"""Outils de l'agent V5, limités à UNE requête.

- Les calculs sont faits par les outils V3.3 existants (`guardian.agent.tools.build_tools`) : aucune formule n'est dupliquée, résultats identiques.
- Chaque appel n'est exécuté que lorsque Strands le demande, à la suite d'un bloc `toolUse` émis par le modèle. Son `toolUseId`
  (identifiant attribué par Bedrock au bloc toolUse) est enregistré : il permet de prouver dans l'historique Strands que l'appel vient du modèle.
- Contexte figé au début de la requête (copie des poids A/B et du profil actif) ; un objet neuf par requête, donc aucun résultat d'une ancienne requête.
- Appel identique (même outil, mêmes paramètres résolus) dans la même requête : le résultat déjà calculé est renvoyé, et l'appel est tracé comme réutilisation.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from strands import ToolContext, tool

from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.agent_v5.compact import compact as compact_view

TOOL_ARGS = {
    "get_profile": (("profile_id", ""),),
    "evaluate_portfolio": (("portfolio", "A"), ("start_date", ""), ("end_date", "")),
    "check_profile_constraints": (("profile_id", ""), ("portfolio", "A"), ("start_date", ""), ("end_date", "")),
    "compare_scenarios": (("profile_id", ""), ("start_date", ""), ("end_date", "")),
    "check_esg_preferences": (("profile_id", ""), ("portfolio", "A")),
}


@dataclass
class ToolCall:
    id: int                     # rang de l'appel dans la requête
    request_id: int
    tool: str
    tool_use_id: str            # identifiant du bloc toolUse émis par le modèle (preuve d'origine)
    arguments: dict             # paramètres résolus (profil vide = profil actif, portefeuille en majuscules)
    status: str                 # "ok" | "error"
    duration_ms: float
    result: dict | None
    error: str | None
    reused_from: int | None     # id de l'appel dont le résultat est réutilisé (aucun recalcul)
    origin: str = "model"       # tous les appels V5 sont déclenchés par un toolUse du modèle
    model_view: dict | None = None   # ce qui a réellement été transmis au modèle (résultat complet, ou vue compacte si activée)
    compacted: bool = False


def freeze(ctx: SessionContext, allowed_profiles: set) -> SessionContext:
    return SessionContext(weights=dict(ctx.weights or {}), profile_id=ctx.profile_id,
                          weights_b=dict(ctx.weights_b) if ctx.weights_b else None,
                          fail_tools=set(ctx.fail_tools or ()), allowed_profiles=set(allowed_profiles))


class RequestTools:
    def __init__(self, service, frozen: SessionContext, request_id: int, compact: bool = False):
        self.ctx, self.request_id, self.compact = frozen, request_id, compact
        self._scratch = Tracer()                                   # journal interne des outils V3.3 (une entrée par calcul réel)
        self._legacy = {t.tool_spec["name"]: t for t in build_tools(service, frozen, self._scratch)}
        self.calls: list[ToolCall] = []
        self._cache: dict = {}
        self._lock = threading.Lock()                              # Strands peut exécuter des outils en parallèle (fils)

    @property
    def computed(self) -> int:
        """Nombre de calculs réellement exécutés par les outils V3.3."""
        return len(self._scratch.records)

    def _resolve(self, tool_name: str, kwargs: dict) -> dict:
        out = {}
        for name, default in TOOL_ARGS[tool_name]:
            v = str(kwargs.get(name, default) or default).strip()
            if name == "profile_id":
                v = v.lower() or self.ctx.profile_id
            elif name == "portfolio":
                v = v.upper() or "A"
            out[name] = v
        return out

    def run(self, tool_name: str, kwargs: dict, tool_use_id: str) -> dict:
        args = self._resolve(tool_name, kwargs)
        key = (tool_name, tuple(sorted(args.items())))
        with self._lock:
            if key in self._cache:
                first = self._cache[key]
                view = first.model_view if first.model_view is not None else self._error_payload(tool_name, first.error)
                self.calls.append(ToolCall(len(self.calls) + 1, self.request_id, tool_name, tool_use_id, args, first.status, 0.0,
                                           first.result, first.error, reused_from=first.id, model_view=view, compacted=first.compacted))
                return view
            t0 = time.perf_counter()
            n = len(self._scratch.records)
            out = self._legacy[tool_name](**args)
            src = self._scratch.records[n]
            view = compact_view(tool_name, out) if self.compact else out      # la vue compacte est construite APRÈS l'exécution réelle
            call = ToolCall(len(self.calls) + 1, self.request_id, tool_name, tool_use_id, args, src.status,
                            round((time.perf_counter() - t0) * 1000, 2), src.result, src.error, reused_from=None,
                            model_view=view, compacted=self.compact and view is not out)
            self.calls.append(call)
            self._cache[key] = call
            return view

    @staticmethod
    def _error_payload(tool_name: str, error: str | None) -> dict:
        return {"status": "error", "tool": tool_name, "message": error,
                "instruction": "L'outil a échoué : n'avance aucun chiffre ni conclusion qui en dépend ; signale la limite."}

    def strands_tools(self) -> list:
        rt = self

        def uid(ctx: ToolContext) -> str:
            return str((ctx.tool_use or {}).get("toolUseId", ""))

        @tool(context=True)
        def get_profile(profile_id: str = "", tool_context: ToolContext = None) -> dict:
            """Profil officiel d'un investisseur fictif (objectif, horizon, niveau de risque, préférences) et repères heuristiques du Guardian Check.

            Args:
                profile_id: "robert", "amira" ou "mateo" ; vide = profil actif.
            """
            return rt.run("get_profile", {"profile_id": profile_id}, uid(tool_context))

        @tool(context=True)
        def evaluate_portfolio(portfolio: str = "A", start_date: str = "", end_date: str = "", tool_context: ToolContext = None) -> dict:
            """Composition et métriques historiques en CAD d'un portefeuille sélectionné : poids, classes d'actifs, rendement, volatilité,
            plus forte baisse, concentration, nombre effectif de positions, statistiques par actif, FNB détenus.

            Args:
                portfolio: "A" ou "B".
                start_date: début AAAA-MM-JJ (vide = période complète).
                end_date: fin AAAA-MM-JJ (vide = période complète).
            """
            return rt.run("evaluate_portfolio", {"portfolio": portfolio, "start_date": start_date, "end_date": end_date}, uid(tool_context))

        @tool(context=True)
        def check_profile_constraints(profile_id: str = "", portfolio: str = "A", start_date: str = "", end_date: str = "",
                                      tool_context: ToolContext = None) -> dict:
            """Guardian Check : confronte un portefeuille au profil. Retourne pour chaque critère (R1 concentration, R2 actifs volatils,
            R4 volatilité, R5 plus forte baisse, R7 diversification, R10 contexte) le statut (OK = conforme, ATTENTION, CONFLIT, INFO),
            la valeur mesurée et les repères heuristiques. Indispensable pour juger les risques, la diversification ou l'adéquation au profil.

            Args:
                profile_id: "robert", "amira" ou "mateo" ; vide = profil actif.
                portfolio: "A" ou "B".
                start_date: début AAAA-MM-JJ (vide = période complète).
                end_date: fin AAAA-MM-JJ (vide = période complète).
            """
            return rt.run("check_profile_constraints", {"profile_id": profile_id, "portfolio": portfolio, "start_date": start_date,
                                                        "end_date": end_date}, uid(tool_context))

        @tool(context=True)
        def compare_scenarios(profile_id: str = "", start_date: str = "", end_date: str = "", tool_context: ToolContext = None) -> dict:
            """Compare les portefeuilles A et B sur la même période (métriques, Guardian Check de chacun, écarts, compromis historiques).
            Exige qu'un portefeuille B soit sélectionné.

            Args:
                profile_id: "robert", "amira" ou "mateo" ; vide = profil actif.
                start_date: début AAAA-MM-JJ (vide = période complète).
                end_date: fin AAAA-MM-JJ (vide = période complète).
            """
            return rt.run("compare_scenarios", {"profile_id": profile_id, "start_date": start_date, "end_date": end_date}, uid(tool_context))

        @tool(context=True)
        def check_esg_preferences(profile_id: str = "", portfolio: str = "A", tool_context: ToolContext = None) -> dict:
            """Cohérence d'un portefeuille avec les préférences ESG DÉCLARÉES d'un profil (sources, couverture, catégories documentées ; aucun score).

            Args:
                profile_id: "robert", "amira" ou "mateo" ; vide = profil actif.
                portfolio: "A" ou "B".
            """
            return rt.run("check_esg_preferences", {"profile_id": profile_id, "portfolio": portfolio}, uid(tool_context))

        return [get_profile, evaluate_portfolio, check_profile_constraints, compare_scenarios, check_esg_preferences]
