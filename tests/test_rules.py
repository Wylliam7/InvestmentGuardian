"""Guardian Check : classification, configuration, seuils gelés, profils Robert et Amira, règle R7."""
import copy
from types import SimpleNamespace

import pandas as pd
import pytest

from guardian.rules import engine
from guardian.rules.engine import ATTENTION, CONFLIT, INFO, OK, ConfigError, classify, evaluate


def fake_result(weights, vols, classes=None, portfolio_vol=0.08, mdd=-0.10, sectors=None):
    classes = classes or {t: "equity" for t in weights}
    sectors = sectors or {t: "Financials" for t in weights}
    assets = [SimpleNamespace(ticker=t, weight=w, annualized_vol=vols[t], asset_class=classes[t], sector=sectors[t]) for t, w in weights.items()]
    mx = max(weights, key=weights.get)
    hhi = sum(w * w for w in weights.values())
    return SimpleNamespace(
        assets=assets, weights=weights, volatility=portfolio_vol, factor=245.4, n_obs=1228, years=5.0,
        concentration=SimpleNamespace(max_weight=weights[mx], max_ticker=mx, hhi=hhi, effective_n=1 / hhi),
        drawdown=SimpleNamespace(max_drawdown=mdd, peak_date=pd.Timestamp("2022-01-03"),
                                 trough_date=pd.Timestamp("2022-10-14"), recovered=True, underwater_days=300))


def test_thresholds_are_frozen_as_documented():
    """PROJECT_SPEC §7 : toute modification de seuil doit être consciente (ce test doit alors être mis à jour avec une justification écrite)."""
    cfg = engine.load_rules_config()
    th = {r: {p: (v["attention"], v["conflict"]) for p, v in rule["thresholds"].items()} for r, rule in cfg["rules"].items()}
    assert th == {
        "R1": {"robert": (0.10, 0.20), "amira": (0.20, 0.35)},
        "R2": {"robert": (0.10, 0.20), "amira": (0.35, 0.50)},
        "R4": {"robert": (0.10, 0.14), "amira": (0.25, 0.35)},
        "R5": {"robert": (0.15, 0.25), "amira": (0.40, 0.55)},
        "R7": {"robert": (6, 4), "amira": (5, 3)},
    }
    assert cfg["volatile_asset_vol_threshold"] == 0.35
    assert cfg["status"] == "heuristique"
    assert [cfg["rules"][r]["direction"] for r in ("R1", "R2", "R4", "R5", "R7")] == ["max", "max", "max", "max", "min"]


def test_classify_boundaries_are_strict():
    assert classify(0.10, 0.10, 0.20) == OK
    assert classify(0.1001, 0.10, 0.20) == ATTENTION
    assert classify(0.20, 0.10, 0.20) == ATTENTION
    assert classify(0.2001, 0.10, 0.20) == CONFLIT


def test_classify_boundaries_for_minimum_rule_r7():
    assert classify(6.0, 6, 4, "min") == OK            # égal au seuil : pas franchi
    assert classify(5.99, 6, 4, "min") == ATTENTION
    assert classify(4.0, 6, 4, "min") == ATTENTION
    assert classify(3.99, 6, 4, "min") == CONFLIT


def test_r7_matches_documented_definition_effective_n():
    """R7 = 1/HHI (PROJECT_SPEC §7) : 40/35/25 → 2,9 ; 4 positions égales → 4,0."""
    w = {"X": .4, "Y": .35, "Z": .25}
    rep = evaluate(fake_result(w, {t: .1 for t in w}), "robert")
    f = rep.by_id()["R7"]
    assert f.measured == pytest.approx(1 / 0.345) and f.status == CONFLIT and f.direction == "min"


def test_r7_exact_boundary_values():
    eq4 = {f"A{i}": .25 for i in range(4)}       # N effectif = 4,0
    eq6 = {f"A{i}": 1 / 6 for i in range(6)}     # N effectif = 6,0 (à la précision flottante près)
    r4 = evaluate(fake_result(eq4, {t: .1 for t in eq4}), "robert").by_id()["R7"]
    r6 = evaluate(fake_result(eq6, {t: .1 for t in eq6}), "robert").by_id()["R7"]
    assert r4.status == ATTENTION       # 4,0 : pas < 4 (conflit) mais < 6 (attention)
    assert r6.status == OK              # 6,0 : pas < 6, malgré une éventuelle erreur de virgule flottante


def test_diversified_low_risk_portfolio_is_ok_for_both_profiles():
    w = {f"A{i}": 0.1 for i in range(10)}          # 10 positions de 10 % : R1 = 10 % (pas > 10 %), N effectif = 10
    for pid in ("robert", "amira"):
        rep = evaluate(fake_result(w, {t: 0.12 for t in w}, portfolio_vol=0.08, mdd=-0.10), pid)
        assert {f.rule_id: f.status for f in rep.findings} == {"R1": OK, "R2": OK, "R4": OK, "R5": OK, "R7": OK, "R10": INFO}


def test_concentrated_volatile_portfolio_flags_conflicts_for_robert():
    w = {"X": .4, "Y": .35, "Z": .25}
    rep = evaluate(fake_result(w, {"X": .5, "Y": .07, "Z": .13}, portfolio_vol=.22, mdd=-.36), "robert")
    st = {f.rule_id: f.status for f in rep.findings}
    assert st == {"R1": CONFLIT, "R2": CONFLIT, "R4": CONFLIT, "R5": CONFLIT, "R7": CONFLIT, "R10": INFO}
    r2 = rep.by_id()["R2"]
    assert r2.measured == pytest.approx(.4) and [a["ticker"] for a in r2.evidence["volatile_assets"]] == ["X"]


def test_same_measures_different_statuses_for_robert_and_amira():
    w = {"X": .4, "Y": .35, "Z": .25}
    res = fake_result(w, {"X": .5, "Y": .07, "Z": .13}, portfolio_vol=.22, mdd=-.36)
    rob, ami = evaluate(res, "robert"), evaluate(res, "amira")
    for rid in ("R1", "R2", "R4", "R5", "R7"):
        assert rob.by_id()[rid].measured == ami.by_id()[rid].measured          # mêmes mesures
        assert rob.by_id()[rid].profile_id == "robert" and ami.by_id()[rid].profile_id == "amira"
    assert [ami.by_id()[r].status for r in ("R1", "R2", "R4", "R5", "R7")] == [CONFLIT, ATTENTION, OK, OK, CONFLIT]   # 40 % > 35 % ; vol 22 % < 25 %
    assert [rob.by_id()[r].status for r in ("R1", "R2", "R4", "R5", "R7")] == [CONFLIT] * 5
    # seuils appliqués = ceux du profil
    assert (ami.by_id()["R1"].threshold_attention, ami.by_id()["R1"].threshold_conflict) == (0.20, 0.35)
    assert (rob.by_id()["R1"].threshold_attention, rob.by_id()["R1"].threshold_conflict) == (0.10, 0.20)


def test_high_risk_tolerance_does_not_accept_everything_for_amira():
    w = {"A": .6, "B": .4}          # position unique de 60 %, N effectif 1,92
    rep = evaluate(fake_result(w, {"A": .5, "B": .5}, portfolio_vol=.40, mdd=-.60), "amira")
    assert {r: rep.by_id()[r].status for r in ("R1", "R2", "R4", "R5", "R7")} == {"R1": CONFLIT, "R2": CONFLIT, "R4": CONFLIT, "R5": CONFLIT, "R7": CONFLIT}


def test_crypto_counts_as_volatile_even_with_low_measured_volatility():
    w = {"B": .85, "C": .15}
    rep = evaluate(fake_result(w, {"B": .05, "C": .10}, classes={"B": "etf_bond", "C": "crypto"}), "robert")
    r2 = rep.by_id()["R2"]
    assert r2.measured == pytest.approx(.15) and r2.status == ATTENTION


def test_changing_threshold_changes_status():
    res = fake_result({"X": .15, "Y": .85}, {"X": .1, "Y": .1})
    cfg = engine.load_rules_config()
    base = evaluate(res, "robert", cfg).by_id()["R1"].status
    cfg2 = copy.deepcopy(cfg)
    cfg2["rules"]["R1"]["thresholds"]["robert"] = {"attention": 0.5, "conflict": 0.9}
    assert base == CONFLIT
    assert evaluate(res, "robert", cfg2).by_id()["R1"].status == ATTENTION


def test_every_finding_carries_required_fields():
    w = {"X": .4, "Y": .6}
    for f in evaluate(fake_result(w, {"X": .5, "Y": .1}), "robert").findings:
        assert f.status in (OK, ATTENTION, CONFLIT, INFO)
        assert f.heuristic is True and f.config_version
        assert f.justification.strip() and f.method.strip() and f.limitations and f.summary and f.display["phrase" if f.status != INFO else "measured"] is not None
        d = f.to_dict()
        assert {"status", "status_label", "measured", "threshold_attention", "threshold_conflict", "justification", "method", "limitations"} <= set(d)
        if f.status != INFO:
            assert f.threshold_attention is not None and f.threshold_conflict is not None


def test_status_labels_follow_the_requested_vocabulary():
    assert engine.STATUS_LABELS == {OK: "Conforme", ATTENTION: "Attention", CONFLIT: "Conflit", INFO: "Information"}


def test_r10_tech_share_only_for_profile_with_qualitative_constraint():
    w = {"NVDA": .3, "SHOP.TO": .1, "QQQ": .2, "XBB.TO": .4}
    sectors = {"NVDA": "Information Technology", "SHOP.TO": "Information Technology", "QQQ": "Broad market (U.S. growth/tech-heavy)", "XBB.TO": "Bonds (Canada aggregate)"}
    classes = {"NVDA": "equity", "SHOP.TO": "equity", "QQQ": "etf_equity", "XBB.TO": "etf_bond"}
    res = fake_result(w, {t: .2 for t in w}, classes=classes, sectors=sectors)
    ami, rob = evaluate(res, "amira").by_id()["R10"], evaluate(res, "robert").by_id()["R10"]
    assert ami.status == INFO and ami.measured == pytest.approx(.4) and ami.evidence["qqq_weight_pct"] == 20.0
    assert ami.threshold_attention is None and ami.threshold_conflict is None            # aucun seuil appliqué
    assert rob.measured is None and "tech_share_pct" not in rob.evidence


def test_invalid_config_is_rejected():
    cfg = copy.deepcopy(engine.load_rules_config())
    cfg["rules"]["R1"]["thresholds"]["robert"] = {"attention": 0.3, "conflict": 0.2}
    with pytest.raises(ConfigError):
        engine.validate_rules_config(cfg)
    cfg = copy.deepcopy(engine.load_rules_config())
    cfg["rules"]["R7"]["thresholds"]["robert"] = {"attention": 4, "conflict": 6}          # sens inversé pour une règle « min »
    with pytest.raises(ConfigError):
        engine.validate_rules_config(cfg)
    cfg = copy.deepcopy(engine.load_rules_config())
    del cfg["rules"]["R4"]
    with pytest.raises(ConfigError):
        engine.validate_rules_config(cfg)


def test_unknown_profile_is_rejected():
    with pytest.raises(ConfigError, match="Profil inconnu"):
        evaluate(fake_result({"X": 1.0}, {"X": .1}), "mateo")


def test_amira_profile_matches_official_case():
    a = engine.load_profiles()["amira"]
    assert a["age"] == 26 and a["risk_profile_label"] == "Élevé" and a["horizon_years_min"] == 15 and a["horizon_years_max"] is None
    assert "Faire croître son capital à long terme" in a["objective"]
    assert any("cryptoactifs" in p for p in a["preferences"]) and any("exclusivement sur les technologies" in p for p in a["preferences"])
    assert "p. 5" in a["source"]


def test_real_scenario_runs_and_documents_what_was_measured(real_service):
    """On vérifie la structure du constat, pas un diagnostic prédéterminé."""
    res, rep = real_service.check({"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}, "robert")
    byid = rep.by_id()
    assert byid["R1"].measured == pytest.approx(0.40)
    assert byid["R4"].measured == pytest.approx(res.volatility)
    assert byid["R5"].measured == pytest.approx(abs(res.drawdown.max_drawdown))
    assert byid["R7"].measured == pytest.approx(res.concentration.effective_n)
    assert sum(rep.counts().values()) == 6
