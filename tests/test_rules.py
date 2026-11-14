"""Guardian Check : classification, configuration, aucun seuil modifié en silence."""
import copy
from types import SimpleNamespace

import pytest

from guardian.rules import engine
from guardian.rules.engine import ATTENTION, CONFLIT, OK, ConfigError, classify, evaluate


def fake_result(weights, vols, classes=None, portfolio_vol=0.08, mdd=-0.10):
    classes = classes or {t: "equity" for t in weights}
    assets = [SimpleNamespace(ticker=t, weight=w, annualized_vol=vols[t], asset_class=classes[t]) for t, w in weights.items()]
    mx = max(weights, key=weights.get)
    return SimpleNamespace(
        assets=assets, weights=weights, volatility=portfolio_vol, factor=245.4, n_obs=1228,
        concentration=SimpleNamespace(max_weight=weights[mx], max_ticker=mx),
        drawdown=SimpleNamespace(max_drawdown=mdd, peak_date=__import__("pandas").Timestamp("2022-01-03"),
                                 trough_date=__import__("pandas").Timestamp("2022-10-14"), recovered=True, underwater_days=300))


def test_thresholds_are_frozen_as_documented():
    """PROJECT_SPEC §7 : toute modification de seuil doit être consciente (ce test doit alors être mis à jour avec une justification)."""
    cfg = engine.load_rules_config()
    th = {r: (v["thresholds"]["robert"]["attention"], v["thresholds"]["robert"]["conflict"]) for r, v in cfg["rules"].items()}
    assert th == {"R1": (0.10, 0.20), "R2": (0.10, 0.20), "R4": (0.10, 0.14), "R5": (0.15, 0.25)}
    assert cfg["volatile_asset_vol_threshold"] == 0.35
    assert cfg["status"] == "heuristique"


def test_classify_boundaries_are_strict():
    assert classify(0.10, 0.10, 0.20) == OK
    assert classify(0.1001, 0.10, 0.20) == ATTENTION
    assert classify(0.20, 0.10, 0.20) == ATTENTION
    assert classify(0.2001, 0.10, 0.20) == CONFLIT


def test_diversified_low_risk_portfolio_is_ok():
    w = {f"A{i}": 0.1 for i in range(10)}
    rep = evaluate(fake_result(w, {t: 0.12 for t in w}, portfolio_vol=0.08, mdd=-0.10), "robert")
    assert {f.rule_id: f.status for f in rep.findings} == {"R1": OK, "R2": OK, "R4": OK, "R5": OK}


def test_concentrated_volatile_portfolio_flags_conflicts():
    w = {"X": .4, "Y": .35, "Z": .25}
    rep = evaluate(fake_result(w, {"X": .5, "Y": .07, "Z": .13}, portfolio_vol=.22, mdd=-.36), "robert")
    st = {f.rule_id: f.status for f in rep.findings}
    assert st == {"R1": CONFLIT, "R2": CONFLIT, "R4": CONFLIT, "R5": CONFLIT}
    r2 = {f.rule_id: f for f in rep.findings}["R2"]
    assert r2.measured == pytest.approx(.4) and [a["ticker"] for a in r2.evidence["volatile_assets"]] == ["X"]


def test_crypto_counts_as_volatile_even_with_low_measured_volatility():
    w = {"B": .85, "C": .15}
    rep = evaluate(fake_result(w, {"B": .05, "C": .10}, classes={"B": "etf_bond", "C": "crypto"}), "robert")
    r2 = {f.rule_id: f for f in rep.findings}["R2"]
    assert r2.measured == pytest.approx(.15) and r2.status == ATTENTION


def test_changing_threshold_changes_status():
    w = {"X": .15, "Y": .85}
    res = fake_result({"X": .15, "Y": .85}, {"X": .1, "Y": .1})
    cfg = engine.load_rules_config()
    base = {f.rule_id: f.status for f in evaluate(res, "robert", cfg).findings}["R1"]
    cfg2 = copy.deepcopy(cfg)
    cfg2["rules"]["R1"]["thresholds"]["robert"] = {"attention": 0.5, "conflict": 0.9}
    assert base == CONFLIT
    assert {f.rule_id: f.status for f in evaluate(res, "robert", cfg2).findings}["R1"] == ATTENTION


def test_every_finding_carries_required_fields():
    w = {"X": .4, "Y": .6}
    for f in evaluate(fake_result(w, {"X": .5, "Y": .1}), "robert").findings:
        assert f.status in (OK, ATTENTION, CONFLIT)
        assert f.heuristic is True and f.config_version
        assert f.justification.strip() and f.method.strip() and f.limitations and f.summary
        assert 0 <= f.threshold_attention < f.threshold_conflict <= 1
        d = f.to_dict()
        assert {"status", "measured", "threshold_attention", "threshold_conflict", "justification", "method", "limitations"} <= set(d)


def test_invalid_config_is_rejected():
    cfg = copy.deepcopy(engine.load_rules_config())
    cfg["rules"]["R1"]["thresholds"]["robert"] = {"attention": 0.3, "conflict": 0.2}
    with pytest.raises(ConfigError):
        engine.validate_rules_config(cfg)
    cfg = copy.deepcopy(engine.load_rules_config())
    del cfg["rules"]["R4"]
    with pytest.raises(ConfigError):
        engine.validate_rules_config(cfg)


def test_unknown_profile_is_rejected():
    with pytest.raises(ConfigError, match="Profil inconnu"):
        evaluate(fake_result({"X": 1.0}, {"X": .1}), "amira")


def test_real_scenario_runs_and_documents_what_was_measured(real_service):
    """On vérifie la structure du constat, pas un diagnostic prédéterminé."""
    res, rep = real_service.check({"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}, "robert")
    byid = {f.rule_id: f for f in rep.findings}
    assert byid["R1"].measured == pytest.approx(0.40)
    assert byid["R4"].measured == pytest.approx(res.volatility)
    assert byid["R5"].measured == pytest.approx(abs(res.drawdown.max_drawdown))
    assert sum(rep.counts().values()) == 4
