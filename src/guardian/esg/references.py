"""Références cliquables des constats ESG, construites UNIQUEMENT à partir des données enregistrées (config/esg_sources.yaml).

Règles :
- un lien « décision » n'existe que si l'enregistrement porte une `decision_url` vérifiée ;
- sinon, si la source a une URL vérifiée, on renvoie vers cette page (liste ou document) en disant qu'elle n'est PAS la page de la décision ;
- sinon (URL absente, invalide ou non vérifiée) : « Référence à vérifier », aucun lien. Aucune URL n'est jamais déduite ni construite.
"""
from __future__ import annotations

TO_VERIFY = "Référence à vérifier"
LINK_LABEL = "Consulter la source officielle"
KIND_NOTES = {
    "list_page": "Ce lien mène à la page de liste de la source, pas à une page dédiée à cette décision : repérez l'entreprise dans la liste.",
    "document": "Ce lien mène à un document de la source (niveau du fonds), pas à une vérification des positions détenues.",
    "decision_page": "Ce lien mène à la page de cette décision.",
}


def _is_url(u) -> bool:
    return isinstance(u, str) and u.startswith(("http://", "https://")) and " " not in u


def source_label(source: dict) -> str:
    return str(source.get("short_name") or source.get("title") or source.get("id") or "Source inconnue")


def build_reference(source: dict | None, record: dict | None = None) -> dict:
    """`source` : entrée de source (clés id, short_name/title, url, url_status, url_kind, consulted_on). `record` : constat documenté ou None."""
    source = source or {}
    rec_url = (record or {}).get("decision_url")
    if record and _is_url(rec_url) and record.get("decision_url_verified_on"):
        url, kind, status = rec_url, "decision_page", "verified"
    elif _is_url(source.get("url")) and source.get("url_status") == "verified":
        url, kind, status = source["url"], source.get("url_kind") or "list_page", "verified"
    else:
        url, kind, status = None, None, "to_verify"
    ref = {"source_id": source.get("id"), "source_name": source_label(source), "consulted_on": source.get("consulted_on"),
           "url": url, "url_kind": kind, "url_status": status,
           "link_label": LINK_LABEL if url else TO_VERIFY, "link_note": KIND_NOTES.get(kind) if url else
           "Aucune adresse vérifiée n'est enregistrée pour cette référence : consultez la source à partir de son nom et de sa date de consultation."}
    if record:
        ref.update({"ticker": record.get("ticker"), "company_name_in_source": record.get("company_name_in_source"), "decision": record.get("decision"),
                    "published": record.get("published"), "criterion_fr": record.get("criterion_fr")})
    return ref
