"""Formulation pédagogique sur les FNB (fonds négociés en bourse). N'altère AUCUN poids, indice HHI, seuil ni statut : texte et indicateurs de contexte seulement.

La règle R1 applique le même repère à une action et à un FNB. Ce module rappelle qu'une position de X % dans un FNB diversifié n'est pas équivalente
à une position de X % dans une entreprise individuelle, et que la diversification sous-jacente des FNB n'est PAS mesurée par le prototype.
"""
from __future__ import annotations

from guardian.explain.format import pct_value

FUND_CLASSES = ("etf_equity", "etf_bond")     # fonds de plusieurs titres ; GLD (or) et cryptoactifs sont traités ailleurs

NOT_MEASURED = "La diversification sous-jacente des FNB n'est pas mesurée ici."
EFFECTIVE_N_NOTE = ("Le nombre effectif de positions mesure la concentration des poids entre les lignes du portefeuille, "
                    "pas le nombre d'entreprises sous-jacentes.")
GENERIC_NOTE = ("Une position de {w} dans un FNB diversifié n'est pas équivalente à une position de {w} dans une entreprise individuelle : "
                "un FNB détient plusieurs entreprises ou titres. " + NOT_MEASURED + " Le repère s'applique pourtant de la même façon à une action et à un FNB, "
                "ce qui peut surestimer la concentration réelle. Certains FNB sont eux-mêmes concentrés (par exemple sur un secteur) : la composition "
                "sous-jacente reste à vérifier auprès de l'émetteur. " + EFFECTIVE_N_NOTE)
SHORT_NOTE = ("Un FNB détient plusieurs titres : sa part n'est pas équivalente à celle d'une entreprise individuelle. " + NOT_MEASURED + " " + EFFECTIVE_N_NOTE)


def fund_exposure(weights: dict, universe, max_ticker: str, max_weight: float) -> dict:
    """Contexte FNB d'un portefeuille. `weights` : fractions ; `max_weight` : poids (fraction) de la plus grande position."""
    lines = []
    for t, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        ac = str(universe.loc[t, "asset_class"])
        if ac in FUND_CLASSES:
            lines.append({"ticker": t, "name": str(universe.loc[t, "name"]), "weight_pct": round(100 * w, 2), "asset_class": ac})
    top_is_fund = any(x["ticker"] == max_ticker for x in lines)
    total = round(sum(x["weight_pct"] for x in lines), 2)
    wtxt = pct_value(100 * max_weight)
    out = {
        "has_funds": bool(lines), "fund_lines": lines, "fund_weight_pct": total,
        "largest_position_is_fund": top_is_fund, "largest_position_ticker": max_ticker,
        "underlying_diversification_measured": False,
        "limitation": NOT_MEASURED,
        "pedagogical_note": (GENERIC_NOTE.format(w=wtxt) if top_is_fund else SHORT_NOTE) if lines else
                            "Aucun FNB dans ce portefeuille : chaque position est une action individuelle ou un actif unique.",
    }
    return out


def fund_share(weights: dict, universe) -> float:
    """Part (fraction) du portefeuille détenue via des FNB d'actions ou d'obligations (métadonnée réelle `asset_class`)."""
    return sum(w for t, w in weights.items() if str(universe.loc[t, "asset_class"]) in FUND_CLASSES)
