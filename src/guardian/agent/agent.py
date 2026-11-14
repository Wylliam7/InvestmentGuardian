"""Agent Strands + Amazon Bedrock, avec garde-fous : aucune réponse non validée n'est présentée comme vérifiée."""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from guardian.agent.service import GuardianService
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer, sanitize

DEFAULT_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
DEFAULT_REGION = "us-east-1"

SYSTEM_PROMPT = """Tu es l'assistant d'Investment Guardian, un outil éducatif de SIMULATION d'aide à la décision d'investissement. Tu réponds en français, de façon claire et concise (200 mots maximum).

RÈGLES ABSOLUES
1. Pour toute question sur le portefeuille, le risque ou le profil, appelle d'abord les outils : evaluate_portfolio (métriques) ET check_profile_constraints (Guardian Check). Le portefeuille et le profil sont déjà connus du système : ne fournis aucun poids. Chaque question est traitée seule : appelle les outils pour chaque question.
2. Tu ne calcules rien et n'inventes aucun chiffre. N'emploie que les valeurs retournées par les outils, en citant leur unité et la période.
3. Si un outil retourne status "error" ou échoue, dis seulement que l'analyse n'a pas pu être réalisée, rapporte le message d'erreur, et ne donne AUCUN chiffre ni conclusion. Ne calcule jamais à la place de l'outil.
4. Les seuils du Guardian Check sont des heuristiques pédagogiques du prototype. N'écris jamais « seuils recommandés » ni « normes » : écris « seuils heuristiques ». Dis-le quand tu les cites.
5. Le portefeuille est FICTIF et son historique est une SIMULATION rétrospective : n'écris pas que l'investisseur « a connu » ou « a subi » une perte ; écris que le portefeuille simulé aurait reculé de X % sur la période.
6. L'historique décrit le passé (2021-11-12 au 2026-11-12). Ne prédis aucun rendement futur et ne dis pas qu'une performance passée se répétera.
7. Ne donne aucun conseil financier personnalisé et ne propose aucune transaction réelle. Tu peux expliquer des risques et signaler des incohérences avec le profil.
8. Distingue clairement : (a) résultats chiffrés issus des outils, (b) constats du Guardian Check, (c) ton interprétation. Mentionne au moins une limite pertinente (par exemple le biais du survivant ou la fenêtre unique de cinq ans).
9. Si la question sort du périmètre de tes outils, dis-le au lieu de répondre de mémoire."""


@dataclass
class TurnResult:
    """Résultat d'UNE requête utilisateur. `turn` = numéro de requête (pas un cycle interne de Strands, voir `cycles`)."""
    turn: int
    question: str
    text: str | None                  # None si la réponse est retenue
    withheld: bool
    withheld_reason: str | None
    error: dict | None
    tool_records: list
    duration_s: float
    model_id: str
    region: str
    usage: dict = field(default_factory=dict)
    cycles: int | None = None
    started_at: str = ""
    caveat: str | None = None          # avertissement affiché avec la réponse


def map_error(exc: BaseException) -> dict:
    """Traduit une exception AWS/Strands en message compréhensible, sans masquer le type d'erreur."""
    chain = []
    e: BaseException | None = exc
    while e is not None and len(chain) < 5:
        chain.append(e)
        e = e.__cause__ or e.__context__
    code, name = None, type(exc).__name__
    for e in chain:
        resp = getattr(e, "response", None)
        if isinstance(resp, dict) and resp.get("Error", {}).get("Code"):
            code = resp["Error"]["Code"]
            break
    names = " ".join(type(e).__name__ for e in chain)
    raw = sanitize(f"{name}: {exc}")
    if code in {"ExpiredTokenException", "ExpiredToken", "RequestExpired"} or "ExpiredToken" in names:
        kind, msg = "credentials_expired", "Les identifiants AWS temporaires ont expiré. Renouvelez-les puis réessayez."
    elif "NoCredentialsError" in names or "PartialCredentialsError" in names or code == "UnrecognizedClientException":
        kind, msg = "no_credentials", "Aucun identifiant AWS valide n'est disponible pour cette session."
    elif code in {"AccessDeniedException", "AccessDenied"}:
        kind, msg = "access_denied", "Accès refusé à Amazon Bedrock ou au modèle pour ce rôle."
    elif code in {"ThrottlingException", "TooManyRequestsException"} or "Throttl" in names:
        kind, msg = "throttling", "Amazon Bedrock limite temporairement le débit des requêtes. Réessayez dans un instant."
    elif code in {"ResourceNotFoundException", "ValidationException"} or "ModelNotFound" in names:
        kind, msg = "model_error", "Le modèle ou la requête est refusé par Amazon Bedrock (identifiant de modèle, région ou format)."
    elif any(k in names for k in ("EndpointConnectionError", "ConnectTimeout", "ReadTimeout", "ConnectionError")):
        kind, msg = "network", "Amazon Bedrock est injoignable (réseau ou délai dépassé)."
    else:
        kind, msg = "unknown", "Erreur inattendue lors de l'appel à l'agent."
    return {"kind": kind, "message": msg, "code": code, "exception": name, "detail": raw[:500]}


def evaluate_turn(text: str, records: list, sdk_delta: dict) -> tuple[bool, str | None, str | None]:
    """Décide si la réponse peut être affichée. Retourne (retenue, raison, avertissement)."""
    failed = [r for r in records if r.status == "error"]
    if failed:
        names = ", ".join(sorted({r.tool for r in failed}))
        return True, f"Au moins un outil a échoué ({names}). La réponse du modèle n'est pas affichée : l'analyse est incomplète.", None
    sdk_errors = sum(v.get("errors", 0) for v in sdk_delta.values())
    if sdk_errors:
        return True, "Le SDK a signalé une erreur d'appel d'outil non enregistrée par notre journal. Réponse non validée.", None
    traced = {}
    for r in records:
        traced[r.tool] = traced.get(r.tool, 0) + 1
    for name, v in sdk_delta.items():
        if v.get("calls", 0) > traced.get(name, 0):
            return True, f"Le SDK rapporte un appel de l'outil '{name}' absent de notre journal. Réponse non validée.", None
    if not records:
        if re.search(r"\d", text or ""):
            return True, "Aucun outil financier n'a été appelé alors que la réponse contient des chiffres : ils ne sont pas vérifiés.", None
        return False, None, "Aucun outil financier n'a été appelé pour cette réponse."
    return False, None, None


def _tool_snapshot(agent) -> dict:
    out = {}
    metrics = getattr(agent, "event_loop_metrics", None)
    for name, tm in (getattr(metrics, "tool_metrics", None) or {}).items():
        out[name] = {"calls": getattr(tm, "call_count", 0), "errors": getattr(tm, "error_count", 0)}
    return out


def _usage_snapshot(agent) -> dict:
    u = getattr(getattr(agent, "event_loop_metrics", None), "accumulated_usage", None) or {}
    return {k: int(u.get(k, 0)) for k in ("inputTokens", "outputTokens", "totalTokens")}


def _cycles(agent) -> int:
    return int(getattr(getattr(agent, "event_loop_metrics", None), "cycle_count", 0) or 0)


class GuardianAgent:
    """Un agent par session. `model_factory` permet de substituer le modèle dans les tests."""

    def __init__(self, service: GuardianService, ctx: SessionContext, tracer: Tracer | None = None,
                 model_id: str | None = None, region: str | None = None, model_factory=None):
        self.service, self.ctx = service, ctx
        self.tracer = tracer or Tracer()
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
        self.region = region or os.environ.get("AWS_REGION", DEFAULT_REGION)
        self.max_tokens = int(os.environ.get("GUARDIAN_MAX_TOKENS", "1500"))
        self._model_factory = model_factory
        self._ask_lock = threading.Lock()
        self._agent = None
        self.turns: list[TurnResult] = []

    def _get_agent(self):
        if self._agent is None:
            from strands import Agent
            if self._model_factory:
                model = self._model_factory()
            else:
                from strands.models import BedrockModel
                model = BedrockModel(model_id=self.model_id, region_name=self.region,
                                     max_tokens=self.max_tokens, temperature=0.0, streaming=True)
            self._agent = Agent(model=model, tools=build_tools(self.service, self.ctx, self.tracer),
                                system_prompt=SYSTEM_PROMPT, callback_handler=None)
        return self._agent

    def ask(self, question: str) -> TurnResult:
        """Traite UNE requête utilisateur (= un « tour » de notre journal).

        - Une seule requête à la fois par agent (verrou) : les appels d'outils ne peuvent pas être
          attribués à la mauvaise requête.
        - Chaque requête repart d'une conversation vide : un résultat d'outil d'une requête précédente
          ne peut jamais fonder la réponse d'une nouvelle requête. La validation n'utilise que les outils
          exécutés pendant CETTE requête, quel que soit le nombre de cycles internes de Strands.
        """
        with self._ask_lock:
            return self._ask_locked(question)

    def _ask_locked(self, question: str) -> TurnResult:
        turn = self.tracer.start_turn()
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        text, error, usage, cycles = None, None, {}, None
        sdk_delta: dict = {}
        agent = None
        n_msgs = 0
        try:
            agent = self._get_agent()
            agent.messages.clear()          # requête indépendante : aucune mémoire des résultats d'outils précédents
            n_msgs = len(agent.messages)
            tools_before, usage_before, cycles_before = _tool_snapshot(agent), _usage_snapshot(agent), _cycles(agent)
            result = agent(question)
            text = str(result).strip()
            after = _tool_snapshot(agent)
            sdk_delta = {n: {"calls": v["calls"] - tools_before.get(n, {}).get("calls", 0),
                             "errors": v["errors"] - tools_before.get(n, {}).get("errors", 0)}
                         for n, v in after.items()}
            sdk_delta = {n: v for n, v in sdk_delta.items() if v["calls"] or v["errors"]}
            ua = _usage_snapshot(agent)
            usage = {k: ua[k] - usage_before[k] for k in ua}
            cycles = _cycles(agent) - cycles_before
        except Exception as e:  # noqa: BLE001
            error = map_error(e)
        records = self.tracer.for_turn(turn)
        withheld, reason, caveat = False, None, None
        if error is not None:
            withheld, reason = True, "L'appel à l'agent a échoué : aucune réponse n'est affichée."
            text = None
        else:
            withheld, reason, caveat = evaluate_turn(text or "", records, sdk_delta)
            if not (text or "").strip():
                withheld, reason = True, "Le modèle a retourné une réponse vide."
        if withheld and agent is not None:
            del agent.messages[n_msgs:]   # ne pas réinjecter une réponse non validée dans le contexte
            text = None
        tr = TurnResult(turn=turn, question=question, text=text, withheld=withheld, withheld_reason=reason,
                        error=error, tool_records=records, duration_s=round(time.perf_counter() - t0, 2),
                        model_id=self.model_id, region=self.region, usage=usage, cycles=cycles,
                        started_at=started, caveat=caveat)
        self.turns.append(tr)
        return tr
