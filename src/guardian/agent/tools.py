"""Outils Strands exposés à l'agent (V1 : quatre outils financiers réels).

Les portefeuilles A/B et le profil actif viennent du contexte de session (côté serveur, mis à jour par l'interface) :
le modèle ne retranscrit jamais de poids. Chaque appel est enregistré dans le Tracer, succès ou échec.
Aucun décorateur ne masque la signature des outils (leçon de la phase 0).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from strands import tool

from guardian.agent.service import GuardianService
from guardian.agent.tracer import Tracer, digest, sanitize

ERROR_INSTRUCTION = ("L'outil a échoué. N'avance aucun chiffre ni conclusion financière ; "
                     "indique seulement que l'analyse n'a pas pu être réalisée et rapporte le message d'erreur.")


@dataclass
class SessionContext:
    weights: dict                      # portefeuille A : poids cibles (fractions)
    profile_id: str
    weights_b: dict | None = None      # portefeuille B (comparaison), s'il est défini
    fail_tools: set = field(default_factory=set)   # injection de pannes (tests uniquement)
    allowed_profiles: set | None = None            # profils utilisables pour la requête en cours (None = tous : appels directs/tests)

    def snapshot(self) -> dict:
        pct = lambda w: None if w is None else {t: round(100 * v, 4) for t, v in w.items()}  # noqa: E731
        return {"profile_id": self.profile_id, "weights_a_pct": pct(self.weights), "weights_b_pct": pct(self.weights_b)}


def _data_refs(result: dict) -> dict:
    prov = result.get("provenance") or {}
    files = prov.get("data_files") or {}
    refs = {"files_sha256_prefix": {n: f["sha256"][:12] for n, f in files.items()},
            "window": prov.get("window"), "price_field": prov.get("price_field"),
            "reference_currency": prov.get("reference_currency"),
            "rules_config_version": result.get("config_version") or result.get("rules_config_version")}
    if result.get("profile", {}).get("source"):
        refs["profile_source"] = result["profile"]["source"]
    return refs


def _run(tracer: Tracer, ctx: SessionContext, name: str, arguments: dict, fn) -> dict:
    t0 = time.perf_counter()
    try:
        if name in ctx.fail_tools:
            raise RuntimeError("Panne simulée de l'outil (test de robustesse).")
        result = fn()
        tracer.add(tool=name, arguments=arguments, status="ok",
                   duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                   result=result, result_digest=digest(result), data_refs=_data_refs(result))
        return result
    except Exception as e:  # noqa: BLE001 - toute erreur est enregistrée puis renvoyée au modèle comme erreur
        msg = sanitize(f"{type(e).__name__}: {e}")
        tracer.add(tool=name, arguments=arguments, status="error",
                   duration_ms=round((time.perf_counter() - t0) * 1000, 2), error=msg)
        return {"status": "error", "tool": name, "message": msg, "instruction": ERROR_INSTRUCTION}


def _profile(service: GuardianService, ctx: SessionContext, profile_id: str) -> str:
    pid = (profile_id or "").strip().lower() or ctx.profile_id
    if pid not in service.profiles:
        raise ValueError(f"Profil inconnu : {pid!r}. Profils disponibles : {sorted(service.profiles)}.")
    if ctx.allowed_profiles is not None and pid not in ctx.allowed_profiles:
        raise ValueError(f"Le profil {pid!r} n'est pas autorisé pour cette requête : l'utilisateur ne l'a pas nommé et le profil actif est "
                         f"{ctx.profile_id!r}. Demandez à l'utilisateur de sélectionner ce profil dans l'interface.")
    return pid


def _portfolio(ctx: SessionContext, portfolio: str) -> tuple[str, dict]:
    p = (portfolio or "A").strip().upper()
    if p == "A":
        return "A", ctx.weights
    if p == "B":
        if not ctx.weights_b:
            raise ValueError("Aucun portefeuille B n'est sélectionné dans l'interface.")
        return "B", ctx.weights_b
    raise ValueError("Le paramètre portfolio doit valoir 'A' ou 'B'.")


def build_tools(service: GuardianService, ctx: SessionContext, tracer: Tracer) -> list:
    @tool
    def get_profile(profile_id: str = "") -> dict:
        """Retourne le profil officiel d'un investisseur fictif et les seuils heuristiques du Guardian Check qui lui sont appliqués.

        À utiliser pour connaître l'objectif, l'horizon, la tolérance au risque et les préférences d'un persona
        (robert ou amira). Les seuils sont des heuristiques pédagogiques du prototype, pas des normes.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
        """
        args = {"profile_id": profile_id}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            thresholds = {rid: {"title": r["title"], "direction": r["direction"], **r["thresholds"][pid]}
                          for rid, r in service.rules_cfg["rules"].items() if pid in r["thresholds"]}
            return {"status": "ok", "profile_id": pid, "is_active_profile": pid == ctx.profile_id,
                    "profile": service.profiles[pid], "heuristic_thresholds": thresholds,
                    "thresholds_are_heuristics": True, "rules_config_version": service.rules_cfg["version"],
                    "available_profiles": sorted(service.profiles)}

        return _run(tracer, ctx, "get_profile", args, run)

    @tool
    def evaluate_portfolio(portfolio: str = "A", start_date: str = "", end_date: str = "") -> dict:
        """Calcule les métriques historiques d'un portefeuille fictif sélectionné dans l'interface, en dollars canadiens (CAD).

        Retourne rendement cumulé et annualisé, volatilité annualisée, drawdown maximal, concentration,
        exposition par classe d'actifs et statistiques par actif, avec la provenance des données.
        Les portefeuilles sont déjà connus du système : ne fournis aucun poids.

        Args:
            portfolio: "A" (portefeuille principal) ou "B" (portefeuille de comparaison). Par défaut "A".
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"portfolio": portfolio, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            label, w = _portfolio(ctx, portfolio)
            out = service.analyze(w, start_date or None, end_date or None).to_tool_dict()
            out["portfolio"] = label
            return out

        return _run(tracer, ctx, "evaluate_portfolio", args, run)

    @tool
    def check_profile_constraints(profile_id: str = "", portfolio: str = "A", start_date: str = "", end_date: str = "") -> dict:
        """Exécute le Guardian Check : confronte un portefeuille fictif au profil d'un investisseur.

        Retourne le profil officiel du persona, puis un constat par règle (statut OK, ATTENTION, CONFLIT ou INFO,
        valeur mesurée, seuils heuristiques, justification, méthode, limites), les limites générales
        et les informations manquantes. Un statut CONFLIT signale un conflit potentiel selon des seuils heuristiques, pas une norme.
        Les mesures financières sont identiques pour tous les profils ; seuls les seuils et les statuts changent.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
            portfolio: "A" (portefeuille principal) ou "B" (portefeuille de comparaison). Par défaut "A".
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"profile_id": profile_id, "portfolio": portfolio, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            label, w = _portfolio(ctx, portfolio)
            res, report = service.check(w, pid, start_date or None, end_date or None)
            full = res.to_tool_dict()
            out = report.to_dict()
            out.update({"profile": service.profiles[pid], "portfolio": label, "window": full["window"],
                        "weights_pct": full["weights_pct"], "metrics": full["metrics"], "concentration": full["concentration"],
                        "provenance": res.provenance})
            return out

        return _run(tracer, ctx, "check_profile_constraints", args, run)

    @tool
    def compare_scenarios(profile_id: str = "", start_date: str = "", end_date: str = "") -> dict:
        """Compare les portefeuilles fictifs A et B sélectionnés dans l'interface, sur exactement la même période et la même grille de dates.

        Retourne pour chacun : métriques historiques en CAD, concentration, expositions et constats du Guardian Check
        pour le profil demandé ; puis les écarts B moins A et des compromis historiques formulés sans désigner de gagnant.
        Nécessite qu'un portefeuille B soit sélectionné dans l'interface.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"profile_id": profile_id, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            _, wa = _portfolio(ctx, "A")
            _, wb = _portfolio(ctx, "B")
            out = service.compare(wa, wb, pid, start_date or None, end_date or None).to_tool_dict()
            out["profile"] = service.profiles[pid]          # faits officiels du persona, à citer tels quels
            return out

        return _run(tracer, ctx, "compare_scenarios", args, run)

    return [get_profile, evaluate_portfolio, check_profile_constraints, compare_scenarios]
