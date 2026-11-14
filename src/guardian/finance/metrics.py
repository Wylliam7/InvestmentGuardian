"""Métriques de rendement, de risque et de concentration (fonctions pures, testables)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DAYS_PER_YEAR = 365.25


def years_between(index: pd.DatetimeIndex) -> float:
    return (index[-1] - index[0]).days / DAYS_PER_YEAR


def annualization_factor(index: pd.DatetimeIndex) -> float:
    """Nombre observé de périodes de rendement par année : (n - 1) / années."""
    if len(index) < 2:
        raise ValueError("Au moins deux dates sont nécessaires.")
    return (len(index) - 1) / years_between(index)


def simple_returns(values: pd.Series) -> pd.Series:
    return values.pct_change().dropna()


def cumulative_return(values: pd.Series) -> float:
    return float(values.iloc[-1] / values.iloc[0] - 1.0)


def annualized_return(values: pd.Series, min_years: float = 1.0):
    """Rendement annualisé géométrique ; None si la fenêtre est plus courte que min_years."""
    years = years_between(values.index)
    if years < min_years:
        return None
    return float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0)


def annualized_volatility(values: pd.Series, factor: float | None = None) -> float:
    r = simple_returns(values)
    if len(r) < 2:
        raise ValueError("Pas assez de rendements pour estimer la volatilité.")
    f = annualization_factor(values.index) if factor is None else factor
    return float(r.std(ddof=1) * np.sqrt(f))


@dataclass(frozen=True)
class DrawdownInfo:
    max_drawdown: float             # valeur négative, ex. -0.5
    peak_date: pd.Timestamp
    trough_date: pd.Timestamp
    recovery_date: pd.Timestamp | None
    underwater_days: int            # jours calendaires du sommet à la récupération (ou à la fin)
    recovered: bool


def max_drawdown(values: pd.Series) -> DrawdownInfo:
    running_max = values.cummax()
    dd = values / running_max - 1.0
    trough = dd.idxmin()
    peak = values.loc[:trough].idxmax()
    peak_value = values.loc[peak]
    after = values.loc[trough:]
    rec = after[after >= peak_value]
    recovery = rec.index[0] if len(rec) else None
    end = recovery if recovery is not None else values.index[-1]
    return DrawdownInfo(max_drawdown=float(dd.min()), peak_date=peak, trough_date=trough,
                        recovery_date=recovery, underwater_days=int((end - peak).days),
                        recovered=recovery is not None)


def drawdown_series(values: pd.Series) -> pd.Series:
    return values / values.cummax() - 1.0


@dataclass(frozen=True)
class Concentration:
    max_weight: float
    max_ticker: str
    top3_weight: float
    hhi: float
    effective_n: float


def concentration(weights: dict) -> Concentration:
    items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    w = np.array([v for _, v in items], dtype=float)
    hhi = float((w ** 2).sum())
    return Concentration(max_weight=float(w[0]), max_ticker=items[0][0],
                         top3_weight=float(w[:3].sum()), hhi=hhi, effective_n=1.0 / hhi)


def exposure_by(weights: dict, labels: dict) -> dict:
    """Somme des poids par étiquette (classe d'actifs, devise...)."""
    out: dict = {}
    for t, w in weights.items():
        out[labels[t]] = out.get(labels[t], 0.0) + w
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))
