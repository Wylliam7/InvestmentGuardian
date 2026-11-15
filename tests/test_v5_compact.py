"""Fidélité de la vue compacte (expérience V5) : elle doit sélectionner et réorganiser les résultats des moteurs, sans rien inventer
ni transformer. Ces tests contrôlent les DONNÉES transmises au modèle, pas une formulation de Nova."""
import json

import pytest
from conftest import StepModel

from guardian.agent.tools import LINE_TYPES, SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.agent_v5.agent import AgentV5
from guardian.agent_v5.compact import compact
from guardian.finance.presets import load_presets

P = load_presets()
W = {k: {t: v / 100 for t, v in P[k]["weights_pct"].items()} for k in P}
PROFILES = ("amira", "robert", "mateo")
PERIODS = [("", ""), ("2022-01-01", "2022-12-31"), ("2024-01-01", "")]
PAIRS = [("robert_nvda_40", "robert_prudent", "robert"), ("amira_tech_crypto", "amira_croissance", "amira"),
         ("mateo_actions_canadiennes", "mateo_croissance_equilibree", "mateo")]
EV, CK, CMP, ESG, GP = "evaluate_portfolio", "check_profile_constraints", "compare_scenarios", "check_esg_preferences", "get_profile"


def tools(service, preset, pid, preset_b=None):
    return {t.tool_spec["name"]: t for t in build_tools(service, SessionContext(W[preset], pid, weights_b=W[preset_b] if preset_b else None), Tracer())}


def leaves(obj, strings: set, numbers: set):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, str):
        strings.add(obj)
    elif isinstance(obj, (int, float)):
        numbers.add(round(float(obj), 6))
    elif isinstance(obj, dict):
        for v in obj.values():
            leaves(v, strings, numbers)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            leaves(v, strings, numbers)


def assert_nothing_invented(original: dict, view: dict):
    """Toute valeur de la vue existe dans le résultat d'origine. Exceptions documentées : libellés LINE_TYPES et nombre de lignes."""
    so, no, sv, nv = set(), set(), set(), set()
    leaves(original, so, no)
    leaves(view, sv, nv)
    allowed_strings = so | set(LINE_TYPES.values())
    assert sv - allowed_strings == set(), sorted(sv - allowed_strings)[:5]
    n_lines = {float(len((b or {}).get("weights_pct") or {})) for b in (original, original.get("portfolio_A"), original.get("portfolio_B"))}
    assert nv - no - n_lines == set(), sorted(nv - no - n_lines)[:5]


def size(o) -> int:
    return len(json.dumps(o, ensure_ascii=False))


# ---------------------------------------------------------------- aucune valeur inventée, pour tous les outils, profils, portefeuilles, périodes
@pytest.mark.parametrize("preset", sorted(P))
@pytest.mark.parametrize("pid", PROFILES)
def test_no_value_is_invented_for_any_tool(real_service, preset, pid):
    t = tools(real_service, preset, pid)
    for name, kwargs in ((EV, {}), (CK, {}), (ESG, {}), (GP, {})):
        orig = t[name](**kwargs)
        assert_nothing_invented(orig, compact(name, orig))


@pytest.mark.parametrize("start,end", PERIODS)
def test_periods_and_dates_are_preserved(real_service, start, end):
    t = tools(real_service, "amira_tech_crypto", "amira")
    ev, ck = t[EV](start_date=start, end_date=end), t[CK](start_date=start, end_date=end)
    cev, cck = compact(EV, ev), compact(CK, ck)
    assert cev["window"]["start"] == ev["window"]["start"] and cev["window"]["end"] == ev["window"]["end"]
    assert cck["window"]["start"] == ck["window"]["start"] and cck["window"]["end"] == ck["window"]["end"]
    for k in ("max_drawdown_peak_date", "max_drawdown_trough_date", "max_drawdown_recovered"):
        assert cev["metrics"][k] == ev["metrics"][k]
    r5 = next(c for c in cck["criteria"] if c["rule_id"] == "R5")
    assert r5["evidence"]["peak_date"] == ev["metrics"]["max_drawdown_peak_date"]
    assert_nothing_invented(ev, cev)
    assert_nothing_invented(ck, cck)


# ---------------------------------------------------------------- statuts Guardian : tous présents, aucun transformé
@pytest.mark.parametrize("preset", sorted(P))
@pytest.mark.parametrize("pid", PROFILES)
def test_every_guardian_status_measure_and_reference_is_preserved(real_service, preset, pid):
    ck = tools(real_service, preset, pid)[CK]()
    c = compact(CK, ck)
    assert c["counts"] == ck["counts"] and c["profile_id"] == ck["profile_id"] == pid
    assert len(c["criteria"]) == len(ck["findings"])
    for f, x in zip(ck["findings"], c["criteria"]):
        d = f["display"]
        assert x["rule_id"] == f["rule_id"] and x["status"] == f["status_label"]
        assert x.get("measured") == (d.get("measured") or None)
        assert x.get("attention") == (d.get("attention") or None) and x.get("conflict") == (d.get("conflict") or None)
        assert x["limitations"] == f["limitations"]
    assert c["general_limitations"] == ck["general_limitations"] and c["missing_information"] == ck["missing_information"]


# ---------------------------------------------------------------- lignes, FNB, métriques
@pytest.mark.parametrize("preset", sorted(P))
def test_lines_types_funds_and_metrics_are_preserved(real_service, preset):
    ev = tools(real_service, preset, "amira")[EV]()
    c = compact(EV, ev)
    assert {x["ticker"]: x["weight_pct"] for x in c["lines"]} == ev["weights_pct"] and c["n_lines"] == len(ev["weights_pct"])
    cls = {a["ticker"]: a["asset_class"] for a in ev["assets"]}
    for x in c["lines"]:
        assert x["type"] == LINE_TYPES[cls[x["ticker"]]]                   # une action n'est jamais présentée comme FNB, ni l'inverse
    fx = ev["fund_exposure"]
    if fx["has_funds"]:
        assert [f["ticker"] for f in c["funds"]["fund_lines"]] == [f["ticker"] for f in fx["fund_lines"]]
        assert c["funds"]["underlying_diversification_measured"] is False and c["funds"]["note"] == fx["pedagogical_note"]
    assert c["metrics"] == ev["metrics"] and c["asset_class_exposure_pct"] == ev["asset_class_exposure_pct"]
    assert c["provenance"]["limitations"] == ev["provenance"]["limitations"]


def test_technology_share_and_its_limit_are_preserved_for_amira(real_service):
    ev = tools(real_service, "amira_tech_crypto", "amira")[EV]()
    assert compact(EV, ev)["technology"] == ev["key_facts"]["technology"]


# ---------------------------------------------------------------- comparaison A/B : aucun mélange
@pytest.mark.parametrize("a,b,pid", PAIRS)
def test_ab_results_are_not_mixed(real_service, a, b, pid):
    cmp_ = tools(real_service, a, pid, b)[CMP]()
    c = compact(CMP, cmp_)
    for side in ("A", "B"):
        assert {x["ticker"]: x["weight_pct"] for x in c[f"portfolio_{side}"]["lines"]} == cmp_[f"portfolio_{side}"]["weights_pct"]
        assert c[f"portfolio_{side}"]["metrics"] == cmp_[f"portfolio_{side}"]["metrics"]
        assert [(x["rule_id"], x["status"]) for x in c[f"guardian_{side}"]["criteria"]] == \
               [(f["rule_id"], f["status_label"]) for f in cmp_[f"guardian_{side}"]["findings"]]
        assert c[f"guardian_{side}"]["counts"] == cmp_[f"guardian_{side}"]["counts"]
    assert c["differences_B_minus_A"] == cmp_["differences_B_minus_A"] and c["historical_tradeoffs"] == cmp_["historical_tradeoffs"]
    assert c["no_winner_notice"] == cmp_["no_winner_notice"]
    assert_nothing_invented(cmp_, c)


# ---------------------------------------------------------------- ESG : exclusions, observations, couverture, limites
@pytest.mark.parametrize("preset", ["mateo_actions_canadiennes", "mateo_croissance_equilibree"])
def test_esg_categories_decisions_coverage_and_limits_are_preserved(real_service, preset):
    esg = tools(real_service, preset, "mateo")[ESG]()
    c = compact(ESG, esg)
    key = lambda cats: sorted((r["ticker"], cat["decision_label"], cat["dimension_label"], r["published"], r["criterion_fr"])  # noqa: E731
                              for cat in cats for r in cat["records"])
    ckey = lambda cats: sorted((r["ticker"], cat["decision"], cat["dimension"], r["published"], r["criterion"]) for cat in cats for r in cat["records"])  # noqa: E731
    assert ckey(c.get("documented_categories", [])) == key(esg["documented_categories"])
    assert ckey(c.get("complementary_information", [])) == key(esg["complementary_information"])
    doc_t = {t for cat in c.get("documented_categories", []) for t in cat["tickers"]}
    comp_t = {t for cat in c.get("complementary_information", []) for t in cat["tickers"]}
    assert not doc_t & comp_t                                               # une observation n'est jamais rangée avec les exclusions liées à la préférence
    assert c["coverage"] == esg["coverage"] and c["overall_state"] == esg["overall_label"]
    assert {x["ticker"]: x["state"] for x in c["lines"]} == {x["ticker"]: x["state_label"] for x in esg["lines"]}
    assert c["uncertainties"] == esg["uncertainties"] and [s["limits"] for s in c["sources"]] == [s["limits"] for s in esg["sources"]]
    assert c["no_score_notice"] == esg["no_score_notice"] and c["data_nature"] == esg["data_nature"]


def test_esg_not_applicable_is_preserved(real_service):
    esg = tools(real_service, "amira_tech_crypto", "amira")[ESG]()
    c = compact(ESG, esg)
    assert c["applicable"] is False and c["uncertainties"] == esg["uncertainties"]


# ---------------------------------------------------------------- profils, erreurs, taille
def test_two_profiles_in_one_request_keep_their_own_statuses(real_service):
    t = {x.tool_spec["name"]: x for x in build_tools(real_service, SessionContext(W["amira_tech_crypto"], "amira", allowed_profiles={"amira", "robert"}), Tracer())}
    ca, cr = compact(CK, t[CK](profile_id="amira")), compact(CK, t[CK](profile_id="robert"))
    assert ca["profile_id"] == "amira" and cr["profile_id"] == "robert"
    assert {x["rule_id"]: x["status"] for x in ca["criteria"]}["R1"] == "Attention"
    assert {x["rule_id"]: x["status"] for x in cr["criteria"]}["R1"] == "Conflit"


def test_errors_are_passed_through_unchanged():
    err = {"status": "error", "tool": CMP, "message": "Aucun portefeuille B", "instruction": "x"}
    assert compact(CMP, err) is err


@pytest.mark.parametrize("name,kwargs,limit", [(EV, {}, 0.80), (CK, {}, 0.55), (ESG, {}, 0.60)])
def test_compact_views_are_smaller(real_service, name, kwargs, limit):
    pid = "mateo" if name == ESG else "amira"
    preset = "mateo_actions_canadiennes" if name == ESG else "amira_tech_crypto"
    orig = tools(real_service, preset, pid)[name](**kwargs)
    assert size(compact(name, orig)) < limit * size(orig)


# ---------------------------------------------------------------- intégration : le modèle reçoit la vue compacte, la trace garde l'original
def test_model_receives_the_compact_view_and_the_trace_keeps_the_original(real_service):
    model = StepModel([("tools", [CK]), ("text", "Réponse.")])
    ag = AgentV5(real_service, SessionContext(dict(W["amira_tech_crypto"]), "amira"), model_factory=lambda: model, compact=True)
    r = ag.ask("Quels sont mes risques ?")
    call = r.calls[0]
    assert call.compacted and call.result["findings"] and "findings" not in call.model_view
    sent = [json.loads(b["toolResult"]["content"][0]["text"]) for m in r.messages for b in m["content"] if "toolResult" in b]
    assert sent == [call.model_view] and r.provenance_ok


def test_compact_is_off_by_default(real_service, monkeypatch):
    monkeypatch.delenv("GUARDIAN_V5_COMPACT", raising=False)
    model = StepModel([("tools", [CK]), ("text", "Réponse.")])
    r = AgentV5(real_service, SessionContext(dict(W["amira_tech_crypto"]), "amira"), model_factory=lambda: model).ask("Quels sont mes risques ?")
    sent = [json.loads(b["toolResult"]["content"][0]["text"]) for m in r.messages for b in m["content"] if "toolResult" in b]
    assert not r.calls[0].compacted and sent == [r.calls[0].result]
