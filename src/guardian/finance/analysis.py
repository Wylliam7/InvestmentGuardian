"""Analyse complète d'un portefeuille : séries, métriques, provenance."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from guardian.data.loader import DataBundle
from guardian.finance import metrics as m
from guardian.finance.panel import CadPanel
from guardian.finance.portfolio import PortfolioSeries, simulate_portfolio

CALENDAR_POLICY = ("Grille commune : jours où tous les actifs TSX et tous les actifs américains ont un prix "
                   "(intersection). Les cryptos sont lues à ces mêmes dates ; aucun prix n'est inventé.")
FX_POLICY = ("Taux USD/CAD (Banque du Canada) : dernier taux publié à la date ou avant (report vers l'avant "
             "seulement). Conversion appliquée aux prix avant le calcul des rendements.")

ASSUMPTIONS = [
    "Prix : adj_close (ajusté des fractionnements et dividendes), converti en CAD.",
    "Portefeuille long seulement, sans levier ni vente à découvert, sans frais ni impôts.",
    "Capital initial fictif de 100 000 CAD, rééquilibrage mensuel vers les poids cibles (dernier jour de grille du mois).",
    "Rendements quotidiens simples ; volatilité annualisée avec le facteur observé (périodes par année de la grille).",
    "Rendement annualisé géométrique, présenté seulement si la fenêtre dépasse un an.",
]
LIMITATIONS = [
    "Simulation historique, pas une prévision : les performances passées ne garantissent pas les résultats futurs.",
    "Biais du survivant : l'univers a été choisi en 2026 parmi des titres aujourd'hui importants.",
    "Fenêtre unique de cinq ans ; les résultats dépendent des dates de début et de fin.",
    "Calendrier commun : les mouvements des cryptos les jours où les actions ne se négocient pas ne sont pas observés individuellement.",
    "Données Yahoo Finance non certifiées par les bourses ; adj_close est rétro-ajusté.",
]


@dataclass(frozen=True)
class AssetStats:
    ticker: str
    name: str
    asset_class: str
    currency: str
    weight: float
    annualized_vol: float
    cumulative_return: float
    max_drawdown: float


@dataclass(frozen=True)
class AnalysisResult:
    weights: dict
    series: PortfolioSeries
    asset_prices_cad: pd.DataFrame        # prix CAD des actifs du portefeuille sur la fenêtre
    n_obs: int
    factor: float
    years: float
    cumulative_return: float
    annualized_return: float | None
    volatility: float
    drawdown: m.DrawdownInfo
    concentration: m.Concentration
    class_exposure: dict
    currency_exposure: dict
    assets: tuple
    provenance: dict = field(default_factory=dict)

    @property
    def value(self) -> pd.Series:
        return self.series.value

    def to_tool_dict(self) -> dict:
        """Représentation JSON pour l'agent et la trace (valeurs en pourcentage, 2 décimales)."""
        pct = lambda x: None if x is None else round(100.0 * x, 2)  # noqa: E731
        d = self.drawdown
        return {
            "status": "ok",
            "window": {"start": str(self.series.start.date()), "end": str(self.series.end.date()),
                       "n_observations": self.n_obs, "years": round(self.years, 2)},
            "weights_pct": {t: pct(w) for t, w in self.weights.items()},
            "metrics": {
                "cumulative_return_pct": pct(self.cumulative_return),
                "annualized_return_pct": pct(self.annualized_return),
                "annualized_volatility_pct": pct(self.volatility),
                "max_drawdown_pct": pct(d.max_drawdown),
                "max_drawdown_peak_date": str(d.peak_date.date()),
                "max_drawdown_trough_date": str(d.trough_date.date()),
                "max_drawdown_recovered": d.recovered,
                "max_drawdown_underwater_days": d.underwater_days,
            },
            "concentration": {
                "largest_position": self.concentration.max_ticker,
                "largest_position_weight_pct": pct(self.concentration.max_weight),
                "top3_weight_pct": pct(self.concentration.top3_weight),
                "hhi": round(self.concentration.hhi, 4),
                "effective_number_of_positions": round(self.concentration.effective_n, 2),
            },
            "asset_class_exposure_pct": {k: pct(v) for k, v in self.class_exposure.items()},
            "currency_exposure_pct": {k: pct(v) for k, v in self.currency_exposure.items()},
            "assets": [{"ticker": a.ticker, "name": a.name, "asset_class": a.asset_class,
                        "weight_pct": pct(a.weight), "annualized_volatility_pct": pct(a.annualized_vol),
                        "cumulative_return_pct": pct(a.cumulative_return),
                        "max_drawdown_pct": pct(a.max_drawdown)} for a in self.assets],
            "provenance": self.provenance,
        }


def analyze_portfolio(bundle: DataBundle, panel: CadPanel, weights: dict, start=None, end=None,
                      rebalance: str = "monthly") -> AnalysisResult:
    series = simulate_portfolio(panel, weights, start, end, rebalance=rebalance)
    values = series.value
    idx = values.index
    factor = m.annualization_factor(idx)
    tickers = list(series.weights)
    prices = panel.prices_cad.loc[idx, tickers]

    uni = bundle.universe
    assets = tuple(
        AssetStats(ticker=t, name=str(uni.loc[t, "name"]), asset_class=str(uni.loc[t, "asset_class"]),
                   currency=str(uni.loc[t, "currency"]), weight=series.weights[t],
                   annualized_vol=m.annualized_volatility(prices[t], factor),
                   cumulative_return=m.cumulative_return(prices[t]),
                   max_drawdown=m.max_drawdown(prices[t]).max_drawdown)
        for t in tickers)

    classes = {t: str(uni.loc[t, "asset_class"]) for t in tickers}
    currencies = {t: str(uni.loc[t, "currency"]) for t in tickers}
    n_ffill_window = sum(1 for d in panel.fx_ffilled_dates if idx[0] <= d <= idx[-1])

    provenance = {
        "data_files": {n: {"sha256": bundle.sha256[n], "rows": bundle.rows[n]} for n in bundle.sha256},
        "data_dir": str(bundle.data_dir),
        "data_manifest_mismatch": list(bundle.manifest_mismatch),
        "window": {"start": str(idx[0].date()), "end": str(idx[-1].date()), "n_observations": len(idx)},
        "price_field": "adj_close",
        "reference_currency": "CAD",
        "calendar_policy": CALENDAR_POLICY,
        "calendar_days": {"grid": len(panel.grid), "tsx_days": panel.n_tsx_days, "us_days": panel.n_us_days,
                          "crypto_days_in_source": panel.n_crypto_days},
        "fx_policy": FX_POLICY,
        "fx_days_carried_forward_in_window": n_ffill_window,
        "rebalancing": "mensuel" if series.rebalance == "monthly" else "aucun (achat et conservation)",
        "n_rebalances": len(series.rebalance_dates),
        "annualization_factor": round(factor, 2),
        "assumptions": ASSUMPTIONS,
        "limitations": LIMITATIONS,
    }
    return AnalysisResult(
        weights=series.weights, series=series, asset_prices_cad=prices, n_obs=len(idx), factor=factor,
        years=m.years_between(idx), cumulative_return=m.cumulative_return(values),
        annualized_return=m.annualized_return(values), volatility=m.annualized_volatility(values, factor),
        drawdown=m.max_drawdown(values), concentration=m.concentration(series.weights),
        class_exposure=m.exposure_by(series.weights, classes),
        currency_exposure=m.exposure_by(series.weights, currencies), assets=assets, provenance=provenance)
