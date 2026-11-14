"""Outils Strands exposés à l'agent (V0 : deux outils financiers réels).

Le portefeuille courant et le profil actif viennent du contexte de session (côté serveur) : le modèle
ne retranscrit jamais de poids. Chaque appel est enregistré dans le Tracer, succès ou échec.
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
    weights: dict                      # poids cibles (fractions)
    profile_id: str
    fail_tools: set = field(default_factory=set)   # injection de pannes (tests uniquement)


def _data_refs(result: dict) -> dict:
    prov = result.get("provenance") or {}
    files = prov.get("data_files") or {}
    return {"files_sha256_prefix": {n: f["sha256"][:12] for n, f in files.items()},
            "window": prov.get("window"), "price_field": prov.get("price_field"),
            "reference_currency": prov.get("reference_currency"),
            "rules_config_version": result.get("config_version")}


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


def build_tools(service: GuardianService, ctx: SessionContext, tracer: Tracer) -> list:
    @tool
    def evaluate_portfolio(start_date: str = "", end_date: str = "") -> dict:
        """Calcule les métriques historiques du portefeuille fictif courant, en dollars canadiens (CAD).

        Retourne rendement cumulé et annualisé, volatilité annualisée, drawdown maximal, concentration,
        exposition par classe d'actifs et statistiques par actif, avec la provenance des données.
        Le portefeuille est déjà connu du système : ne fournis aucun poids.

        Args:
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"start_date": start_date, "end_date": end_date}
        return _run(tracer, ctx, "evaluate_portfolio", args,
                    lambda: service.analyze(ctx.weights, start_date or None, end_date or None).to_tool_dict())

    @tool
    def check_profile_constraints(profile_id: str = "robert", start_date: str = "", end_date: str = "") -> dict:
        """Exécute le Guardian Check : confronte le portefeuille fictif courant au profil de l'investisseur.

        Retourne le profil officiel du persona, puis un constat par règle (statut OK, ATTENTION ou CONFLIT,
        valeur mesurée, seuils heuristiques, justification, méthode, limites), les limites générales
        et les informations manquantes. Les seuils sont des heuristiques, pas des normes.

        Args:
            profile_id: Identifiant du profil. Seul "robert" est disponible dans cette version.
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"profile_id": profile_id, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            res, report = service.check(ctx.weights, profile_id, start_date or None, end_date or None)
            out = report.to_dict()
            out["profile"] = service.profiles[profile_id]
            out["window"] = res.to_tool_dict()["window"]
            out["weights_pct"] = res.to_tool_dict()["weights_pct"]
            out["provenance"] = res.provenance
            return out

        return _run(tracer, ctx, "check_profile_constraints", args, run)

    return [evaluate_portfolio, check_profile_constraints]
