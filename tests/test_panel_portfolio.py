"""Grille de dates, conversion CAD, validation des poids et rééquilibrage (données synthétiques)."""
import pandas as pd
import pytest

from conftest import make_bundle
from guardian.data.loader import DataError
from guardian.finance.panel import CadPanel, build_cad_panel
from guardian.finance.portfolio import PortfolioError, simulate_portfolio, validate_weights, slice_window


# ---------------------------------------------------------------- grille et FX
def _bundle(universe, usd_prices=None, fx=None):
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    tsx = {d: 10.0 for d in dates if d != "2024-01-05"}          # TSX fermée le 5
    us = {d: (usd_prices or {}).get(d, 10.0) for d in dates if d != "2024-01-03"}   # US fermé le 3
    cry = {d: 5.0 for d in ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"]}
    fx = fx or {"2024-01-02": 1.30, "2024-01-04": 1.40, "2024-01-05": 1.50, "2024-01-08": 1.50}
    return make_bundle(universe, {"AAA.TO": tsx, "BBB": us, "CCC-USD": cry}, fx)


def test_grid_is_intersection_of_tsx_and_us_days(synthetic_universe):
    p = build_cad_panel(_bundle(synthetic_universe))
    assert [d.strftime("%Y-%m-%d") for d in p.grid] == ["2024-01-02", "2024-01-04", "2024-01-08"]
    assert not p.prices_cad.isna().any().any()
    assert "CCC-USD" in p.prices_cad.columns            # crypto lue aux dates de la grille, sans création de prix


def test_usd_conversion_constant_usd_price_gives_fx_return(synthetic_universe):
    p = build_cad_panel(_bundle(synthetic_universe))
    assert p.prices_cad.loc["2024-01-02", "BBB"] == pytest.approx(10.0 * 1.30)
    assert p.prices_cad.loc["2024-01-04", "BBB"] == pytest.approx(10.0 * 1.40)
    assert p.prices_cad["BBB"].iloc[1] / p.prices_cad["BBB"].iloc[0] - 1 == pytest.approx(1.40 / 1.30 - 1)
    assert p.prices_cad["AAA.TO"].nunique() == 1         # actif CAD : aucune conversion


def test_fx_forward_fill_only_never_backward(synthetic_universe):
    p = build_cad_panel(_bundle(synthetic_universe))
    # 2024-01-08 a un taux publié ; ajoutons un jour de grille sans taux : le dernier taux connu est reporté
    fx = {"2024-01-02": 1.30, "2024-01-04": 1.40}          # pas de taux le 8
    p2 = build_cad_panel(_bundle(synthetic_universe, fx=fx))
    assert p2.fx_used.loc["2024-01-08"] == pytest.approx(1.40)
    assert [d.strftime("%Y-%m-%d") for d in p2.fx_ffilled_dates] == ["2024-01-08"]


def test_fx_missing_on_first_grid_date_raises_instead_of_backfilling(synthetic_universe):
    with pytest.raises(DataError):
        build_cad_panel(_bundle(synthetic_universe, fx={"2024-01-04": 1.40, "2024-01-08": 1.5}))


# ---------------------------------------------------------------- poids
KNOWN = ["NVDA", "XBB.TO", "XIU.TO"]


def test_weights_valid():
    assert validate_weights({"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}, KNOWN) == {"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}


@pytest.mark.parametrize("w", [
    {"NVDA": .4, "XBB.TO": .35, "XIU.TO": .2},       # somme 95 %
    {"NVDA": .5, "XBB.TO": .6, "XIU.TO": -.1},       # négatif (vente à découvert)
    {"NVDA": .5, "ZZZ": .5},                          # actif inconnu
    {},                                               # vide
    {"NVDA": "abc", "XBB.TO": 1.0},                   # non numérique
    {"NVDA": float("nan"), "XBB.TO": 1.0},
])
def test_weights_invalid(w):
    with pytest.raises(PortfolioError):
        validate_weights(w, KNOWN)


# ---------------------------------------------------------------- rééquilibrage
def _panel(prices: dict, dates):
    df = pd.DataFrame(prices, index=pd.DatetimeIndex(dates))
    return CadPanel(prices_cad=df, fx_used=pd.Series(1.0, index=df.index), fx_ffilled_dates=(),
                    n_tsx_days=len(df), n_us_days=len(df), n_crypto_days=len(df))


DATES = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02"]
PRICES = {"A": [100, 110, 110, 121], "B": [100, 100, 100, 100]}


def test_monthly_rebalancing_known_result():
    s = simulate_portfolio(_panel(PRICES, DATES), {"A": .5, "B": .5}, rebalance="monthly")
    assert list(s.value.round(2)) == [100000.0, 105000.0, 105000.0, 110250.0]
    assert [d.strftime("%Y-%m-%d") for d in s.rebalance_dates] == ["2024-01-31"]


def test_no_rebalancing_known_result():
    s = simulate_portfolio(_panel(PRICES, DATES), {"A": .5, "B": .5}, rebalance="none")
    assert s.value.iloc[-1] == pytest.approx(110500.0)
    assert s.rebalance_dates == ()


def test_single_asset_portfolio_tracks_asset():
    s = simulate_portfolio(_panel(PRICES, DATES), {"A": 1.0})
    assert list(s.value / s.value.iloc[0]) == pytest.approx([1.0, 1.1, 1.1, 1.21])


def test_no_look_ahead_future_prices_do_not_change_past_values():
    base = simulate_portfolio(_panel(PRICES, DATES), {"A": .5, "B": .5})
    altered = {"A": [100, 110, 110, 999], "B": [100, 100, 100, 1]}
    alt = simulate_portfolio(_panel(altered, DATES), {"A": .5, "B": .5})
    assert list(base.value.iloc[:3]) == pytest.approx(list(alt.value.iloc[:3]))


def test_window_selection_and_errors():
    panel = _panel(PRICES, DATES)
    s = simulate_portfolio(panel, {"A": 1.0}, start="2024-01-31", end="2024-02-01")
    assert len(s.value) == 2 and s.value.iloc[0] == pytest.approx(100000.0)
    with pytest.raises(PortfolioError):
        slice_window(panel.grid, "2024-02-02", "2024-01-30")
    with pytest.raises(PortfolioError):
        slice_window(panel.grid, "2030-01-01", "2030-02-01")
    with pytest.raises(PortfolioError):
        simulate_portfolio(panel, {"A": 1.0}, rebalance="weekly")
