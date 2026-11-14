"""Validation des poids et simulation de la valeur d'un portefeuille fictif.

Hypothèses (DECISIONS.md F-06, F-18) : long seulement, sans levier, sans frais ni impôts,
capital initial fictif, rééquilibrage mensuel vers les poids cibles au dernier jour de grille du mois.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from guardian.finance.panel import CadPanel

INITIAL_VALUE = 100_000.0
WEIGHT_TOLERANCE = 1e-4


class PortfolioError(ValueError):
    """Portefeuille invalide (poids, actifs ou fenêtre)."""


def validate_weights(weights: dict, known_tickers, tol: float = WEIGHT_TOLERANCE) -> dict:
    """Retourne des poids (fractions) validés : actifs connus, >= 0, somme = 1."""
    if not isinstance(weights, dict) or not weights:
        raise PortfolioError("Le portefeuille est vide.")
    known = set(known_tickers)
    unknown = sorted(t for t in weights if t not in known)
    if unknown:
        raise PortfolioError(f"Actifs absents des données : {unknown}")
    clean = {}
    for t, w in weights.items():
        try:
            w = float(w)
        except (TypeError, ValueError) as e:
            raise PortfolioError(f"Poids non numérique pour {t}") from e
        if not np.isfinite(w):
            raise PortfolioError(f"Poids non valide pour {t}")
        if w < 0:
            raise PortfolioError(f"Poids négatif pour {t} : la vente à découvert n'est pas permise.")
        clean[t] = w
    total = sum(clean.values())
    if abs(total - 1.0) > tol:
        raise PortfolioError(f"Les poids totalisent {total * 100:.2f} % au lieu de 100 %.")
    return {t: w for t, w in clean.items() if w > 0}


def weights_from_percent(weights_pct: dict) -> dict:
    return {t: float(w) / 100.0 for t, w in weights_pct.items()}


@dataclass(frozen=True)
class PortfolioSeries:
    value: pd.Series                 # valeur du portefeuille (CAD fictifs)
    weights: dict                    # poids cibles (fractions)
    rebalance: str
    rebalance_dates: tuple
    start: pd.Timestamp
    end: pd.Timestamp


def slice_window(grid: pd.DatetimeIndex, start=None, end=None) -> pd.DatetimeIndex:
    """Fenêtre dans la grille : première date >= start, dernière date <= end."""
    s = pd.Timestamp(start) if start else grid[0]
    e = pd.Timestamp(end) if end else grid[-1]
    if s > e:
        raise PortfolioError("La date de début est postérieure à la date de fin.")
    if e < grid[0] or s > grid[-1]:
        raise PortfolioError(f"Fenêtre hors des données ({grid[0].date()} à {grid[-1].date()}).")
    idx = grid[(grid >= s) & (grid <= e)]
    if len(idx) < 2:
        raise PortfolioError("Fenêtre trop courte : au moins deux dates sont nécessaires.")
    return idx


def simulate_portfolio(panel: CadPanel, weights: dict, start=None, end=None,
                       initial_value: float = INITIAL_VALUE, rebalance: str = "monthly") -> PortfolioSeries:
    if rebalance not in ("monthly", "none"):
        raise PortfolioError("rebalance doit valoir 'monthly' ou 'none'.")
    w = validate_weights(weights, panel.prices_cad.columns)
    idx = slice_window(panel.grid, start, end)
    tickers = list(w)
    prices = panel.prices_cad.loc[idx, tickers].to_numpy(dtype=float)
    target = np.array([w[t] for t in tickers])
    months = idx.to_period("M")

    shares = initial_value * target / prices[0]
    values = np.empty(len(idx))
    rebal = []
    for i in range(len(idx)):
        values[i] = float(shares @ prices[i])
        month_end = i < len(idx) - 1 and months[i + 1] != months[i]
        if rebalance == "monthly" and month_end:
            shares = values[i] * target / prices[i]     # information disponible à la date i seulement
            rebal.append(idx[i])
    return PortfolioSeries(value=pd.Series(values, index=idx, name="valeur_portefeuille_cad"),
                           weights=w, rebalance=rebalance, rebalance_dates=tuple(rebal),
                           start=idx[0], end=idx[-1])
