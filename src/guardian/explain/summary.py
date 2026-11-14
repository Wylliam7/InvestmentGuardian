"""Résumé des risques prioritaires : déterministe, fidèle aux constats, sans appel à l'IA.

Les règles corrélées sont regroupées en thèmes pour ne pas présenter cinq risques indépendants :
- concentration : R1 (poids de la plus grande position) et R7 (nombre effectif de positions) ;
- actifs très fluctuants : R2 ;
- fluctuations et baisses historiques : R4 (volatilité) et R5 (baisse maximale).
Au plus trois thèmes ; seuls ceux qui franchissent un repère sont affichés.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guardian.explain.format import asset_label, fr, pct, pct_value
from guardian.rules.engine import ATTENTION, CONFLIT, GuardianReport

THEMES = (("concentration", ("R1", "R7")), ("actifs_fluctuants", ("R2",)), ("fluctuations_baisses", ("R4", "R5")))
SEVERITY = {CONFLIT: 2, ATTENTION: 1}
COUNT_WORDS = {1: "un élément mérite", 2: "deux éléments méritent", 3: "trois éléments méritent"}


@dataclass(frozen=True)
class SummaryItem:
    theme: str
    rules: tuple            # règles qui ont réellement franchi un repère dans ce thème
    severity: int           # 2 = risque important à examiner, 1 = point de vigilance
    text: str


@dataclass(frozen=True)
class PrioritySummary:
    profile_name: str
    items: tuple
    sentence: str
    intro: str
    related_note: str | None
    n_flagged_rules: int

    @property
    def n_items(self) -> int:
        return len(self.items)


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " et " + parts[-1]


def build_priority_summary(result, report: GuardianReport, profile: dict, universe) -> PrioritySummary:
    name = profile["display_name"]
    f = report.by_id()
    flagged = {rid for rid, g in f.items() if g.status in SEVERITY}
    top = result.concentration.max_ticker
    top_label = asset_label(universe, top)
    items: list[SummaryItem] = []

    for theme, rules in THEMES:
        hit = tuple(r for r in rules if r in flagged)
        if not hit:
            continue
        sev = max(SEVERITY[f[r].status] for r in hit)
        if theme == "concentration":
            parts = []
            if "R1" in hit:
                parts.append(f"la concentration dans {top_label} ({pct_value(100 * result.concentration.max_weight)} du portefeuille)")
            if "R7" in hit:
                parts.append(f"la répartition entre peu de positions (diversification équivalente à {fr(result.concentration.effective_n)} positions de poids égal)")
            text = _join(parts)
        elif theme == "actifs_fluctuants":
            text = f"la part d'actifs très fluctuants ({pct_value(100 * f['R2'].measured)} du portefeuille)"
        else:
            parts = []
            if "R4" in hit:
                parts.append(f"les fluctuations historiques (environ {pct(f['R4'].measured)} par an)")
            if "R5" in hit:
                parts.append(f"l'ampleur des baisses passées (jusqu'à −{fr(100 * f['R5'].measured)} %)")
            text = _join(parts)
        items.append(SummaryItem(theme, hit, sev, text))

    items.sort(key=lambda i: -i.severity)             # tri stable : à gravité égale, l'ordre des thèmes est conservé
    items = items[:3]
    n = len(items)
    if n == 0:
        intro = ""
        sentence = (f"Pour {name}, aucun repère de vigilance n'est dépassé selon nos critères pédagogiques. "
                    "Cela ne signifie pas que le portefeuille est sans risque : lisez aussi les limites de l'analyse.")
    else:
        intro = f"Pour {name}, {COUNT_WORDS[n]} particulièrement votre attention :"
        sentence = intro + " " + " ; ".join(i.text for i in items) + "."

    note = None
    vol_tickers = {a["ticker"] for a in f["R2"].evidence["volatile_assets"]}
    if "R1" in flagged and top in vol_tickers:
        influenced = [lbl for lbl, ok in (("la part d'actifs très fluctuants", "R2" in flagged), ("les fluctuations historiques", "R4" in flagged),
                                          ("l'ampleur des baisses passées", "R5" in flagged)) if ok]
        if influenced:
            note = (f"Ces éléments se recoupent : {top_label} pèse lourd et fait partie des actifs très fluctuants, ce qui peut aussi contribuer à "
                    f"{_join(influenced)}. Il ne s'agit donc pas de risques entièrement indépendants.")
    return PrioritySummary(profile_name=name, items=tuple(items), sentence=sentence, intro=intro, related_note=note, n_flagged_rules=len(flagged))
