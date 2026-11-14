"""Contrôles sur les données officielles réelles, avec un recalcul indépendant (module csv + numpy)."""
import csv
import hashlib
import shutil

import numpy as np
import pytest
import yaml

from conftest import REPO
from guardian.data.loader import DataError, load_bundle, resolve_data_dir
from guardian.finance.metrics import annualization_factor

DATA = resolve_data_dir()
WEIGHTS = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}


def test_official_files_are_unmodified():
    manifest = yaml.safe_load((REPO / "config" / "data_manifest.yaml").read_text())["sha256"]
    for name, expected in manifest.items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == expected, name


def test_bundle_loads_and_matches_audit(real_service):
    b = real_service.bundle
    assert b.manifest_mismatch == ()
    assert b.rows == {"assets_universe.csv": 31, "prices_daily.csv": 40049, "fx_usdcad_daily.csv": 1245}
    assert len(real_service.panel.grid) == 1228
    assert len(real_service.panel.fx_ffilled_dates) == 10


def test_all_portfolio_assets_exist_and_weights_sum_to_100(real_service):
    assert set(WEIGHTS) <= set(real_service.bundle.universe.index)
    preset = yaml.safe_load((REPO / "config" / "presets.yaml").read_text())["presets"]["robert_nvda_40"]
    assert sum(preset["weights_pct"].values()) == pytest.approx(100.0)
    assert preset["weights_pct"] == {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25}


def _read(name):
    with open(DATA / name, newline="") as f:
        return list(csv.DictReader(f))


def test_usd_to_cad_conversion_matches_independent_computation(real_service):
    fx = {r["date"]: float(r["usdcad"]) for r in _read("fx_usdcad_daily.csv")}
    nvda = {r["date"]: float(r["adj_close"]) for r in _read("prices_daily.csv") if r["ticker"] == "NVDA"}
    for d in ["2021-11-12", "2023-03-15", "2026-11-12", "2022-11-11"]:     # 2022-11-11 : taux reporté
        ts = real_service.panel.prices_cad.index[real_service.panel.prices_cad.index == d]
        assert len(ts) == 1, d
        rate = fx.get(d)
        if rate is None:                                            # report vers l'avant, recalculé à la main
            rate = fx[max(k for k in fx if k < d)]
        assert real_service.panel.prices_cad.loc[d, "NVDA"] == pytest.approx(nvda[d] * rate, rel=1e-12)
    # un actif CAD n'est pas converti
    xiu = {r["date"]: float(r["adj_close"]) for r in _read("prices_daily.csv") if r["ticker"] == "XIU.TO"}
    assert real_service.panel.prices_cad.loc["2023-03-15", "XIU.TO"] == pytest.approx(xiu["2023-03-15"])


def test_portfolio_metrics_match_independent_implementation(real_service):
    """Recalcul sans réutiliser le code du moteur : lecture csv, report FX à la main, rééquilibrage mensuel à la main."""
    grid = [d for d in map(str, real_service.panel.grid.date)]
    fx = {r["date"]: float(r["usdcad"]) for r in _read("fx_usdcad_daily.csv")}
    px = {}
    for r in _read("prices_daily.csv"):
        if r["ticker"] in WEIGHTS:
            px.setdefault(r["ticker"], {})[r["date"]] = float(r["adj_close"])
    last_rate, prices = None, {t: [] for t in WEIGHTS}
    for d in grid:
        last_rate = fx.get(d, last_rate)
        for t in WEIGHTS:
            p = px[t][d]
            prices[t].append(p * last_rate if t == "NVDA" else p)
    P = np.array([prices[t] for t in WEIGHTS]).T
    w = np.array(list(WEIGHTS.values()))
    shares = 100000 * w / P[0]
    vals = []
    for i in range(len(grid)):
        vals.append(shares @ P[i])
        if i < len(grid) - 1 and grid[i][:7] != grid[i + 1][:7]:
            shares = vals[-1] * w / P[i]
    vals = np.array(vals)
    r = vals[1:] / vals[:-1] - 1
    import datetime as dt
    years = (dt.date.fromisoformat(grid[-1]) - dt.date.fromisoformat(grid[0])).days / 365.25
    factor = (len(grid) - 1) / years
    expected = {
        "cum": vals[-1] / vals[0] - 1,
        "ann": (vals[-1] / vals[0]) ** (1 / years) - 1,
        "vol": r.std(ddof=1) * np.sqrt(factor),
        "mdd": (vals / np.maximum.accumulate(vals) - 1).min(),
    }
    res = real_service.analyze(WEIGHTS)
    assert res.n_obs == len(grid)
    assert res.factor == pytest.approx(factor)
    assert res.cumulative_return == pytest.approx(expected["cum"], rel=1e-9)
    assert res.annualized_return == pytest.approx(expected["ann"], rel=1e-9)
    assert res.volatility == pytest.approx(expected["vol"], rel=1e-9)
    assert res.drawdown.max_drawdown == pytest.approx(expected["mdd"], rel=1e-9)


def test_single_asset_nvda_close_to_audit_reference(real_service):
    """Contrôle de plausibilité avec DATA_AUDIT.md §8 (autre grille : 1 218 jours et facteur 252 dans l'audit)."""
    a = {x.ticker: x for x in real_service.analyze(WEIGHTS).assets}["NVDA"]
    assert abs(a.annualized_vol - 0.515) < 0.01
    assert abs(a.max_drawdown - (-0.635)) < 0.005


# ---------------------------------------------------------------- échecs du chargeur
def _copy_data(tmp_path):
    for n in ["assets_universe.csv", "prices_daily.csv", "fx_usdcad_daily.csv"]:
        shutil.copy(DATA / n, tmp_path / n)
    return tmp_path


def test_loader_missing_file(tmp_path):
    with pytest.raises(DataError, match="introuvable"):
        load_bundle(tmp_path)


def test_loader_detects_duplicate_rows(tmp_path):
    d = _copy_data(tmp_path)
    lines = (d / "prices_daily.csv").read_text().splitlines()
    (d / "prices_daily.csv").write_text("\n".join(lines + [lines[1]]) + "\n")
    with pytest.raises(DataError, match="doublons"):
        load_bundle(d)


def test_loader_detects_unknown_ticker_and_flags_modified_files(tmp_path):
    d = _copy_data(tmp_path)
    lines = (d / "prices_daily.csv").read_text().splitlines()
    bad = lines[1].replace(lines[1].split(",")[1], "ZZZ", 1)
    (d / "prices_daily.csv").write_text("\n".join(lines + [bad]) + "\n")
    with pytest.raises(DataError, match="absents de l'univers"):
        load_bundle(d)


def test_manifest_mismatch_is_reported_not_fatal(tmp_path):
    d = _copy_data(tmp_path)
    fx = (d / "fx_usdcad_daily.csv").read_text().replace("1.3", "1.4", 1)
    (d / "fx_usdcad_daily.csv").write_text(fx)
    assert "fx_usdcad_daily.csv" in load_bundle(d).manifest_mismatch
