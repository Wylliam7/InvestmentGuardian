"""Niveau 1 de l'explicabilité : ce que l'assistant a RÉELLEMENT fait, d'après le journal des outils (jamais d'après le texte du modèle).

Aucune phrase n'est produite pour un outil qui n'a pas été exécuté.
"""
from __future__ import annotations

from dataclasses import dataclass

DATA_SOURCES = ("Prix quotidiens ajustés (Yahoo Finance, jeu de départ du Datathon) et taux de change USD/CAD (Banque du Canada), "
                "convertis en dollars canadiens ; données figées par empreinte numérique.")
IA_DISCLAIMER = ("Le texte rédigé par l'IA est une interprétation : il n'est pas vérifié phrase par phrase. "
                 "Les chiffres, repères et statuts affichés par l'application viennent du moteur Python.")
TOOLS_DISCLAIMER = "Les outils financiers ont été exécutés par le code Python de l'application, pas par le modèle."


@dataclass(frozen=True)
class CallLine:
    record_id: int
    tool: str
    ok: bool
    text: str
    duration_ms: float


def _profile_name(rec, profiles: dict) -> str | None:
    pid = (rec.arguments.get("profile_id") or "").strip().lower()
    if rec.result and rec.result.get("profile_id"):
        pid = rec.result["profile_id"]
    if pid in profiles:
        return profiles[pid]["display_name"]
    return pid or None


def describe_calls(records, profiles: dict, active_profile: str | None = None) -> list[CallLine]:
    """Une phrase par appel RÉELLEMENT exécuté, dans l'ordre d'exécution."""
    lines = []
    for r in sorted(records, key=lambda x: x.id):
        port = (r.arguments.get("portfolio") or "A").upper()
        who = _profile_name(r, profiles) or (profiles[active_profile]["display_name"] if active_profile in profiles else "le profil actif")
        if r.tool == "get_profile":
            ok_text = f"A consulté le profil officiel de {who}."
        elif r.tool == "evaluate_portfolio":
            ok_text = f"A analysé votre portefeuille {port} (rendement, fluctuations, baisses, répartition)."
        elif r.tool == "check_profile_constraints":
            ok_text = f"A comparé les risques du portefeuille {port} avec le profil de {who} (Guardian Check)."
        elif r.tool == "compare_scenarios":
            ok_text = f"A comparé les deux allocations A et B sur la même période pour {who}."
        else:
            ok_text = f"A exécuté l'outil « {r.tool} »."
        text = ok_text if r.status == "ok" else f"Tentative échouée : {ok_text[0].lower() + ok_text[1:]} Erreur : {r.error}"
        lines.append(CallLine(r.id, r.tool, r.status == "ok", text, r.duration_ms))
    return lines


def data_facts(records) -> dict:
    """Période, devise et provenance, relevées dans les résultats réellement retournés par les outils."""
    window, currency, files = None, None, {}
    for r in records:
        if r.status != "ok" or not r.data_refs:
            continue
        refs = r.data_refs
        window = window or refs.get("window")
        currency = currency or refs.get("reference_currency")
        files.update(refs.get("files_sha256_prefix") or {})
    return {"window": window, "currency": currency, "files": files}


def summary_lines(records, profiles: dict, active_profile: str | None = None) -> dict:
    calls = describe_calls(records, profiles, active_profile)
    facts = data_facts(records)
    ok = [c for c in calls if c.ok]
    notes = []
    if facts["window"]:
        notes.append(f"Période historique : du {facts['window']['start']} au {facts['window']['end']} ({facts['window']['n_observations']} dates communes).")
    if facts["currency"]:
        notes.append(f"Devise : dollar canadien ({facts['currency']}).")
    if facts["files"]:
        notes.append("Données : " + DATA_SOURCES)
    return {"calls": calls, "n_ok": len(ok), "n_failed": len(calls) - len(ok), "notes": notes,
            "disclaimers": [TOOLS_DISCLAIMER if ok else "Aucun outil financier n'a été exécuté avec succès pour cette requête.", IA_DISCLAIMER]}
