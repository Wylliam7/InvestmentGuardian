"""Grille de dates commune et conversion en CAD.

Politique (DECISIONS.md F-02 à F-04) :
- prix = adj_close ;
- grille = jours où TOUS les actifs TSX et TOUS les actifs américains ont un prix (intersection) ;
- les cryptos sont lues à ces mêmes dates (aucun prix inventé) ;
- taux USD/CAD = dernier taux publié à la date ou avant (report vers l'avant seulement) ;
- conversion avant tout calcul de rendement.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from guardian.data.loader import DataBundle, DataError


@dataclass(frozen=True)
class CadPanel:
    prices_cad: pd.DataFrame       # index = grille, colonnes = tickers, valeurs en CAD
    fx_used: pd.Series             # USD/CAD appliqué à chaque date de la grille
    fx_ffilled_dates: tuple        # dates de grille sans taux publié (taux reporté)
    n_tsx_days: int
    n_us_days: int
    n_crypto_days: int             # jours crypto disponibles dans la source (toutes dates)

    @property
    def grid(self) -> pd.DatetimeIndex:
        return self.prices_cad.index


def _group(universe: pd.DataFrame, ticker: str) -> str:
    row = universe.loc[ticker]
    if row["asset_class"] == "crypto":
        return "crypto"
    return "tsx" if row["market"] == "TSX" else "us"


def build_cad_panel(bundle: DataBundle) -> CadPanel:
    wide = bundle.prices.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    groups = {t: _group(bundle.universe, t) for t in wide.columns}
    tsx = [t for t, g in groups.items() if g == "tsx"]
    us = [t for t, g in groups.items() if g == "us"]
    crypto = [t for t, g in groups.items() if g == "crypto"]
    if not tsx or not us:
        raise DataError("Univers incomplet : il faut au moins un actif TSX et un actif américain")

    tsx_days = wide.index[wide[tsx].notna().all(axis=1)]
    us_days = wide.index[wide[us].notna().all(axis=1)]
    grid = tsx_days.intersection(us_days).sort_values()
    if len(grid) < 2:
        raise DataError("Grille de dates commune vide")

    panel = wide.loc[grid].copy()
    if panel.isna().any().any():
        bad = panel.columns[panel.isna().any()].tolist()
        raise DataError(f"Prix manquants sur la grille commune pour {bad} (aucun remplissage n'est appliqué)")

    fx = bundle.fx
    if grid[0] < fx.index[0]:
        raise DataError("Aucun taux USD/CAD publié à la première date de la grille (pas de report vers l'arrière)")
    fx_full = fx.reindex(fx.index.union(grid)).sort_index().ffill()  # report vers l'avant seulement
    fx_used = fx_full.loc[grid]
    ffilled = tuple(d for d in grid if d not in fx.index)

    usd = [t for t in panel.columns if bundle.universe.loc[t, "currency"] == "USD"]
    panel[usd] = panel[usd].mul(fx_used, axis=0)

    n_crypto = int(wide[crypto].notna().all(axis=1).sum()) if crypto else 0
    return CadPanel(prices_cad=panel, fx_used=fx_used, fx_ffilled_dates=ffilled,
                    n_tsx_days=len(tsx_days), n_us_days=len(us_days), n_crypto_days=n_crypto)
