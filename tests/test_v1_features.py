"""V1 : profils Robert/Amira, quatre portefeuilles, constructeur, comparaison A/B, outils get_profile et compare_scenarios."""
import csv
import re
from types import SimpleNamespace

import pandas as pd
import pytest

from conftest import StepModel, expected_compare
from guardian.agent.agent import GuardianAgent
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.data.loader import resolve_data_dir
from guardian.finance.builder import normalize_to_100, parse_weight_rows, rows_from_weights
from guardian.finance.compare import ComparisonError, compare_portfolios
from guardian.finance.presets import EXPECTED_PRESET_IDS, PresetError, load_presets, validate_presets
from guardian.rules.engine import CONFLIT, INFO

NVDA40 = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}
GP, EV, CK, CMP = "get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios"
FORBIDDEN_WORDS = re.compile(r"\b(meilleur|meilleure|pire|gagnant|gagnante|vainqueur|recommand\w*|optimal\w*)\b", re.I)


def tools_by_name(service, ctx, tracer=None):
    tracer = tracer or Tracer()
    return {t.tool_spec["name"]: t for t in build_tools(service, ctx, tracer)}, tracer


# ------------------------------------------------------------------ 1-2. même portefeuille, deux profils
def test_same_portfolio_gives_identical_financial_metrics_for_both_profiles(real_service):
    res_r, rep_r = real_service.check(NVDA40, "robert")
    res_a, rep_a = real_service.check(NVDA40, "amira")
    assert res_r.to_tool_dict() == res_a.to_tool_dict()                                       # moteur : strictement identique
    for rid in ("R1", "R2", "R4", "R5", "R7"):
        assert rep_r.by_id()[rid].measured == rep_a.by_id()[rid].measured                      # mêmes mesures
    assert [f.status for f in rep_r.findings] != [f.status for f in rep_a.findings]            # diagnostics différents


def test_guardian_check_uses_the_selected_profile_thresholds(real_service):
    cfg = real_service.rules_cfg["rules"]
    for pid in ("robert", "amira"):
        _, rep = real_service.check(NVDA40, pid)
        assert rep.profile_id == pid and rep.profile_name == real_service.profiles[pid]["display_name"]
        for rid in ("R1", "R2", "R4", "R5", "R7"):
            f = rep.by_id()[rid]
            assert f.profile_id == pid
            assert (f.threshold_attention, f.threshold_conflict) == (cfg[rid]["thresholds"][pid]["attention"], cfg[rid]["thresholds"][pid]["conflict"])


def test_tool_check_profile_constraints_respects_requested_profile(real_service):
    ctx = SessionContext(NVDA40, "robert")
    t, tracer = tools_by_name(real_service, ctx)
    out_default, out_amira = t[CK](), t[CK](profile_id="amira")
    assert out_default["profile_id"] == "robert" and out_amira["profile_id"] == "amira"
    assert out_amira["profile"]["age"] == 26
    assert out_default["window"] == out_amira["window"] and out_default["weights_pct"] == out_amira["weights_pct"]      # mêmes mesures
    assert [r.status for r in tracer.records] == ["ok", "ok"]


# ------------------------------------------------------------------ 3. quatre portefeuilles
def test_four_presets_are_valid_exact_and_use_official_assets(real_service):
    presets = load_presets()
    assert tuple(presets) == EXPECTED_PRESET_IDS and len(presets) == 6   # 4 de V1 + 2 de Mateo (V3)
    with open(resolve_data_dir() / "assets_universe.csv", newline="") as f:
        official = {r["ticker"] for r in csv.DictReader(f)}
    for pid, p in presets.items():
        w = p["weights_pct"]
        assert sum(w.values()) == 100, pid                                                    # somme EXACTE (entiers)
        assert all(isinstance(v, int) and v > 0 for v in w.values()) and set(w) <= official, pid
    validate_presets(presets, real_service.bundle.universe.index, real_service.profiles)
    for pid, p in presets.items():                                                            # chacun s'analyse pour les trois profils
        for prof in ("robert", "amira", "mateo"):
            res, rep = real_service.check({t: v / 100 for t, v in p["weights_pct"].items()}, prof)
            assert res.n_obs == 1228 and len(rep.findings) == 6


def test_preset_compositions_are_frozen_as_documented():
    """Les compositions ont été fixées avant de voir les diagnostics (DECISIONS.md, section V1). Toute modification doit être justifiée."""
    p = {k: v["weights_pct"] for k, v in load_presets().items()}
    assert p["robert_nvda_40"] == {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25}                     # pondérations validées en V0
    assert p["robert_prudent"] == {"XBB.TO": 15, "ZST.TO": 10, "AGG": 10, "XIU.TO": 15, "SPY": 10, "RY.TO": 5, "JNJ": 5, "PG": 5,
                                   "FTS.TO": 5, "CNR.TO": 5, "ENB.TO": 5, "GLD": 10}
    assert p["amira_croissance"] == {"QQQ": 20, "SPY": 20, "XIU.TO": 15, "NVDA": 10, "SHOP.TO": 5, "BTC-USD": 5, "XBB.TO": 10, "RY.TO": 5, "JNJ": 5, "XOM": 5}
    assert p["amira_tech_crypto"] == {"NVDA": 25, "TSLA": 15, "QQQ": 25, "SHOP.TO": 5, "BTC-USD": 20, "ETH-USD": 10}


def test_invalid_preset_is_rejected(real_service):
    bad = {"x": {"weights_pct": {"NVDA": 50, "XBB.TO": 40}, "profile_id": "robert"}}
    with pytest.raises(PresetError):
        validate_presets(bad, real_service.bundle.universe.index, real_service.profiles)


# ------------------------------------------------------------------ 4-6. constructeur
KNOWN = {"NVDA", "XBB.TO", "XIU.TO", "SPY"}


def rows(*pairs):
    return [{"ticker": t, "weight_pct": w} for t, w in pairs]


def test_builder_accepts_valid_weights_and_never_changes_them():
    r = parse_weight_rows(rows(("NVDA", 33.333), ("XBB.TO", 33.333), ("XIU.TO", 33.334)), KNOWN)
    assert r.valid and r.weights_pct == {"NVDA": 33.333, "XBB.TO": 33.333, "XIU.TO": 33.334}      # valeurs exactement saisies
    assert r.fraction_weights["NVDA"] == pytest.approx(0.33333)


@pytest.mark.parametrize("data,fragment", [
    (rows(("NVDA", -10), ("XBB.TO", 110)), "négatif"),
    (rows(("NVDA", 50), ("ZZZ", 50)), "absent de l'univers"),
    (rows(("NVDA", 50), ("NVDA", 50)), "double"),
    (rows(("NVDA", 0), ("XBB.TO", 100)), "poids nul"),
    (rows(("NVDA", 50), ("XBB.TO", 40)), "somme"),
    (rows(("NVDA", "abc"), ("XBB.TO", 100)), "non numérique"),
    (rows(("NVDA", None), ("XBB.TO", 100)), "aucun poids"),
    (rows((None, 20), ("XBB.TO", 80)), "sans actif"),
    ([], "vide"),
])
def test_builder_rejects_invalid_input(data, fragment):
    r = parse_weight_rows(data, KNOWN)
    assert not r.valid and r.weights_pct is None
    assert any(fragment in e for e in r.errors), r.errors


def test_builder_sum_validation_tolerance_and_reporting():
    assert parse_weight_rows(rows(("NVDA", 50.005), ("XBB.TO", 50.0)), KNOWN).valid       # écart 0,005 point : toléré
    r = parse_weight_rows(rows(("NVDA", 50.5), ("XBB.TO", 50.0)), KNOWN)
    assert not r.valid and r.only_sum_is_wrong and r.total_pct == pytest.approx(100.5)
    assert r.weights_pct is None                                                          # rien n'est analysé tant que ce n'est pas corrigé


def test_builder_blank_rows_are_ignored_and_normalization_is_explicit_only():
    r = parse_weight_rows([{"ticker": None, "weight_pct": None}, {"ticker": "NVDA", "weight_pct": 30}, {"ticker": "", "weight_pct": float("nan")},
                           {"ticker": "XBB.TO", "weight_pct": 30}], KNOWN)
    assert r.only_sum_is_wrong and r.rows_seen == {"NVDA": 30.0, "XBB.TO": 30.0}
    assert normalize_to_100(r.rows_seen) == {"NVDA": 50.0, "XBB.TO": 50.0}               # fonction appelée uniquement sur action de l'utilisateur
    assert parse_weight_rows(rows_from_weights(normalize_to_100(r.rows_seen)), KNOWN).valid
    with pytest.raises(ValueError):
        normalize_to_100({"NVDA": 0.0})


# ------------------------------------------------------------------ 9. nouvelles pondérations → nouvelles métriques
def test_changing_weights_recomputes_metrics(real_service):
    base = real_service.analyze(NVDA40)
    less = real_service.analyze({"NVDA": .10, "XBB.TO": .55, "XIU.TO": .35})
    assert less.volatility < base.volatility and abs(less.drawdown.max_drawdown) < abs(base.drawdown.max_drawdown)
    assert less.concentration.max_weight == pytest.approx(.55) and less is not base
    again = real_service.analyze(dict(NVDA40))
    assert again.volatility == base.volatility                                            # déterministe


# ------------------------------------------------------------------ 7-8. comparaison A/B
def test_portfolio_compared_with_itself_has_zero_differences(real_service):
    c = compare_portfolios(real_service, NVDA40, dict(NVDA40), "robert")
    d = c.deltas
    for k in ("cumulative_return_pts", "annualized_return_pts", "annualized_volatility_pts", "max_drawdown_pts",
              "largest_position_weight_pts", "effective_positions"):
        assert d[k] == 0, k
    assert c.a.value.equals(c.b.value) and [f.status for f in c.report_a.findings] == [f.status for f in c.report_b.findings]
    assert any("proches" in t for t in c.tradeoffs)


def test_two_portfolios_are_compared_on_exactly_the_same_period_and_conventions(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    c = compare_portfolios(real_service, NVDA40, prudent, "robert")
    assert c.a.value.index.equals(c.b.value.index) and c.a.series.start == c.b.series.start and c.a.series.end == c.b.series.end
    assert c.a.series.rebalance == c.b.series.rebalance == "monthly" and c.a.factor == c.b.factor
    assert c.conventions["currency"] == "CAD" and c.conventions["same_date_grid"] is True and c.conventions["n_observations"] == 1228
    sub = compare_portfolios(real_service, NVDA40, prudent, "amira", "2023-01-02", "2024-12-31")             # fenêtre partagée, profil différent
    assert sub.a.value.index.equals(sub.b.value.index) and str(sub.a.series.start.date()) >= "2023-01-02" and str(sub.a.series.end.date()) <= "2024-12-31"
    assert sub.a.annualized_return is not None                                                                 # 2 ans


def test_comparison_values_match_the_engine_and_deltas_are_b_minus_a(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    c = compare_portfolios(real_service, NVDA40, prudent, "robert")
    a, b = real_service.analyze(NVDA40), real_service.analyze(prudent)
    assert c.deltas["annualized_volatility_pts"] == pytest.approx(100 * (b.volatility - a.volatility), abs=0.006)
    assert c.deltas["max_drawdown_pts"] == pytest.approx(100 * (b.drawdown.max_drawdown - a.drawdown.max_drawdown), abs=0.006)
    assert c.deltas["effective_positions"] == pytest.approx(b.concentration.effective_n - a.concentration.effective_n, abs=0.006)


def test_comparison_never_names_a_winner_even_when_one_return_is_higher(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    c = compare_portfolios(real_service, NVDA40, prudent, "robert")
    assert c.a.cumulative_return > c.b.cumulative_return                                     # A a le rendement historique le plus élevé
    sentences = [*c.tradeoffs, c.to_tool_dict()["no_winner_notice"]]
    disclaimers = [s for s in sentences if re.search(r"ne désign\w+ pas", s)]
    assert disclaimers                                                                         # la formule négative existe
    assertive = " ".join(s for s in sentences if s not in disclaimers)                         # hors formules niant un verdict
    assert not FORBIDDEN_WORDS.search(assertive), FORBIDDEN_WORDS.search(assertive)
    assert any("compromis" in t.lower() for t in c.tradeoffs) and any("ne désignent pas" in t for t in c.tradeoffs)
    assert c.report_a.counts()[CONFLIT] > c.report_b.counts()[CONFLIT]


def test_comparison_fails_loudly_if_grids_differ():
    idx1, idx2 = pd.date_range("2024-01-01", periods=3), pd.date_range("2024-01-02", periods=3)
    mk = lambda i: SimpleNamespace(value=pd.Series([1.0, 2.0, 3.0], index=i))  # noqa: E731
    fake = SimpleNamespace(check=lambda w, p, s=None, e=None: (mk(idx1 if w == "a" else idx2), None))
    with pytest.raises(ComparisonError, match="même grille"):
        compare_portfolios(fake, "a", "b", "robert")


# ------------------------------------------------------------------ 10. get_profile
def test_get_profile_returns_official_profile_and_heuristic_thresholds(real_service):
    ctx = SessionContext(NVDA40, "robert")
    t, tracer = tools_by_name(real_service, ctx)
    amira, active = t[GP](profile_id="Amira"), t[GP]()
    assert amira["status"] == "ok" and amira["profile"]["age"] == 26 and amira["profile"]["horizon_years_min"] == 15 and amira["is_active_profile"] is False
    assert amira["thresholds_are_heuristics"] is True and amira["heuristic_thresholds"]["R7"]["direction"] == "min"
    assert amira["heuristic_thresholds"]["R1"]["conflict"] == 0.35 and active["profile_id"] == "robert" and active["is_active_profile"] is True
    bad = t[GP](profile_id="zzz")
    assert bad["status"] == "error" and "Profil inconnu" in bad["message"]
    assert [r.status for r in tracer.records] == ["ok", "ok", "error"] and tracer.records[0].arguments == {"profile_id": "Amira"}
    assert tracer.records[0].data_refs["profile_source"].endswith("p. 5")


# ------------------------------------------------------------------ 11. compare_scenarios
def test_compare_scenarios_tool_matches_engine_and_requires_portfolio_b(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    ctx = SessionContext(NVDA40, "robert", weights_b=prudent)
    t, tracer = tools_by_name(real_service, ctx)
    out = t[CMP]()
    assert out == expected_compare(real_service, NVDA40, prudent, "robert")
    assert out["differences_B_minus_A"]["annualized_volatility_pts"] < 0 and "no_winner_notice" in out
    ctx.weights_b = None
    err = t[CMP]()
    assert err["status"] == "error" and "portefeuille B" in err["message"]
    assert [r.status for r in tracer.records] == ["ok", "error"]


def test_agent_uses_get_profile_and_compare_scenarios_with_faithful_trace(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    ctx = SessionContext(NVDA40, "robert", weights_b=prudent)
    model = StepModel([("tools", [GP, CMP]), ("text", "Interprétation : compromis historiques entre rendement et risque.")])
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model)
    tr = ag.ask("Compare A et B pour Robert.")
    by = {r.tool: r for r in tr.tool_records}
    assert sorted(by) == [CMP, GP] and all(r.status == "ok" and r.turn == 1 for r in tr.tool_records) and not tr.withheld
    assert by[CMP].result == expected_compare(real_service, NVDA40, prudent, "robert")
    assert tr.context["weights_a_pct"]["NVDA"] == 40.0 and tr.context["weights_b_pct"]["GLD"] == 10.0 and tr.context["profile_id"] == "robert"


def test_compare_without_portfolio_b_is_reported_and_answer_withheld(real_service):
    ag = GuardianAgent(real_service, SessionContext(NVDA40, "robert"), Tracer(),
                       model_factory=lambda: StepModel([("tools", [CMP]), ("text", "A est meilleur : 22,3 % contre 6,9 %.")]))
    tr = ag.ask("Compare A et B.")
    assert tr.withheld and tr.text is None and "portefeuille B" in tr.withheld_reason
    assert tr.tool_records[0].status == "error"


# ------------------------------------------------------------------ 13. aucune réutilisation, contexte reconstruit à chaque requête
def test_context_changes_between_requests_are_used_and_never_stale(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    ctx = SessionContext(NVDA40, "robert", weights_b=prudent)
    model = StepModel([("tools", [EV]), ("text", "ok"), ("tools", [EV]), ("text", "ok")])
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model)
    t1 = ag.ask("Q1")
    ctx.weights = {"NVDA": .10, "XBB.TO": .55, "XIU.TO": .35}                              # l'utilisateur modifie le portefeuille A
    ctx.profile_id = "amira"
    t2 = ag.ask("Q2")
    assert t1.tool_records[0].result["weights_pct"]["NVDA"] == 40.0
    assert t2.tool_records[0].result["weights_pct"]["NVDA"] == 10.0 and t2.tool_records[0].turn == 2
    assert t1.context["weights_a_pct"]["NVDA"] == 40.0 and t2.context["weights_a_pct"]["NVDA"] == 10.0 and t2.context["profile_id"] == "amira"
    assert model.seen[2] == [["text"]]                                                     # aucune mémoire de la requête 1


def test_old_comparison_results_cannot_validate_a_new_request(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    ctx = SessionContext(NVDA40, "robert", weights_b=prudent)
    ag = GuardianAgent(real_service, ctx, Tracer(),
                       model_factory=lambda: StepModel([("tools", [CMP]), ("text", "Compromis."), ("text", "La volatilité de A est de 22,3 %.")]))
    assert not ag.ask("Q1").withheld
    t2 = ag.ask("Q2")
    assert t2.tool_records == [] and t2.withheld and t2.text is None


def test_parallel_v1_tools_do_not_mix_traces(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    for _ in range(10):
        ctx = SessionContext(NVDA40, "robert", weights_b=prudent)
        ag = GuardianAgent(real_service, ctx, Tracer(),
                           model_factory=lambda: StepModel([("tools", [GP, EV, CK, CMP]), ("text", "Interprétation.")]))
        tr = ag.ask("q")
        assert sorted(r.tool for r in tr.tool_records) == sorted([GP, EV, CK, CMP])
        assert len({r.id for r in tr.tool_records}) == 4 and {r.turn for r in tr.tool_records} == {1} and not tr.withheld


def test_failure_of_a_v1_tool_withholds_the_answer(real_service):
    ctx = SessionContext(NVDA40, "robert", weights_b=NVDA40, fail_tools={GP})
    ag = GuardianAgent(real_service, ctx, Tracer(),
                       model_factory=lambda: StepModel([("tools", [GP, EV]), ("text", "La volatilité est de 12,3 %.")]))
    tr = ag.ask("q")
    assert tr.withheld and tr.text is None and {r.tool: r.status for r in tr.tool_records} == {GP: "error", EV: "ok"}


# ------------------------------------------------------------------ langage
def test_system_prompt_enforces_prudent_wording():
    from guardian.agent.agent import SYSTEM_PROMPT
    for needle in ("conflit potentiel", "seuils heuristiques du prototype", "Faits historiques", "Interprétation",
                   "tolérance personnelle réelle", "meilleur", "get_profile", "compare_scenarios"):
        assert needle in SYSTEM_PROMPT


def test_prompt_context_note_reflects_selection_without_leaking_weights(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    ag = GuardianAgent(real_service, SessionContext(NVDA40, "amira", weights_b=prudent), Tracer(), model_factory=lambda: StepModel([("text", "x")]))
    p = ag.compose_prompt("Ma question ?")
    assert "Profil actif : amira (Amira)" in p and "Portefeuille B : défini" in p and "compare_scenarios est disponible" in p and p.endswith("Ma question ?")
    assert "40" not in p and "NVDA" not in p                                              # aucun poids ni actif transmis dans la note
    ag.ctx.weights_b = None
    assert "Portefeuille B : non défini" in ag.compose_prompt("q")
    tr = ag.ask("Ma question ?")
    assert tr.question == "Ma question ?"                                                # la question affichée reste celle de l'utilisateur


# ------------------------------------------------------------------ faits du persona : aucun horizon inventé
@pytest.mark.parametrize("text,bad", [
    ("Robert a un horizon de 3 à 5 ans.", []),
    ("Horizon : 3-5 ans pour Robert, 15 ans ou plus pour Amira.", []),
    ("Robert est un investisseur à horizon moyen (5-10 ans).", ["5 à 10 ans"]),
    ("Amira investit sur 10 ans ou plus.", ["10 ans ou plus"]),
    ("Fenêtre historique de cinq ans, 2021 à 2026.", []),
])
def test_unsupported_horizons_detection(real_service, text, bad):
    from guardian.agent.agent import unsupported_horizons
    assert unsupported_horizons(text, real_service.profiles) == bad


def test_answer_with_invented_persona_horizon_is_withheld(real_service):
    ctx = SessionContext(NVDA40, "robert")
    model = StepModel([("tools", [EV]), ("text", "Robert est à horizon moyen (5-10 ans) ; le portefeuille a une volatilité de 22,3 %.")])
    tr = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model).ask("q")
    assert tr.withheld and tr.text is None and "5 à 10 ans" in tr.withheld_reason and tr.tool_records[0].status == "ok"
    ok = StepModel([("tools", [EV]), ("text", "Robert a un horizon de 3 à 5 ans ; volatilité de 22,3 %.")])
    assert not GuardianAgent(real_service, SessionContext(NVDA40, "robert"), Tracer(), model_factory=lambda: ok).ask("q").withheld
