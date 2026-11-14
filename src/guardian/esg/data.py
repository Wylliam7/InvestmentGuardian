"""Chargement et validation des données ESG documentées (config/esg_sources.yaml). Aucune donnée n'est créée ici."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from guardian.data.loader import REPO_ROOT

ESG_PATH = REPO_ROOT / "config" / "esg_sources.yaml"
REQUIRED_SOURCE_FIELDS = ("publisher", "title", "url", "consulted_on", "nature", "scope", "limits", "terms")
DECISIONS = ("exclusion", "observation")
RELEVANCE = ("direct", "indirect")
URL_STATUSES = ("verified", "to_verify")
URL_KINDS = ("list_page", "document", "decision_page")


class EsgDataError(Exception):
    """Données ESG absentes ou incohérentes."""


@dataclass(frozen=True)
class EsgData:
    version: str
    retrieved_on: str
    sources: dict
    records: tuple                 # constats documentés par entreprise
    checked: dict = field(default_factory=dict)       # ticker -> [ids de sources où l'entreprise a été cherchée]
    fund_level: dict = field(default_factory=dict)    # ticker de FNB -> information de niveau du fonds
    not_applicable: dict = field(default_factory=dict)  # ticker -> justification

    def records_for(self, ticker: str) -> list:
        return [r for r in self.records if r["ticker"] == ticker]

    @property
    def is_empty(self) -> bool:
        return not (self.records or self.checked or self.fund_level or self.not_applicable)


def empty_esg_data() -> EsgData:
    """Aucune donnée ESG disponible : tout actif applicable sera « information insuffisante »."""
    return EsgData(version="vide", retrieved_on="", sources={}, records=(), checked={}, fund_level={}, not_applicable={})


def _date(value, label: str) -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError as e:
        raise EsgDataError(f"{label} : date invalide {value!r}") from e


def parse_esg_data(raw: dict, universe_tickers=None) -> EsgData:
    """Valide la structure : sources complètes, enregistrements rattachés à une source, tickers connus, aucun recouvrement incohérent."""
    sources = raw.get("sources") or {}
    for sid, s in sources.items():
        missing = [k for k in REQUIRED_SOURCE_FIELDS if not s.get(k)]
        if missing:
            raise EsgDataError(f"Source {sid!r} : champs manquants {missing} (provenance incomplète)")
        _date(s["consulted_on"], f"Source {sid!r}")
        if not str(s["url"]).startswith("http"):
            raise EsgDataError(f"Source {sid!r} : URL invalide")
        if s.get("url_status", "to_verify") not in URL_STATUSES or s.get("url_kind", "list_page") not in URL_KINDS:
            raise EsgDataError(f"Source {sid!r} : url_status ou url_kind invalide")
        if s.get("url_status") == "verified":
            _date(s.get("url_verified_on"), f"Source {sid!r} (url_verified_on obligatoire pour une URL vérifiée)")
    known = set(universe_tickers) if universe_tickers is not None else None

    def check_ticker(t: str, where: str) -> None:
        if known is not None and t not in known:
            raise EsgDataError(f"{where} : actif {t!r} absent de l'univers officiel")

    records = []
    for r in raw.get("records") or []:
        for k in ("ticker", "source", "company_name_in_source", "criterion_fr", "decision", "published", "dimension", "relevance"):
            if not r.get(k):
                raise EsgDataError(f"Enregistrement {r.get('ticker')!r} : champ {k!r} manquant")
        if r["source"] not in sources:
            raise EsgDataError(f"Enregistrement {r['ticker']!r} : source inconnue {r['source']!r}")
        if r["decision"] not in DECISIONS or r["relevance"] not in RELEVANCE:
            raise EsgDataError(f"Enregistrement {r['ticker']!r} : décision ou pertinence invalide")
        if r.get("decision_url"):
            if not str(r["decision_url"]).startswith("http") or not r.get("decision_url_verified_on"):
                raise EsgDataError(f"Enregistrement {r['ticker']!r} : decision_url exige une URL http(s) et decision_url_verified_on")
            _date(r["decision_url_verified_on"], f"Enregistrement {r['ticker']!r}")
        check_ticker(r["ticker"], "Enregistrement")
        records.append({**r, "published": _date(r["published"], f"Enregistrement {r['ticker']!r}")})

    checked: dict = {}
    for c in raw.get("checks") or []:
        if c["source"] not in sources:
            raise EsgDataError(f"Vérification : source inconnue {c['source']!r}")
        _date(c["checked_on"], "Vérification")
        for t in c["checked_tickers"]:
            check_ticker(t, "Vérification")
            checked.setdefault(t, []).append(c["source"])
    rec_tickers = {r["ticker"] for r in records}
    not_checked = rec_tickers - set(checked)
    if not_checked:
        raise EsgDataError(f"Enregistrements sans vérification correspondante : {sorted(not_checked)}")

    fund_level = {}
    for f in raw.get("fund_level") or []:
        if f["source"] not in sources:
            raise EsgDataError(f"Information de fonds : source inconnue {f['source']!r}")
        check_ticker(f["ticker"], "Information de fonds")
        fund_level[f["ticker"]] = f
    na = dict(raw.get("not_applicable") or {})
    for t, why in na.items():
        check_ticker(t, "Non applicable")
        if not str(why).strip():
            raise EsgDataError(f"Non applicable {t!r} : justification obligatoire")
    overlap = set(na) & (set(checked) | rec_tickers)
    if overlap:
        raise EsgDataError(f"Actifs à la fois « non applicables » et vérifiés : {sorted(overlap)}")
    return EsgData(version=str(raw.get("version", "?")), retrieved_on=str(raw.get("retrieved_on", "")), sources=sources,
                   records=tuple(records), checked=checked, fund_level=fund_level, not_applicable=na)


def load_esg_data(path: Path | None = None, universe_tickers=None) -> EsgData:
    p = path or ESG_PATH
    if not p.exists():
        return empty_esg_data()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        raise EsgDataError(f"Lecture de {p.name} impossible : {e}") from e
    return parse_esg_data(raw, universe_tickers)
