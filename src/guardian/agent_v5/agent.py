"""Agent V5 : le modèle Bedrock configuré (Strands) choisit et appelle les outils ; Python calcule.

Déroulé d'une requête :
1. contexte figé et outils neufs pour la requête (aucune préexécution : aucun outil n'est appelé avant le modèle) ;
2. appel de l'agent Strands ;
3. si la question porte sur les risques, la diversification ou l'adéquation au profil et que le Guardian Check n'a pas été appelé :
   UNE relance ciblée, dans la même conversation, qui explique ce qui manque ; Nova fait lui-même l'appel ;
4. s'il manque encore : la réponse est marquée « non confirmée » et les faits réellement obtenus sont joints ;
5. preuve d'origine : chaque appel tracé doit correspondre à un bloc toolUse émis par le modèle dans l'historique Strands, et inversement.
"""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field

from guardian.agent.agent import (DEFAULT_MODEL_ID, DEFAULT_REGION, asks_about_esg, clarification_message,
                                  map_error, profile_conflict, profiles_mentioned)
from guardian.agent.fallback import verified_facts
from guardian.agent.tools import SessionContext
from guardian.agent_v5.tools import RequestTools, freeze

SYSTEM_PROMPT_V5 = """Tu es l'assistant d'Investment Guardian, un outil éducatif de SIMULATION : portefeuilles fictifs, historique 2021-2026 en dollars canadiens. Tu réponds en français clair à une personne non spécialiste.

OUTILS
Tu n'as aucune donnée sur le portefeuille ou le profil sans tes outils : appelle ceux dont la question a besoin AVANT de répondre.
- evaluate_portfolio : composition, poids, rendements, volatilité, plus forte baisse, concentration.
- check_profile_constraints : Guardian Check, statuts de chaque critère pour le profil. Nécessaire dès que la question porte sur les risques, la diversification ou l'adéquation au profil.
- get_profile : profil officiel. compare_scenarios : comparaison A/B (si B est sélectionné). check_esg_preferences : préférences ESG déclarées.
N'appelle pas deux fois le même outil avec les mêmes paramètres.

RÈGLES
1. N'utilise que les valeurs retournées par les outils, telles quelles. Ne calcule, n'additionne ni ne multiplie rien, même pour illustrer une hypothèse.
2. Si tu as appelé check_profile_constraints, nomme les critères pertinents pour la question avec leur statut retourné (OK = Conforme, Attention, Conflit), y compris ceux qui sont conformes, et attribue chaque statut au bon profil et au bon portefeuille. Les repères sont des seuils heuristiques du prototype, pas des normes.
3. Seul un statut du Guardian Check qualifie une mesure. N'écris jamais qu'une mesure est « acceptable », « excessive », « trop élevée », « suffisante » ou « recommandée ». Sans repère (par exemple la part technologique ou obligataire), dis qu'aucun repère ne permet de conclure.
4. FNB : le nombre de lignes n'est pas le nombre de titres détenus. Un FNB contient plusieurs titres, mais sa composition n'est pas mesurée par le prototype.
5. Ce sont des faits historiques simulés. N'affirme aucune corrélation, aucune perte future, aucune récupération garantie. Ne relie pas deux mesures de périodes différentes : la plus forte baisse d'un actif n'a pas forcément eu lieu pendant celle du portefeuille.
6. ESG : une information insuffisante n'est ni un respect ni un non-respect des préférences.
7. Aucun conseil de transaction, même indirect (réduire, augmenter, ajouter, « améliorer » ou « mieux diversifier »). Explique les risques et les compromis.
8. Si une information n'est retournée par aucun outil, dis qu'elle n'est pas mesurée.

FORME
Première phrase : la réponse directe à la question. Puis un ou deux courts paragraphes, sans titres, sans listes et sans gras, 150 mots au plus. Termine par la limite la plus pertinente."""

# Seule règle de dépendance du prototype : une question sur les risques, la diversification ou l'adéquation au profil exige le Guardian Check.
_NEEDS_GUARDIAN = re.compile(r"risqu|diversif|concentr|adapt|adequa|convien|compatib|conform|repere|seuil|guardian|depass|profil|\btrop\b")
GUARDIAN_TOOLS = ("check_profile_constraints", "compare_scenarios")
RELAUNCH = ("[CONTRÔLE DE L'APPLICATION] Ta réponse n'a pas été affichée : la question porte sur {why}, mais tu n'as pas appelé "
            "check_profile_constraints. C'est le seul outil qui donne les statuts du Guardian Check (conforme, attention, conflit) pour ce profil ; "
            "sans lui, aucune conclusion sur les risques ou la diversification ne peut être confirmée. Appelle-le, puis réponds de nouveau, "
            "complètement, à la question de l'utilisateur.")
UNCONFIRMED = ("Analyse non confirmée : le Guardian Check n'a pas été exécuté, même après une relance. Les statuts du profil ne sont pas vérifiés ; "
               "seuls les faits ci-dessous, réellement retournés par les outils, le sont.")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def needs_guardian(question: str) -> bool:
    return bool(_NEEDS_GUARDIAN.search(_fold(question)))


@dataclass
class ResultV5:
    request_id: int
    question: str
    text: str | None
    confirmed: bool                       # False si un contrôle indispensable manque après la relance, ou en cas d'erreur
    notice: str | None                    # message à afficher avec la réponse (non confirmée, erreur)
    relaunched: bool
    calls: list                           # ToolCall, dans l'ordre d'exécution
    model_tool_uses: list                 # (toolUseId, nom) des blocs toolUse émis par le modèle, lus dans l'historique Strands
    provenance_ok: bool                   # appels tracés <-> blocs toolUse du modèle : correspondance exacte
    sdk_tool_counts: dict
    facts: list                           # sections « faits réellement retournés » (fonction V3.3 réutilisée)
    usage: dict = field(default_factory=dict)
    cycles: int | None = None
    duration_s: float = 0.0
    error: dict | None = None
    context: dict = field(default_factory=dict)
    computed: int = 0                     # calculs réellement exécutés (réutilisations exclues)
    messages: list = field(default_factory=list)   # historique Strands de la requête (pour l'audit)
    clarification_profiles: list[tuple[str, str]] = field(default_factory=list)


def _tool_uses(messages: list) -> list:
    out = []
    for m in messages or []:
        if m.get("role") != "assistant":
            continue
        for b in m.get("content") or []:
            if "toolUse" in b:
                out.append((b["toolUse"].get("toolUseId"), b["toolUse"].get("name")))
    return out


class AgentV5:
    def __init__(self, service, ctx: SessionContext, model_id: str | None = None, region: str | None = None, model_factory=None,
                 compact: bool | None = None):
        self.service, self.ctx = service, ctx
        # expérience : vue compacte des résultats transmis au modèle (désactivée par défaut ; GUARDIAN_V5_COMPACT=1 pour l'activer)
        self.compact = compact if compact is not None else os.environ.get("GUARDIAN_V5_COMPACT") == "1"
        self.model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
        self.region = region or os.environ.get("AWS_REGION", DEFAULT_REGION)
        self._model_factory = model_factory
        self._model = None
        self._lock = threading.Lock()
        self._request_id = 0
        self.history: list = []

    def _get_model(self):
        if self._model is None:
            if self._model_factory:
                self._model = self._model_factory()
            else:
                from strands.models import BedrockModel
                self._model = BedrockModel(model_id=self.model_id, region_name=self.region, temperature=0.0, streaming=True,
                                           max_tokens=int(os.environ.get("GUARDIAN_MAX_TOKENS", "1500")))
        return self._model

    def _prompt(self, frozen: SessionContext, question: str) -> str:
        name = self.service.profiles[frozen.profile_id]["display_name"]
        return (f"[CONTEXTE DE L'INTERFACE] Profil actif : {frozen.profile_id} ({name}). Portefeuille A : "
                f"{'sélectionné' if frozen.weights else 'non sélectionné'}. Portefeuille B : {'sélectionné' if frozen.weights_b else 'non sélectionné'}. "
                "Les poids et résultats ne sont disponibles que par les outils. [FIN DU CONTEXTE]\n\n"
                f"Question de l'utilisateur : {question}")

    def ask(self, question: str) -> ResultV5:
        with self._lock:
            r = self._ask(question)
            self.history.append(r)
            return r

    def _ask(self, question: str) -> ResultV5:
        self._request_id += 1
        rid, t0 = self._request_id, time.perf_counter()
        conflict = profile_conflict(question, self.ctx.profile_id, self.service.profiles)
        if conflict:
            return ResultV5(request_id=rid, question=question, text=None, confirmed=False,
                            notice=clarification_message(conflict, self.service.profiles), relaunched=False,
                            calls=[], model_tool_uses=[], provenance_ok=True, sdk_tool_counts={}, facts=[],
                            duration_s=round(time.perf_counter() - t0, 2),
                            context=freeze(self.ctx, {self.ctx.profile_id, *conflict["named"]}).snapshot(),
                            computed=0, messages=[],
                            clarification_profiles=[(pid, self.service.profiles[pid]["display_name"]) for pid in conflict["named"]])
        frozen = freeze(self.ctx, {self.ctx.profile_id, *profiles_mentioned(question, self.service.profiles)})
        rt = RequestTools(self.service, frozen, rid, compact=self.compact)              # outils neufs : aucun résultat d'une requête précédente
        text, error, relaunched, agent = None, None, False, None
        guardian_needed = needs_guardian(question)
        try:
            from strands import Agent
            agent = Agent(model=self._get_model(), tools=rt.strands_tools(), system_prompt=SYSTEM_PROMPT_V5,
                          callback_handler=None, record_direct_tool_call=False)
            text = str(agent(self._prompt(frozen, question))).strip()
            if guardian_needed and not self._guardian_ok(rt.calls):
                relaunched = True
                text = str(agent(RELAUNCH.format(why="les risques, la diversification ou l'adéquation au profil"))).strip()
        except Exception as e:  # noqa: BLE001 - erreur visible, jamais de réponse inventée
            error = map_error(e)
        messages = list(getattr(agent, "messages", []) or [])
        uses = _tool_uses(messages)
        metrics = getattr(agent, "event_loop_metrics", None)
        sdk = {n: m.call_count for n, m in ((getattr(metrics, "tool_metrics", None) or {}).items())}
        traced = [(c.tool_use_id, c.tool) for c in rt.calls]
        provenance_ok = sorted(traced) == sorted(uses) and all(sdk.get(n, 0) == sum(1 for c in rt.calls if c.tool == n) for n in set(sdk) | {c.tool for c in rt.calls})
        confirmed, notice = True, None
        if error is not None:
            confirmed, notice, text = False, f"La génération a échoué : {error['message']}", None
        elif not provenance_ok:
            confirmed, notice = False, "Les appels d'outils tracés ne correspondent pas aux appels émis par le modèle : réponse non confirmée."
        elif guardian_needed and not self._guardian_ok(rt.calls):
            confirmed, notice = False, UNCONFIRMED
        elif asks_about_esg(question) and not any(c.tool == "check_esg_preferences" and c.status == "ok" for c in rt.calls):
            confirmed, notice, text = False, (
                "Analyse non confirmée : l'outil check_esg_preferences n'a pas retourné de résultat pour cette question ESG."
            ), None
        elif any(c.status != "ok" for c in rt.calls):
            notice = "Au moins un outil a échoué : " + ", ".join(sorted({f"{c.tool} ({c.error})" for c in rt.calls if c.status != "ok"}))
            confirmed = self._guardian_ok(rt.calls) or not guardian_needed
        elif not rt.calls and re.search(r"\d", text or ""):
            confirmed, notice, text = False, "Aucun outil n'a retourné de faits pour cette réponse.", None
        if not text and error is None and notice is None:
            confirmed, notice = False, "Le modèle n'a retourné aucun texte."
        usage = {k: int(((getattr(metrics, "accumulated_usage", None) or {}).get(k, 0))) for k in ("inputTokens", "outputTokens", "totalTokens")}
        facts = verified_facts([c for c in rt.calls if c.reused_from is None], question)
        return ResultV5(request_id=rid, question=question, text=text or None, confirmed=confirmed, notice=notice, relaunched=relaunched,
                        calls=list(rt.calls), model_tool_uses=uses, provenance_ok=provenance_ok, sdk_tool_counts=sdk,
                        facts=facts, usage=usage,
                        cycles=getattr(metrics, "cycle_count", None), duration_s=round(time.perf_counter() - t0, 2), error=error,
                        context=frozen.snapshot(), computed=rt.computed, messages=messages)

    @staticmethod
    def _guardian_ok(calls: list) -> bool:
        return any(c.tool in GUARDIAN_TOOLS and c.status == "ok" for c in calls)
