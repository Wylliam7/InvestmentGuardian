"""Agent Strands + Amazon Bedrock, avec garde-fous : aucune réponse non validée n'est présentée comme vérifiée."""
from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

from guardian.agent.claims import check_claims
from guardian.agent.fallback import build_fallback
from guardian.agent.service import GuardianService
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer, sanitize

DEFAULT_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
DEFAULT_REGION = "us-east-1"

SYSTEM_PROMPT = """Tu es l'assistant d'Investment Guardian, un outil éducatif de SIMULATION d'aide à la décision d'investissement. Tu réponds en français, de façon claire et concise (250 mots maximum).

CONTEXTE : l'utilisateur sélectionne dans l'interface un profil (Robert ou Amira), un portefeuille fictif A et parfois un portefeuille B. Tu ne connais ni les poids ni les résultats : seuls les outils les fournissent.

OUTILS
- get_profile : objectif, horizon, tolérance, préférences officielles d'un persona et seuils heuristiques appliqués.
- evaluate_portfolio : métriques historiques en CAD du portefeuille A ou B.
- check_profile_constraints : Guardian Check d'un portefeuille pour un profil. N'utilise un profile_id différent du profil actif QUE si l'utilisateur nomme explicitement ce profil dans sa question ; sinon laisse profile_id vide. Le système refuse les autres profils.
- compare_scenarios : comparaison A/B sur la même période (exige qu'un portefeuille B soit sélectionné).
- check_esg_preferences : cohérence d'un portefeuille avec les préférences ESG DÉCLARÉES d'un profil (module distinct du Guardian Check financier).

RÈGLES ABSOLUES
1. Pour toute question sur un portefeuille, un risque ou un profil, appelle les outils pertinents AVANT de répondre, à chaque question : chaque question est traitée seule. Ne fournis jamais de poids aux outils. Un bloc [CONTEXTE DE L'INTERFACE] précède la question : il indique le profil actif et si un portefeuille B est défini. Si l'utilisateur demande de comparer ou de mettre en regard deux allocations et que B est défini, appelle compare_scenarios.
2. Tu ne calcules rien et n'inventes aucun chiffre ni aucune pondération. N'emploie que les valeurs retournées par les outils, avec leur unité et la période.
3. Si un outil retourne status "error" ou échoue, dis seulement que l'analyse n'a pas pu être réalisée, rapporte le message d'erreur, et ne donne AUCUN chiffre ni conclusion. Ne calcule jamais à la place de l'outil.
4. Les seuils du Guardian Check sont des heuristiques pédagogiques du prototype : écris « seuils heuristiques du prototype », jamais « seuils recommandés », « normes » ou « règles réglementaires ».
5. Le portefeuille est FICTIF et son historique est une SIMULATION rétrospective : écris que le portefeuille simulé aurait reculé de X % sur la période, pas que l'investisseur a subi une perte.
6. L'historique décrit le passé (2021-11-12 au 2026-11-12). Ne prédis aucun rendement futur et ne dis pas qu'une performance passée se répétera.
7. Ne donne aucun conseil financier personnalisé et ne propose aucune transaction. Ne dis pas qu'un portefeuille est « meilleur » ou « le bon choix » : décris des compromis historiques entre rendement et risque.
8. Formule avec prudence. Écris par exemple « présente un conflit potentiel avec les objectifs déclarés de Robert selon les seuils heuristiques du prototype », jamais « est incompatible avec Robert » ni « objectivement risqué ». Ne présume pas qu'une baisse historique dépasse la tolérance personnelle réelle de l'investisseur.
9. Structure ta réponse en quatre parties courtes : (a) Faits historiques calculés ; (b) Seuils heuristiques et constats du Guardian Check ; (c) Objectifs déclarés du persona : cite UNIQUEMENT le champ « profile » retourné par un outil (age, horizon, risque, objectif, préférences), sans rien ajouter ni reformuler en chiffres ; si tu ne l'as pas, appelle get_profile ; (d) Interprétation (ton avis, présenté comme tel). Mentionne au moins une limite (biais du survivant, fenêtre unique de cinq ans, FNB non décomposés). Si un volet n'a pas été examiné par un outil dans CETTE réponse (par exemple les constats financiers pour une question purement ESG), écris « non examiné dans cette réponse » au lieu de le remplir : n'affirme jamais qu'un repère financier est ou n'est pas franchi sans avoir appelé check_profile_constraints.
10. Si la question sort du périmètre de tes outils, dis-le au lieu de répondre de mémoire.
12. Ne prête au persona aucune émotion, aucun besoin ni aucune situation absents du profil retourné par l'outil (par exemple anxiété, besoin de liquidités) : cite seulement ses objectifs et préférences officiels.
11. ESG : pour toute question sur l'ESG, les controverses, la durabilité ou l'éthique, appelle check_esg_preferences. N'invente JAMAIS une controverse, une note ESG, un score, un classement ou une source : cite uniquement ce que l'outil retourne (états, couverture, sources avec leur date). Distingue toujours « controverse documentée à examiner », « aucune controverse identifiée dans les sources consultées » et « information insuffisante » : une absence de résultat n'est pas une preuve d'absence de controverse. Si l'état global est « information insuffisante », dis que tu ne peux pas confirmer que le portefeuille respecte toutes les préférences ESG, résume ce qui est connu et ce qui reste à vérifier, sans présenter la part non évaluée comme conforme. N'écris jamais qu'un actif ou un portefeuille est « durable », « éthique » ou « conforme ESG ». Une décision d'exclusion ou d'observation est celle de la source, pas un jugement de culpabilité. Ne combine jamais risque financier et ESG en une note unique, et traite-les dans des parties séparées. Les FNB ne sont pas décomposés : n'affirme rien sur leurs entreprises sous-jacentes. Ne qualifie jamais une « information insuffisante » de « conflit » : un conflit potentiel suppose une information documentée ou un repère franchi. Recopie les pourcentages de couverture exactement tels que l'outil les retourne (ne les additionne pas, ne les arrondis pas autrement) et cite le nombre exact de sources de la liste « sources ».
13. Distinctions ESG obligatoires. Exclusion et mise sous observation sont deux décisions différentes : une observation n'est pas une exclusion et est moins forte. Environnement ou social et gouvernance sont deux dimensions différentes. Utilise les champs structurés de l'outil : `documented_categories` (critère lié à la préférence déclarée, par exemple une exclusion environnementale) et `complementary_information` (hors critère déclaré, par exemple une observation de gouvernance ou de crime financier). Pour chaque catégorie, nomme la décision (decision_label), la dimension (dimension_label), le poids (weight_pct) et les tickers, avec la source et la date de publication de la décision. Présente l'information complémentaire séparément, comme information complémentaire, JAMAIS comme un conflit environnemental ou social ni comme un conflit avec les préférences. N'additionne JAMAIS des catégories différentes en un seul pourcentage (n'écris pas « 30 % en conflit avec les préférences ESG ») ; recopie `categories_summary` ou les poids de chaque catégorie. N'écris aucune affirmation sans preuve : si le champ n'existe pas, ne l'invente pas. Cite le critère invoqué tel que retourné (criterion_fr) sans le reformuler en accusation, en fait établi ou en jugement : écris « la source a placé X sous observation pour le critère : … », jamais « X est accusée de … ». Le module ESG n'utilise aucun seuil : n'écris pas « seuils heuristiques » à propos de l'ESG. Une ligne « non applicable » (par exemple l'or) n'a pas été « vérifiée » : ne la compte pas parmi les lignes vérifiées.
14. FNB. Une position de X % dans un FNB diversifié n'est pas équivalente à une position de X % dans une entreprise individuelle : un FNB détient plusieurs titres. Quand tu parles de concentration ou de la plus grande position, regarde `fund_exposure` : si `largest_position_is_fund` est vrai, ou si des FNB sont détenus, reprends sa `pedagogical_note` (le repère s'applique pareillement à une action et à un FNB, ce qui peut surestimer la concentration réelle) et rappelle que la diversification sous-jacente des FNB n'est pas mesurée. Ne change ni un poids, ni un indice, ni un seuil, ni un statut : seul le commentaire change.
15. CONTRAT D'EXPLICATION. Chaque outil renvoie `key_facts` : des faits déjà calculés par Python (trois plus grandes positions et leur total, indicateurs, constats et repères du Guardian Check, part technologique directement mesurée, couverture et catégories ESG). Appuie-toi d'abord sur eux et recopie leurs valeurs avec le bon titre, le bon indicateur et la bonne catégorie. Ne recalcule et n'additionne aucun pourcentage. Une part sectorielle partielle n'est pas une exposition totale. Aucun seuil n'existe pour l'ESG ni pour la technologie. Sépare clairement les faits vérifiés, ton interprétation et les informations manquantes. Décris les compromis sans conseiller d'acheter, de vendre, de réduire ou de rééquilibrer. Question hypothétique : donne seulement les expositions connues ; aucun scénario, probabilité, corrélation ni perte future n'est calculé."""


EXPLAIN_RISKS_LABEL = "Explique-moi mes risques avec l'IA"
EXPLAIN_RISKS_REQUIRED = ("evaluate_portfolio", "check_profile_constraints")


EXPLAIN_ESG_REQUIRED = ("check_esg_preferences",)


def explain_risks_task(profile_name: str, has_esg: bool = False) -> str:
    """Consigne interne du bouton « Explique-moi mes risques avec l'IA » (même agent, même mécanisme que l'assistant)."""
    esg = ((" Ce profil a des préférences ESG : appelle aussi check_esg_preferences et présente-les dans une section séparée **Préférences ESG** "
            "(état global, part du portefeuille vérifiée, part non évaluable, sources consultées avec leur date), sans les combiner avec les risques "
            "financiers et sans jamais donner de note. Distingue exclusion et observation, environnement/social et gouvernance : présente chaque catégorie "
            "documentée séparément avec son poids, et l'information complémentaire (hors critère déclaré) à part ; n'additionne jamais les catégories en un "
            "seul pourcentage « en conflit ». N'écris jamais que le portefeuille est durable ou conforme ESG.") if has_esg else "")
    etf = (" Si la plus grande position est un FNB (fund_exposure.largest_position_is_fund), précise qu'une position de X % dans un FNB diversifié "
           "n'est pas équivalente à une position de X % dans une entreprise individuelle et que la diversification sous-jacente des FNB n'est pas mesurée : "
           "reprends dans **Limites** la fund_exposure.pedagogical_note, sans changer un poids ni un statut.")
    return (
        f"TÂCHE : explique à une personne non spécialiste, en français simple et en 250 mots maximum, les deux ou trois principaux risques du "
        f"portefeuille A pour {profile_name}. Appelle evaluate_portfolio et check_profile_constraints (et get_profile si tu as besoin du profil). "
        "Structure ta réponse avec ces cinq titres : **En bref** (deux phrases) ; **Pourquoi cela compte pour "
        f"{profile_name}** (relie chaque enjeu à l'objectif et à l'horizon retournés par l'outil) ; **Les faits historiques utilisés** "
        "(trois ou quatre puces, valeurs exactement telles que retournées par les outils, avec la période et la devise) ; **Pour aller plus loin** "
        "(une piste d'exploration neutre, par exemple comparer avec une autre répartition ; jamais une recommandation d'achat ou de vente) ; "
        "**Limites** (une ou deux limites pertinentes). Reprends les statuts tels que retournés par les outils : tu ne changes ni une valeur, "
        "ni un repère, ni un statut. Évite le jargon : n'écris ni « seuil de conflit », ni « drawdown », ni « HHI », ni « règle R1 » ; "
        "écris « repère de vigilance » (ou « repère pédagogique »), « plus forte baisse historique » et « fluctuations ». "
        "Regroupe les constats liés : si la même position pèse lourd, est très fluctuante et explique les fluctuations du portefeuille, "
        "présente-les comme UN enjeu et non comme trois risques indépendants. N'annonce jamais plus d'enjeux qu'il n'en existe réellement." + etf + esg)


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
    context: dict = field(default_factory=dict)   # profil et portefeuilles A/B réellement utilisés pour cette requête
    unmatched_numbers: tuple = ()      # pourcentages du texte absents des résultats d'outils (contrôle de cohérence)
    clarification: str | None = None   # demande de précision à l'utilisateur (aucun appel au modèle ni aux outils)
    clarification_profiles: tuple = ()  # profils à proposer de sélectionner
    kind: str = "question"                # "question" (assistant) ou "explain_risks" (bouton « Explique-moi mes risques »)
    claims: dict | None = None            # résultat du contrôle déterministe des affirmations essentielles (partiel, voir claims.py)
    fallback: str | None = None           # faits vérifiés issus des outils, affichés quand le texte du modèle est retenu pour affirmation non confirmée


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


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def profiles_mentioned(question: str, profiles: dict) -> list[str]:
    """Profils nommés explicitement dans la question (nom d'affichage ou identifiant, insensible à la casse et aux accents)."""
    q = _norm(question or "")
    found = []
    for pid, prof in profiles.items():
        names = {_norm(pid), _norm(prof.get("display_name", pid))}
        if any(re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", q) for n in names):
            found.append(pid)
    return found


def profile_conflict(question: str, active: str, profiles: dict) -> dict | None:
    """Conflit si la question nomme un ou plusieurs profils SANS nommer le profil actif de l'interface.

    Si le profil actif est nommé (seul ou avec d'autres), il n'y a pas de conflit : les autres profils nommés
    sont explicitement demandés par l'utilisateur. Sans aucun profil nommé, c'est le profil actif qui s'applique.
    """
    named = profiles_mentioned(question, profiles)
    if named and active not in named:
        return {"named": named, "active": active}
    return None


def clarification_message(conflict: dict, profiles: dict) -> str:
    names = " et ".join(profiles[p]["display_name"] for p in conflict["named"])
    active = profiles[conflict["active"]]["display_name"]
    return (f"Votre question demande une analyse pour **{names}**, mais le profil sélectionné dans l'interface est **{active}**. "
            f"Sélectionnez {names} dans le sélecteur de profil, ou reformulez votre question pour {active}. "
            "Aucune analyse n'a été lancée et aucun outil n'a été appelé.")


_PCT_RE = re.compile(r"(?<![\d.,])[−-]?(\d+(?:[.,]\d+)?)\s*%")


def _collect_numbers(obj, out: set) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(abs(float(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)


def unmatched_percentages(text: str, records: list) -> list[str]:
    """Pourcentages cités dans le texte qui ne figurent dans aucun résultat d'outil de CETTE requête (à l'arrondi affiché près).

    Contrôle de cohérence, pas une preuve : 0 % et 100 % sont ignorés ; un pourcentage calculé par le modèle (somme, complément) est signalé.
    """
    avail: set = set()
    for r in records:
        if r.status == "ok" and r.result:
            _collect_numbers(r.result, avail)
    candidates = set(avail) | {v * 100 for v in avail if v <= 1.5}          # les seuils et poids sont parfois des fractions
    bad = []
    for m in _PCT_RE.finditer(text or ""):
        raw = m.group(1)
        val = float(raw.replace(",", "."))
        if val in (0.0, 100.0):
            continue
        d = len(raw.split(",")[1]) if "," in raw else (len(raw.split(".")[1]) if "." in raw else 0)
        tol = 0.5 * 10 ** (-d) + 1e-9
        if not any(abs(c - val) <= tol for c in candidates):
            bad.append(m.group(0).strip().lstrip("−-").strip())
    return list(dict.fromkeys(bad))


_ESG_RE = re.compile(r"\besg\b|controvers|durab|ethiq")


def asks_about_esg(question: str) -> bool:
    """Vrai si la question parle d'ESG, de controverses, de durabilité ou d'éthique (insensible à la casse et aux accents)."""
    return bool(_ESG_RE.search(_norm(question or "")))


_RANGE_RE = re.compile(r"(\d{1,2})\s*(?:-|–|—|à)\s*(\d{1,2})\s*ans")
_OR_MORE_RE = re.compile(r"(\d{1,2})\s*ans\s+ou\s+plus")


def unsupported_horizons(text: str, profiles: dict) -> list[str]:
    """Horizons de placement cités dans le texte qui ne correspondent à aucun profil officiel (vérification déterministe)."""
    ranges = {(p["horizon_years_min"], p["horizon_years_max"]) for p in profiles.values() if p.get("horizon_years_max")}
    minimums = {p["horizon_years_min"] for p in profiles.values() if not p.get("horizon_years_max")}
    bad = []
    for a, b in _RANGE_RE.findall(text or ""):
        if (int(a), int(b)) not in ranges:
            bad.append(f"{a} à {b} ans")
    for a in _OR_MORE_RE.findall(text or ""):
        if int(a) not in minimums:
            bad.append(f"{a} ans ou plus")
    return bad


def evaluate_turn(text: str, records: list, sdk_delta: dict, profiles: dict | None = None) -> tuple[bool, str | None, str | None]:
    """Décide si la réponse peut être affichée. Retourne (retenue, raison, avertissement)."""
    failed = [r for r in records if r.status == "error"]
    if failed:
        names = ", ".join(sorted({r.tool for r in failed}))
        msgs = " ; ".join(sorted({str(getattr(r, "error", "") or "") for r in failed}))[:300]
        detail = f" Message : {msgs}" if msgs else ""
        return True, f"Au moins un outil a échoué ({names}). La réponse du modèle n'est pas affichée : l'analyse est incomplète.{detail}", None
    sdk_errors = sum(v.get("errors", 0) for v in sdk_delta.values())
    if sdk_errors:
        return True, "Le SDK a signalé une erreur d'appel d'outil non enregistrée par notre journal. Réponse non validée.", None
    traced = {}
    for r in records:
        traced[r.tool] = traced.get(r.tool, 0) + 1
    for name, v in sdk_delta.items():
        if v.get("calls", 0) > traced.get(name, 0):
            return True, f"Le SDK rapporte un appel de l'outil '{name}' absent de notre journal. Réponse non validée.", None
    bad = unsupported_horizons(text, profiles) if profiles else []
    if bad:
        return True, (f"Le texte du modèle cite un horizon de placement ({', '.join(bad)}) qui ne correspond à aucun profil officiel : "
                      "réponse non validée."), None
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

    def ask(self, question: str, task: str | None = None, required_tools: tuple = (), kind: str = "question") -> TurnResult:
        """Traite UNE requête utilisateur (= un « tour » de notre journal).

        - Une seule requête à la fois par agent (verrou) : les appels d'outils ne peuvent pas être
          attribués à la mauvaise requête.
        - Chaque requête repart d'une conversation vide : un résultat d'outil d'une requête précédente
          ne peut jamais fonder la réponse d'une nouvelle requête. La validation n'utilise que les outils
          exécutés pendant CETTE requête, quel que soit le nombre de cycles internes de Strands.
        """
        if asks_about_esg(question) and "check_esg_preferences" not in required_tools:
            required_tools = (*required_tools, "check_esg_preferences")     # toute réponse sur l'ESG doit s'appuyer sur l'outil ESG
        with self._ask_lock:
            tr = self._ask_locked(question, task, tuple(required_tools))
            tr.kind = kind
            return tr

    def compose_prompt(self, question: str, task: str | None = None) -> str:
        """Reconstruit EXPLICITEMENT le contexte de la requête depuis l'interface (profil et disponibilité de A/B).

        Aucun poids ni résultat n'est transmis : le modèle doit les obtenir par les outils.
        """
        pid = self.ctx.profile_id
        name = self.service.profiles.get(pid, {}).get("display_name", pid)
        b = ("défini : compare_scenarios est disponible pour comparer A et B" if self.ctx.weights_b
             else "non défini : compare_scenarios n'est pas disponible")
        named = profiles_mentioned(question, self.service.profiles)
        allowed = sorted({pid, *named})
        return (f"[CONTEXTE DE L'INTERFACE, pas une question de l'utilisateur]\n"
                f"Profil actif : {pid} ({name}).\nProfils autorisés pour cette requête : {', '.join(allowed)} "
                f"(le profil actif, plus ceux que l'utilisateur nomme explicitement ; n'en utilise aucun autre).\nPortefeuille A : {'défini' if self.ctx.weights else 'non défini'}.\nPortefeuille B : {b}.\n"
                f"[FIN DU CONTEXTE]\n\n" + (f"{task}\n\n" if task else "") + f"Question de l'utilisateur : {question}")

    def _ask_locked(self, question: str, task: str | None = None, required_tools: tuple = ()) -> TurnResult:
        turn = self.tracer.start_turn()
        context = self.ctx.snapshot()      # contexte figé au début de la requête
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        text, error, usage, cycles = None, None, {}, None
        sdk_delta: dict = {}
        agent = None
        n_msgs = 0
        conflict = profile_conflict(question, self.ctx.profile_id, self.service.profiles)
        if conflict:
            tr = TurnResult(turn=turn, question=question, text=None, withheld=False, withheld_reason=None, error=None,
                            tool_records=[], duration_s=round(time.perf_counter() - t0, 2), model_id=self.model_id,
                            region=self.region, started_at=started, context=context,
                            clarification=clarification_message(conflict, self.service.profiles),
                            clarification_profiles=tuple(conflict["named"]))
            self.turns.append(tr)
            return tr
        # profils que les outils peuvent utiliser pour CETTE requête : le profil actif + ceux que l'utilisateur nomme
        self.ctx.allowed_profiles = {self.ctx.profile_id, *profiles_mentioned(question, self.service.profiles)}
        try:
            agent = self._get_agent()
            agent.messages.clear()          # requête indépendante : aucune mémoire des résultats d'outils précédents
            n_msgs = len(agent.messages)
            tools_before, usage_before, cycles_before = _tool_snapshot(agent), _usage_snapshot(agent), _cycles(agent)
            result = agent(self.compose_prompt(question, task))
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
        unmatched_list: list = []
        if error is not None:
            withheld, reason = True, "L'appel à l'agent a échoué : aucune réponse n'est affichée."
            text = None
        else:
            withheld, reason, caveat = evaluate_turn(text or "", records, sdk_delta, self.service.profiles)
            if not (text or "").strip():
                withheld, reason = True, "Le modèle a retourné une réponse vide."
            unmatched = unmatched_percentages(text, records) if (text and not withheld and records) else []
            unmatched_list = unmatched
            if unmatched:
                note = ("Attention : ces pourcentages du texte n'ont pas été retrouvés tels quels dans les résultats des outils de cette requête : "
                        f"{', '.join(unmatched)}. Ils peuvent avoir été calculés ou arrondis par le modèle ; fiez-vous aux chiffres affichés par l'application.")
                caveat = f"{caveat} {note}" if caveat else note
            missing = [n for n in required_tools if not any(r.tool == n and r.status == "ok" for r in records)]
            if not withheld and missing:
                withheld = True
                reason = ("Les outils financiers attendus pour cette demande n'ont pas tous été exécutés avec succès (manquant : "
                          f"{', '.join(missing)}). La réponse du modèle n'est pas affichée.")
        claims_dict, fallback = None, None
        if not withheld and text and records and error is None:
            universe = getattr(getattr(self.service, "bundle", None), "universe", None)
            crep = check_claims(text, records, self.service.profiles, self.ctx.profile_id, universe)
            claims_dict = crep.to_dict()
            if not crep.ok:
                withheld = True
                kinds = ", ".join(sorted({v.category for v in crep.violations}))
                reason = (f"Le contrôle automatique a relevé {len(crep.violations)} affirmation(s) du texte de l'IA non conforme(s) aux résultats des outils "
                          f"({kinds}). Le texte n'est pas affiché comme conclusion fiable.")
                fallback = build_fallback(records, question)
        if withheld and agent is not None:
            del agent.messages[n_msgs:]   # ne pas réinjecter une réponse non validée dans le contexte
            text = None
        tr = TurnResult(turn=turn, question=question, text=text, withheld=withheld, withheld_reason=reason,
                        error=error, tool_records=records, duration_s=round(time.perf_counter() - t0, 2),
                        model_id=self.model_id, region=self.region, usage=usage, cycles=cycles,
                        started_at=started, caveat=caveat, context=context, unmatched_numbers=tuple(unmatched_list),
                        claims=claims_dict, fallback=fallback)
        self.turns.append(tr)
        return tr
