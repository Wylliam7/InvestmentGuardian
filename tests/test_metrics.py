"""Calculs vérifiés sur des données synthétiques dont le résultat est connu."""
import math

import numpy as np
import pandas as pd
import pytest

from guardian.finance import metrics as m


def series(values, start="2024-01-01", freq="D"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def test_cumulative_return_compound_one_percent_per_day():
    v = series([100 * 1.01 ** i for i in range(11)])
    assert m.cumulative_return(v) == pytest.approx(1.01 ** 10 - 1)


def test_constant_series_has_zero_return_and_volatility():
    v = series([100.0] * 10)
    assert m.cumulative_return(v) == 0.0
    assert m.annualized_volatility(v, factor=252) == 0.0


def test_volatility_alternating_returns_known_value():
    v = series([100, 101, 101 * 0.99, 101 * 0.99 * 1.01, 101 * 0.99 * 1.01 * 0.99])
    expected = math.sqrt(4 * 0.01 ** 2 / 3) * math.sqrt(252)   # écart-type échantillon de [+1 %, -1 %, +1 %, -1 %]
    assert m.annualized_volatility(v, factor=252) == pytest.approx(expected, rel=1e-9)


def test_max_drawdown_known_unrecovered():
    v = series([100, 120, 60, 90])
    dd = m.max_drawdown(v)
    assert dd.max_drawdown == pytest.approx(-0.5)
    assert dd.peak_date == v.index[1] and dd.trough_date == v.index[2]
    assert not dd.recovered and dd.recovery_date is None
    assert dd.underwater_days == 2          # du sommet (jour 1) à la fin (jour 3)


def test_max_drawdown_recovered():
    v = series([100, 120, 60, 130])
    dd = m.max_drawdown(v)
    assert dd.max_drawdown == pytest.approx(-0.5)
    assert dd.recovered and dd.recovery_date == v.index[3]
    assert dd.underwater_days == 2


def test_max_drawdown_monotonic_rise_is_zero():
    assert m.max_drawdown(series([100, 101, 102, 103])).max_drawdown == 0.0


def test_annualized_return_exact_four_years():
    idx = pd.DatetimeIndex(["2020-01-01", "2024-01-01"])   # 1461 jours = 4,0 ans
    v = pd.Series([100.0, 160.0], index=idx)
    assert m.years_between(idx) == pytest.approx(4.0)
    assert m.annualized_return(v) == pytest.approx(1.6 ** 0.25 - 1)


def test_annualized_return_not_shown_for_less_than_one_year():
    v = series([100, 110, 120])
    assert m.annualized_return(v) is None


def test_annualization_factor_is_observed_periods_per_year():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-07-01", "2021-01-01", "2024-01-01"])
    assert m.annualization_factor(idx) == pytest.approx(3 / m.years_between(idx))


def test_concentration_equal_weights():
    c = m.concentration({"A": .25, "B": .25, "C": .25, "D": .25})
    assert c.hhi == pytest.approx(0.25) and c.effective_n == pytest.approx(4.0)
    assert c.max_weight == pytest.approx(.25) and c.top3_weight == pytest.approx(.75)


def test_concentration_scenario_values():
    c = m.concentration({"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25})
    assert c.max_ticker == "NVDA"
    assert c.hhi == pytest.approx(0.16 + 0.1225 + 0.0625)
    assert c.effective_n == pytest.approx(1 / 0.345)
    assert c.top3_weight == pytest.approx(1.0)


def test_exposure_by_sums_labels():
    out = m.exposure_by({"A": .4, "B": .35, "C": .25}, {"A": "equity", "B": "bond", "C": "equity"})
    assert out == {"equity": pytest.approx(.65), "bond": pytest.approx(.35)}


def test_drawdown_series_matches_max():
    v = series([100, 120, 60, 90])
    assert m.drawdown_series(v).min() == pytest.approx(m.max_drawdown(v).max_drawdown)
    assert np.isclose(m.drawdown_series(v).iloc[0], 0.0)
