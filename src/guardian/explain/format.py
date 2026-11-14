"""Formats français (virgule décimale) et libellés partagés."""
from __future__ import annotations


def fr(x: float, digits: int = 1) -> str:
    """Nombre avec virgule décimale : 2,9."""
    return f"{x:.{digits}f}".replace(".", ",")


def pct(x: float | None, digits: int = 1) -> str:
    """Fraction → pourcentage français : 0.2228 → '22,3 %'. None → 'n.d.'."""
    return "n.d." if x is None else f"{fr(100 * x, digits)} %"


def pct_value(v: float, digits: int = 1) -> str:
    """Pourcentage déjà exprimé en % (40.0 → '40 %', 33.3 → '33,3 %')."""
    return f"{int(round(v))} %" if abs(v - round(v)) < 0.05 else f"{fr(v, digits)} %"


def horizon_text(profile: dict) -> str:
    lo, hi = profile["horizon_years_min"], profile.get("horizon_years_max")
    return f"{lo} à {hi} ans" if hi else f"{lo} ans ou plus"


def asset_label(universe, ticker: str) -> str:
    """Nom lisible d'un actif (nom du jeu de données, ou symbole si le nom est trop long)."""
    try:
        name = str(universe.loc[ticker, "name"])
    except KeyError:
        return ticker
    name = name.replace(" (Class A)", "")
    return name if len(name) <= 28 else ticker


def persona_sentence(profile: dict) -> str:
    """Rappel du profil, avec l'objectif officiel cité tel quel (jamais reformulé)."""
    return (f"{profile['display_name']} a pour objectif : « {profile['objective']} » avec un horizon de {horizon_text(profile)} "
            f"et un niveau de risque {profile['risk_profile_label'].lower()}.")


MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")


def fr_date(ts) -> str:
    """29 novembre 2021 (le 1er du mois : « 1er »)."""
    d = ts.date() if hasattr(ts, "date") else ts
    return f"{'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]} {d.year}"
