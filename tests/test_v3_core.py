"""V3 — Mateo (profil, seuils financiers), module ESG déterministe, outil check_esg_preferences, agent.

Les données ESG de ces tests sont FICTIVES (source « TEST-FICTIF », domaine example.invalid) : elles ne sont jamais chargées par l'application
et ne représentent aucune controverse réelle. Les données réelles sont dans config/esg_sources.yaml et testées séparément.
"""
import copy
import json
import re

import pytest
import yaml

from conftest import REPO, StepModel
from guardian.agent.agent import GuardianAgent, asks_about_esg, explain_risks_task
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.esg.data import EsgDataError, empty_esg_data, load_esg_data, parse_esg_data
from guardian.esg.engine import (COMPLEMENTARY, DOCUMENTED, INSUFFICIENT, NONE_FOUND, NOT_APPLICABLE, STATE_LABELS, evaluate_esg)
from guardian.explain.esg_view import build_esg_view
from guardian.finance.presets import load_presets
from guardian.rules.engine import ATTENTION, CONFLIT, OK, load_profiles, load_rules_config

PRESETS = load_presets()
MATEO_A = {t: v / 100 for t, v in PRESETS["mateo_croissance_equilibree"]["weights_pct"].items()}
MATEO_B = {t: v / 100 for t, v in PRESETS["mateo_actions_canadiennes"]["weights_pct"].items()}
EV, CK, GP, CMP, ESG = "evaluate_portfolio", "check_profile_constraints", "get_profile", "compare_scenarios", "check_esg_preferences"
STATES = {DOCUMENTED, NONE_FOUND, INSUFFICIENT, NOT_APPLICABLE}


def fictional_esg(checked=("MSFT", "JNJ", "PG"), documented=(), not_applicable=None, fund=None):
    """Données FICTIVES : la source n'existe pas ; les enregistrements documentés sont des exemples de test, jamais réels."""
    raw = {"version": "TEST-FICTIF", "retrieved_on": "2000-01-01",
           "sources": {"TEST-FICTIF": {"publisher": "Source fictive de test", "title": "Données FICTIVES pour tests unitaires", "url": "https://example.invalid/test-fictif",
                                       "consulted_on": "2000-01-01", "nature": "Aucune valeur réelle.", "scope": "Tests uniquement.", "limits": ["Fictif."], "terms": "Aucune."}},
           "records": [{"ticker": t, "source": "TEST-FICTIF", "company_name_in_source": "SOCIÉTÉ FICTIVE", "category": "Test", "criterion_fr": "critère fictif",
                        "decision": "exclusion", "published": "2000-01-01", "dimension": "E", "relevance": "direct"} for t in documented],
           "checks": [{"source": "TEST-FICTIF", "checked_on": "2000-01-01", "checked_tickers": sorted(set(checked) | set(documented))}],
           "fund_level": fund or [], "not_applicable": not_applicable or {}}
    return raw


# ============================================================ 1-3. profil Mateo conforme au case officiel
OFFICIAL = {  # Datathon - Case Officiel 2026 FR.pdf, page 6 (relu directement dans le PDF)
    "age": 41, "occupation": "Gestionnaire des opérations", "experience": "Intermédiaire", "risk_profile_label": "Modéré",
    "horizon_years_min": 8, "horizon_years_max": 12, "objective": "Faire croître son capital de façon équilibrée à moyen et à long terme.",
    "situation": "En couple, père de deux enfants.",
    "preferences": ["Accorde une grande importance aux facteurs ESG.",
                    "Souhaite éviter les entreprises liées à des controverses environnementales ou sociales importantes.",
                    "Recherche un équilibre entre potentiel de croissance et stabilité.",
                    "Ouvert aux technologies émergentes si elles correspondent à son profil de risque.",
                    "Peu intéressé par les placements hautement spéculatifs."],
}


def test_mateo_profile_matches_the_official_case():
    m = load_profiles()["mateo"]
    for k, v in OFFICIAL.items():
        assert m[k] == v, k
    assert m["display_name"] == "Mateo" and "p. 6" in m["source"]
    esg = m["esg_preferences"]
    assert esg["importance"] == OFFICIAL["preferences"][0]
    assert [c["official_wording"] for c in esg["criteria"]] == [OFFICIAL["preferences"][1]]
    assert esg["criteria"][0]["direct_dimensions"] == ["E", "S"] and esg["criteria"][0]["indirect_dimensions"] == ["G"]


def test_mateo_wording_is_checked_against_the_pdf_when_available():
    pypdf = pytest.importorskip("pypdf")
    pdf = REPO / "Datathon2026" / "Datathon - Case Officiel 2026 FR.pdf"
    if not pdf.exists():
        pytest.skip("PDF officiel absent (non publié)")
    text = " ".join((pypdf.PdfReader(str(pdf)).pages[5].extract_text() or "").split())
    for s in (OFFICIAL["objective"], *OFFICIAL["preferences"][:2], "8 à 12 ans", "Modéré", "41 ans", "Gestionnaire des opérations"):
        assert " ".join(s.split()) in text, s


def test_mateo_selectable_and_other_profiles_untouched():
    profiles = load_profiles()
    assert list(profiles) == ["robert", "amira", "mateo"]
    assert "esg_preferences" not in profiles["robert"] and "esg_preferences" not in profiles["amira"]


def test_mateo_presets_are_valid_exact_and_use_official_assets(real_service):
    for pid in ("mateo_croissance_equilibree", "mateo_actions_canadiennes"):
        w = PRESETS[pid]["weights_pct"]
        assert PRESETS[pid]["profile_id"] == "mateo" and sum(w.values()) == 100 and all(isinstance(v, int) and v > 0 for v in w.values())
        assert set(w) <= set(real_service.bundle.universe.index)
    assert PRESETS["mateo_croissance_equilibree"]["label"] == "Mateo — Croissance équilibrée, ESG à vérifier"
    assert not any(c in MATEO_A for c in ("BTC-USD", "ETH-USD"))                         # peu intéressé par les placements hautement spéculatifs
    assert PRESETS["mateo_croissance_equilibree"]["weights_pct"] == {"XIU.TO": 20, "SPY": 20, "QQQ": 10, "XBB.TO": 20, "AGG": 10, "MSFT": 5, "JNJ": 5, "PG": 5, "GLD": 5}
    for pid in ("mateo_croissance_equilibree", "mateo_actions_canadiennes"):
        desc = PRESETS[pid]["description"].lower()
        assert "durable" not in desc and "conforme esg" not in desc and "vert" not in desc.split()   # aucune qualification ESG non établie
        assert "à vérifier" in PRESETS[pid]["label"].lower() or "voir « mes préférences esg »" in desc


def test_existing_presets_are_unchanged():
    p = {k: v["weights_pct"] for k, v in PRESETS.items()}
    assert p["robert_nvda_40"] == {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25}
    assert p["amira_tech_crypto"] == {"NVDA": 25, "TSLA": 15, "QQQ": 25, "SHOP.TO": 5, "BTC-USD": 20, "ETH-USD": 10}
    assert p["amira_croissance"] == {"QQQ": 20, "SPY": 20, "XIU.TO": 15, "NVDA": 10, "SHOP.TO": 5, "BTC-USD": 5, "XBB.TO": 10, "RY.TO": 5, "JNJ": 5, "XOM": 5}


# ============================================================ 4. mêmes métriques pour les trois personas
@pytest.mark.parametrize("w", [MATEO_A, MATEO_B, {"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}])
def test_same_portfolio_gives_identical_financial_metrics_for_the_three_personas(real_service, w):
    results = {p: real_service.check(w, p) for p in ("robert", "amira", "mateo")}
    dicts = {p: r[0].to_tool_dict() for p, r in results.items()}
    assert dicts["robert"] == dicts["amira"] == dicts["mateo"]                           # rendements, volatilités, drawdowns identiques
    for rid in ("R1", "R2", "R4", "R5", "R7"):
        assert len({results[p][1].by_id()[rid].measured for p in results}) == 1           # mêmes mesures de règles
    assert len({tuple(f.status for f in results[p][1].findings) for p in results}) >= 2    # seules les interprétations diffèrent


# ============================================================ 5-6. seuils financiers de Mateo
def _midpoint_rounded(robert, amira, step):
    """Milieu arithmétique de Robert et d'Amira, arrondi au multiple de `step` le plus proche, au supérieur à égalité. Tout en décimal exact
    (en flottants, 0,10 + 0,35 donne 0,44999… et fausserait l'arrondi)."""
    from decimal import ROUND_HALF_UP, Decimal
    mid = (Decimal(str(robert)) + Decimal(str(amira))) / 2
    return float((mid / Decimal(str(step))).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(str(step)))


def test_mateo_thresholds_are_the_documented_mechanical_midpoint_of_robert_and_amira():
    cfg = load_rules_config()["rules"]
    for rid in ("R1", "R2", "R4", "R5"):
        for key in ("attention", "conflict"):
            r, a = cfg[rid]["thresholds"]["robert"][key], cfg[rid]["thresholds"]["amira"][key]
            assert cfg[rid]["thresholds"]["mateo"][key] == pytest.approx(_midpoint_rounded(r, a, 0.05)), (rid, key)
    for key in ("attention", "conflict"):
        r, a = cfg["R7"]["thresholds"]["robert"][key], cfg["R7"]["thresholds"]["amira"][key]
        assert cfg["R7"]["thresholds"]["mateo"][key] == pytest.approx(_midpoint_rounded(r, a, 0.5))
    for rid in ("R1", "R2", "R4", "R5", "R7"):                                           # Mateo reste entre Robert et Amira
        t = {p: cfg[rid]["thresholds"][p] for p in ("robert", "mateo", "amira")}
        lo, hi = sorted((t["robert"]["conflict"], t["amira"]["conflict"]))
        assert lo <= t["mateo"]["conflict"] <= hi, rid


def test_mateo_financial_diagnostics_use_mateo_thresholds_and_stay_deterministic(real_service):
    res, rep = real_service.check({"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}, "mateo")
    f = rep.by_id()
    assert f["R1"].status == CONFLIT and (f["R1"].threshold_attention, f["R1"].threshold_conflict) == (0.15, 0.30)
    assert f["R7"].direction == "min" and f["R7"].measured == pytest.approx(1 / 0.345)
    assert f["R7"].status == CONFLIT and (f["R7"].threshold_attention, f["R7"].threshold_conflict) == (5.5, 3.5)        # 2,9 < 3,5
    assert real_service.check({"NVDA": .4, "XBB.TO": .35, "XIU.TO": .25}, "mateo")[1].counts() == rep.counts()


def test_robert_and_amira_thresholds_are_exactly_the_v1_values():
    cfg = load_rules_config()["rules"]
    expected = {"R1": ((0.10, 0.20), (0.20, 0.35)), "R2": ((0.10, 0.20), (0.35, 0.50)), "R4": ((0.10, 0.14), (0.25, 0.35)),
                "R5": ((0.15, 0.25), (0.40, 0.55)), "R7": ((6, 4), (5, 3))}
    for rid, (rob, ami) in expected.items():
        t = cfg[rid]["thresholds"]
        assert (t["robert"]["attention"], t["robert"]["conflict"]) == rob and (t["amira"]["attention"], t["amira"]["conflict"]) == ami


# ============================================================ 7-12. module ESG déterministe
def test_missing_esg_data_never_becomes_compliant(real_service):
    rep = evaluate_esg(MATEO_A, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], empty_esg_data())
    assert rep.overall_state == INSUFFICIENT and rep.coverage_checked == 0.0
    states = {a.ticker: a.state for a in rep.lines}
    assert set(states.values()) == {INSUFFICIENT} and rep.weights_by_state[NONE_FOUND] == 0 and rep.weights_by_state[DOCUMENTED] == 0
    assert rep.overall_label == "Information insuffisante" and sum(rep.weights_by_state.values()) == pytest.approx(1.0)


def test_partial_coverage_is_shown_and_the_rest_is_not_presented_as_compliant(real_service):
    w = {"MSFT": .15, "JNJ": .15, "SPY": .40, "XBB.TO": .30}                              # 30 % cherché, 70 % non évaluable
    esg = parse_esg_data(fictional_esg(checked=("MSFT", "JNJ")), real_service.bundle.universe.index)
    rep = evaluate_esg(w, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert rep.coverage_checked == pytest.approx(0.30) and rep.coverage_of_applicable == pytest.approx(0.30)
    assert rep.weights_by_state[INSUFFICIENT] == pytest.approx(0.70) and rep.overall_state == INSUFFICIENT
    view = build_esg_view(rep, real_service.bundle.universe)
    assert "30 % de votre portefeuille a pu être cherché" in view["coverage_summary"] and "70 % ne peut pas être évalué" in view["coverage_summary"]
    assert "ne sont pas présentées comme conformes" in view["coverage_summary"]
    assert {a.state_label for a in rep.lines} <= set(STATE_LABELS.values()) and not any("conforme" in a.state_label.lower() for a in rep.lines)


def test_documented_controversy_is_distinct_from_insufficient_information(real_service):
    esg = parse_esg_data(fictional_esg(checked=("MSFT",), documented=("JNJ",)), real_service.bundle.universe.index)
    w = {"MSFT": .2, "JNJ": .2, "SPY": .6}
    rep = evaluate_esg(w, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    s = {a.ticker: a.state for a in rep.lines}
    assert s == {"SPY": INSUFFICIENT, "MSFT": NONE_FOUND, "JNJ": DOCUMENTED}
    assert rep.overall_state == DOCUMENTED and rep.overall_label == "Controverse documentée à examiner"          # priorité à l'information documentée
    only_unknown = evaluate_esg({"SPY": 1.0}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert only_unknown.overall_state == INSUFFICIENT and only_unknown.overall_state != rep.overall_state
    rec = next(a for a in rep.lines if a.ticker == "JNJ").records[0]
    assert rec["source"] == "TEST-FICTIF" and rec["company_name_in_source"] == "SOCIÉTÉ FICTIVE"


def test_none_identified_requires_every_applicable_line_to_be_checked(real_service):
    esg = parse_esg_data(fictional_esg(checked=("MSFT", "JNJ"), not_applicable={"GLD": "Fonds adossé à de l'or : sans entreprise émettrice."}),
                         real_service.bundle.universe.index)
    full = evaluate_esg({"MSFT": .5, "JNJ": .4, "GLD": .1}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert full.overall_state == NONE_FOUND and full.overall_label == "Aucune controverse identifiée dans les sources consultées"
    assert full.coverage_of_applicable == pytest.approx(1.0) and full.weights_by_state[NOT_APPLICABLE] == pytest.approx(0.1)
    assert "Cela ne prouve pas" in next(a for a in full.lines if a.ticker == "MSFT").reason
    mixed = evaluate_esg({"MSFT": .5, "JNJ": .3, "SPY": .1, "GLD": .1}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert mixed.overall_state == INSUFFICIENT                                           # une seule ligne non évaluable suffit à empêcher « aucune controverse »
    only_na = evaluate_esg({"GLD": 1.0}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert only_na.overall_state == NOT_APPLICABLE and only_na.coverage_of_applicable is None


def test_not_applicable_requires_a_written_justification(real_service):
    with pytest.raises(EsgDataError, match="justification"):
        parse_esg_data(fictional_esg(not_applicable={"GLD": "  "}), real_service.bundle.universe.index)
    esg = parse_esg_data(fictional_esg(not_applicable={"GLD": "Justification de test."}), real_service.bundle.universe.index)
    rep = evaluate_esg({"GLD": .5, "SPY": .5}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], esg)
    assert next(a for a in rep.lines if a.ticker == "GLD").reason == "Justification de test."


def test_no_esg_score_or_rating_exists_anywhere(real_service):
    rep = real_service.check_esg(MATEO_B, "mateo")
    blob = json.dumps(rep.to_dict(), ensure_ascii=False).lower()
    keys = set(re.findall(r'"([a-z_]+)":', blob))
    assert not [k for k in keys if "score" in k and k != "no_score_notice"] and not [k for k in keys if k in ("rating", "grade", "esg_score", "note_esg")]
    view = build_esg_view(rep, real_service.bundle.universe)
    assert "score" not in json.dumps({k: v for k, v in view.items() if k != "no_score_notice"}, ensure_ascii=False, default=str).lower()
    assert "aucun score" in view["no_score_notice"].lower()
    raw = yaml.safe_load((REPO / "config" / "esg_sources.yaml").read_text(encoding="utf-8"))
    assert not [k for k in re.findall(r"^\s*([a-z_]+):", (REPO / "config" / "esg_sources.yaml").read_text(encoding="utf-8"), re.M) if "score" in k or "rating" in k]
    assert set(raw) == {"version", "retrieved_on", "sources", "records", "checks", "fund_level", "not_applicable"}


def test_etf_lines_are_not_decomposed_and_underlying_exposure_is_unknown(real_service):
    rep = real_service.check_esg(MATEO_A, "mateo")
    etfs = {a.ticker: a for a in rep.lines if a.line_type == "FNB"}
    assert set(etfs) == {"XIU.TO", "SPY", "QQQ", "XBB.TO", "AGG"} and all(a.state == INSUFFICIENT for a in etfs.values())
    assert rep.underlying["status"] == "composition_non_disponible" and rep.underlying["etf_weight_pct"] == 80.0
    assert rep.underlying["direct_company_weight_pct"] == 15.0
    assert "n'est donc pas connue et n'est pas estimée" in rep.underlying["explanation"]
    view = build_esg_view(rep, real_service.bundle.universe)["line_vs_underlying"]
    assert "15 % du portefeuille est investi directement dans des actions" in view["line"] and "80 % est détenu via des FNB" in view["line"]
    none = evaluate_esg({"MSFT": 1.0}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], parse_esg_data(fictional_esg(checked=("MSFT",)), None))
    assert none.underlying["status"] == "aucun_fnb"


def test_esgv_fund_level_information_is_not_a_verification_of_its_holdings(real_service):
    rep = real_service.check_esg({"ESGV": .5, "SPY": .5}, "mateo")
    esgv = next(a for a in rep.lines if a.ticker == "ESGV")
    assert esgv.state == INSUFFICIENT and esgv.fund_note and "L'émetteur indique" in esgv.fund_note
    assert "vanguard_esgv_profile" in esgv.source_ids and any(s["id"] == "vanguard_esgv_profile" for s in rep.sources)
    src = next(s for s in rep.sources if s["id"] == "vanguard_esgv_profile")
    assert any("pas d'une vérification des positions" in lim for lim in src["limits"])
    assert next(a for a in rep.lines if a.ticker == "SPY").fund_note is None
    assert rep.overall_state == INSUFFICIENT and rep.coverage_checked == 0


def test_profiles_without_declared_esg_preferences_are_not_concerned(real_service):
    for pid in ("robert", "amira"):
        rep = real_service.check_esg(MATEO_B, pid)
        assert rep.applicable is False and rep.overall_state is None and rep.lines == ()
        assert "n'a pas déclaré de préférences ESG" in rep.uncertainties[0]
        assert build_esg_view(rep, real_service.bundle.universe) == {"applicable": False, "message": rep.uncertainties[0]}


# ============================================================ données ESG de production : provenance et contenu exact
def test_production_esg_data_is_traceable_and_contains_only_documented_facts(real_service):
    esg = load_esg_data(universe_tickers=real_service.bundle.universe.index)
    assert set(esg.sources) == {"nbim_exclusion_list", "vanguard_esgv_profile"}
    for sid, s in esg.sources.items():
        assert s["url"].startswith("https://") and str(s["consulted_on"]) == "2026-11-14" and s["limits"] and s["terms"] and s["publisher"] and s["scope"]
    assert "n'ont pas été examinées en détail" in " ".join(esg.sources["nbim_exclusion_list"]["terms"].split())
    recs = {r["ticker"]: r for r in esg.records}
    assert set(recs) == {"CNQ.TO", "TD.TO"}
    assert (recs["CNQ.TO"]["decision"], recs["CNQ.TO"]["published"], recs["CNQ.TO"]["criterion_en"], recs["CNQ.TO"]["dimension"]) == (
        "exclusion", "2020-05-13", "Unacceptable greenhouse gas emissions", "E")
    assert (recs["TD.TO"]["decision"], recs["TD.TO"]["published"], recs["TD.TO"]["criterion_en"], recs["TD.TO"]["dimension"], recs["TD.TO"]["relevance"]) == (
        "observation", "2025-06-11", "Gross corruption or other serious financial crime", "G", "indirect")
    stocks = sorted(real_service.bundle.universe.index[real_service.bundle.universe["asset_class"] == "equity"])
    assert sorted(t for t, ids in esg.checked.items() if "nbim_exclusion_list" in ids) == stocks and len(stocks) == 20
    assert set(esg.not_applicable) == {"GLD", "BTC-USD", "ETH-USD", "TLT"} and all(len(v) > 40 for v in esg.not_applicable.values())
    assert set(esg.fund_level) == {"ESGV"}


def test_real_scenarios_for_mateo(real_service):
    a = real_service.check_esg(MATEO_A, "mateo")
    assert a.overall_state == INSUFFICIENT and a.coverage_checked == pytest.approx(0.15) and a.weights_by_state[INSUFFICIENT] == pytest.approx(0.80)
    assert a.weights_by_state[NOT_APPLICABLE] == pytest.approx(0.05) and {x.ticker: x.state for x in a.lines}["GLD"] == NOT_APPLICABLE
    b = real_service.check_esg(MATEO_B, "mateo")
    st = {x.ticker: x.state for x in b.lines}
    assert st["CNQ.TO"] == DOCUMENTED and st["TD.TO"] == COMPLEMENTARY and st["RY.TO"] == st["ENB.TO"] == st["CNR.TO"] == st["FTS.TO"] == NONE_FOUND and st["XBB.TO"] == INSUFFICIENT
    assert b.overall_state == DOCUMENTED and b.weights_by_state[DOCUMENTED] == pytest.approx(0.15) and b.weights_by_state[COMPLEMENTARY] == pytest.approx(0.15)
    view = build_esg_view(b, real_service.bundle.universe)
    texts = {c["ticker"]: c for c in view["controversies"] + view["complementary"]}
    assert [c["ticker"] for c in view["controversies"]] == ["CNQ.TO"] and [c["ticker"] for c in view["complementary"]] == ["TD.TO"]
    assert "a exclu Canadian Natural Resources de son fonds" in texts["CNQ.TO"]["headline"] and "13 mai 2020" in texts["CNQ.TO"]["headline"] and "dimension environnementale" in texts["CNQ.TO"]["link"]
    assert "a placé Toronto-Dominion Bank sous observation" in texts["TD.TO"]["headline"] and "11 juin 2025" in texts["TD.TO"]["headline"] and "gouvernance" in texts["TD.TO"]["link"]
    assert "ni un jugement de culpabilité ni une note ESG" in texts["CNQ.TO"]["caution"] and "moins forte qu'une exclusion" in texts["TD.TO"]["caution"]
    assert all("coupable" not in c["headline"].lower() and "corrompu" not in c["headline"].lower() for c in texts.values())


def test_esg_view_distinguishes_conflict_missing_information_and_absence(real_service):
    view = build_esg_view(real_service.check_esg(MATEO_A, "mateo"), real_service.bundle.universe)
    assert view["intro"] == ("Nous pouvons analyser les risques financiers de votre portefeuille. Toutefois, les données disponibles ne permettent pas encore "
                             "de vérifier l'ensemble de vos préférences ESG.")
    titles = [t for t, _ in view["distinctions"]]
    assert titles == ["Une exclusion documentée liée à la préférence", "Une mise sous observation de gouvernance", "Une information manquante", "Une absence de controverse identifiée"]
    assert any("Cela ne vaut pas preuve" in d for _, d in view["distinctions"])
    assert view["state_label"] == "Information insuffisante"


def test_invalid_esg_data_is_rejected(real_service):
    ok = fictional_esg()
    for mutate, msg in ((lambda r: r["sources"]["TEST-FICTIF"].pop("url"), "provenance incomplète"),
                        (lambda r: r["sources"]["TEST-FICTIF"].update(consulted_on="pas-une-date"), "date invalide"),
                        (lambda r: r["checks"][0].update(source="inconnue"), "source inconnue"),
                        (lambda r: r["checks"][0]["checked_tickers"].append("ZZZ"), "absent de l'univers")):
        bad = copy.deepcopy(ok)
        mutate(bad)
        with pytest.raises(EsgDataError, match=msg):
            parse_esg_data(bad, real_service.bundle.universe.index)
    doc = fictional_esg(documented=("JNJ",))
    doc["checks"][0]["checked_tickers"] = ["MSFT"]
    with pytest.raises(EsgDataError, match="sans vérification"):
        parse_esg_data(doc, real_service.bundle.universe.index)


# ============================================================ 13-17. outil, agent, isolation
def tools(service, ctx, tracer=None):
    tracer = tracer or Tracer()
    return {t.tool_spec["name"]: t for t in build_tools(service, ctx, tracer)}, tracer


def test_check_esg_preferences_tool_matches_the_module_and_records_sources(real_service):
    ctx = SessionContext(MATEO_B, "mateo", weights_b=MATEO_A)
    t, tracer = tools(real_service, ctx)
    out = t[ESG]()
    assert out["status"] == "ok" and out["applicable"] and out["profile_id"] == "mateo" and out["portfolio"] == "A"
    assert out["overall_state"] == DOCUMENTED and out["overall_label"] == "Controverse documentée à examiner"
    assert out["coverage"]["checked_in_sources_pct"] == 85.0 and out["coverage"]["weights_by_state_pct"]["Information insuffisante"] == 15.0
    assert out["declared_esg_preferences"][1] == OFFICIAL["preferences"][1]
    assert {s["id"] for s in out["sources"]} == {"nbim_exclusion_list"} and out["sources"][0]["url"].endswith("exclusion-of-companies")
    assert out["uncertainties"] and out["rules_applied"] and "Aucun score ESG" in out["no_score_notice"]
    b = t[ESG](portfolio="B")
    assert b["portfolio"] == "B" and b["overall_state"] == INSUFFICIENT
    rec = tracer.records[0]
    assert rec.status == "ok" and rec.arguments == {"profile_id": "", "portfolio": "A"} and rec.result_digest
    assert rec.data_refs["esg_sources"] == [{"id": "nbim_exclusion_list", "consulted_on": "2026-11-14", "url": out["sources"][0]["url"], "url_status": "verified"}]
    assert rec.data_refs["esg_data_version"] == "0.1-v3"


def test_check_esg_preferences_for_profile_without_esg_and_error_cases(real_service):
    ctx = SessionContext(MATEO_A, "robert")
    t, tracer = tools(real_service, ctx)
    out = t[ESG]()
    assert out["applicable"] is False and out["overall_state"] is None and "n'a pas déclaré de préférences ESG" in out["uncertainties"][0]
    err = t[ESG](portfolio="B")
    assert err["status"] == "error" and "portefeuille B" in err["message"]
    ctx.allowed_profiles = {"robert"}
    denied = t[ESG](profile_id="mateo")
    assert denied["status"] == "error" and "n'est pas autorisé" in denied["message"]
    assert [r.status for r in tracer.records] == ["ok", "error", "error"]


def test_get_profile_includes_mateo_and_his_esg_preferences(real_service):
    ctx = SessionContext(MATEO_A, "robert")
    t, _ = tools(real_service, ctx)
    out = t[GP](profile_id="mateo")
    assert out["profile"]["age"] == 41 and out["profile"]["horizon_years_min"] == 8 and out["profile"]["esg_preferences"]["importance"] == OFFICIAL["preferences"][0]
    assert out["heuristic_thresholds"]["R1"]["conflict"] == 0.30 and "mateo" in out["available_profiles"]


def test_asks_about_esg_detection():
    for q in ("Ce portefeuille respecte-t-il ses préférences ESG ?", "Y a-t-il des entreprises controversées ?", "Est-il durable ?", "Quelle est l'éthique de ce fonds ?"):
        assert asks_about_esg(q), q
    for q in ("Pourquoi ce portefeuille est-il risqué ?", "Compare A et B.", "Quelle est la volatilité ?"):
        assert not asks_about_esg(q), q


def make_agent(service, active, steps, tool_args=None, weights=None, weights_b=None):
    model = StepModel(steps, tool_args)
    ctx = SessionContext(weights or MATEO_A, active, weights_b=weights_b)
    return GuardianAgent(service, ctx, Tracer(), model_factory=lambda: model), model, ctx


def test_agent_really_calls_the_esg_tool_and_the_trace_matches(real_service):
    ag, model, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Je ne peux pas confirmer que ce portefeuille respecte toutes les préférences ESG de Mateo.")])
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Est-ce que ce portefeuille respecte ses préférences ESG ?")
    assert tr.clarification is None and not tr.withheld and [r.tool for r in tr.tool_records] == [ESG] and tr.tool_records[0].status == "ok"
    from guardian.agent.tools import esg_key_facts
    base = real_service.check_esg(MATEO_A, "mateo").to_dict()
    assert tr.tool_records[0].result == {**base, "key_facts": esg_key_facts(base), "portfolio": "A", "profile": real_service.profiles["mateo"]}
    assert "Profil actif : mateo (Mateo)" in model.prompts[0]


def test_esg_question_without_the_esg_tool_is_withheld(real_service):
    ag, _, _ = make_agent(real_service, "mateo", [("tools", [EV]), ("text", "Ce portefeuille est durable et conforme ESG à 100 %.")])
    tr = ag.ask("Ce portefeuille est-il durable ?")
    assert tr.withheld and tr.text is None and "check_esg_preferences" in tr.withheld_reason
    assert {r.tool for r in tr.tool_records} == {EV}


def test_esg_requests_are_isolated_from_each_other(real_service):
    ag, model, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Réponse 1."), ("text", "Le portefeuille respecte les préférences ESG.")])
    t1 = ag.ask("Que peux-tu dire de l'ESG de ce portefeuille ?")
    t2 = ag.ask("Et sur les controverses ?")
    assert not t1.withheld and t1.tool_records[0].turn == 1
    assert t2.tool_records == [] and t2.withheld and "check_esg_preferences" in t2.withheld_reason       # l'outil de la requête 1 ne valide pas la requête 2
    assert model.seen[2] == [["text"]]


def test_esg_tool_failure_withholds_the_answer(real_service):
    ag, _, ctx = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Tout est conforme ESG.")])
    ctx.fail_tools = {ESG}
    tr = ag.ask("Ce portefeuille respecte-t-il les préférences ESG ?")
    assert tr.withheld and tr.text is None and tr.tool_records[0].status == "error"


def test_active_profile_conflict_applies_to_mateo(real_service):
    ag, model, _ = make_agent(real_service, "robert", [("text", "Ne devrait pas être appelé.")])
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Est-ce que ce portefeuille respecte ses préférences ESG ?")
    assert tr.clarification and "Sélectionnez Mateo" in tr.clarification and model.i == 0 and tr.tool_records == []
    ag2, model2, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Je ne peux pas confirmer.")])
    assert ag2.ask("Mateo veut éviter les entreprises controversées. Est-ce que ce portefeuille respecte ses préférences ESG ?").clarification is None


def test_explain_task_adds_a_separate_esg_section_only_for_esg_profiles():
    assert "Préférences ESG" not in explain_risks_task("Robert")
    t = explain_risks_task("Mateo", has_esg=True)
    assert "check_esg_preferences" in t and "section séparée **Préférences ESG**" in t and "sans les combiner" in t and "jamais que le portefeuille est durable ou conforme ESG" in t


def test_system_prompt_forbids_inventing_esg_facts():
    from guardian.agent.agent import SYSTEM_PROMPT
    for needle in ("check_esg_preferences", "N'invente JAMAIS une controverse, une note ESG, un score", "une absence de résultat n'est pas une preuve d'absence de controverse",
                   "dis que tu ne peux pas confirmer", "jamais qu'un actif ou un portefeuille est « durable »", "Ne combine jamais risque financier et ESG"):
        assert needle in SYSTEM_PROMPT, needle


# ============================================================ contrôle de cohérence des pourcentages cités (ajout V3, après constat en test live)
def _rec(result, status="ok"):
    from types import SimpleNamespace
    return SimpleNamespace(status=status, result=result)


def test_unmatched_percentages_detects_only_numbers_absent_from_tool_results():
    from guardian.agent.agent import unmatched_percentages
    recs = [_rec({"coverage": {"checked_in_sources_pct": 15.0, "weights_pct": {"a": 80.0, "b": 5.0}}, "metrics": {"vol": 22.28, "dd": -36.14},
                  "threshold": 0.35, "n": 1228})]
    ok = "Part vérifiée : 15 %, non évaluable : 80 %, sans objet : 5 %. Fluctuations de 22,3 %, baisse de −36,1 %, repère à 35 %."
    assert unmatched_percentages(ok, recs) == []
    assert unmatched_percentages("Environ 20 % du portefeuille est vérifié (15 % + 5 %).", recs) == ["20 %"]          # somme calculée par le modèle : signalée
    assert unmatched_percentages("Part de 22,5 % et de 40 %.", recs) == ["22,5 %", "40 %"]                           # décimale incorrecte ; entier qui ne correspond pas
    assert unmatched_percentages("Baisse de 36 %.", recs) == []                                                      # 36 % est l'arrondi à l'entier de 36,14 : toléré
    assert unmatched_percentages("0 % de crypto et 100 % en CAD.", recs) == []                                       # bornes ignorées
    assert unmatched_percentages("Aucun pourcentage ici.", recs) == [] and unmatched_percentages("", recs) == []


def test_unmatched_percentages_ignores_failed_tools_and_other_requests():
    from guardian.agent.agent import unmatched_percentages
    assert unmatched_percentages("Part de 15 %.", [_rec({"x": 15.0}, status="error")]) == ["15 %"]        # un outil en échec ne valide rien
    assert unmatched_percentages("Part de 15 %.", []) == ["15 %"]


def test_agent_warns_when_the_text_cites_a_percentage_not_in_the_tool_results(real_service):
    """Pourcentage SANS ancre identifiable dans la phrase : contrôle de cohérence global (avertissement). Avec ancre (V3.3) : voir test_v33_claims.py."""
    ag, _, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Environ 25 % de cet ensemble appelle une lecture prudente. Je ne peux pas confirmer le reste.")])
    tr = ag.ask("Ce portefeuille respecte-t-il les préférences ESG ?")
    assert not tr.withheld and tr.text and tr.unmatched_numbers == ("25 %",)
    assert "n'ont pas été retrouvés tels quels dans les résultats des outils" in tr.caveat and "25 %" in tr.caveat
    ok, _, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Seuls 15 % du portefeuille ont été cherchés ; 80 % ne peuvent pas être évalués.")])
    tr2 = ok.ask("Ce portefeuille respecte-t-il les préférences ESG ?")
    assert not tr2.withheld and tr2.unmatched_numbers == () and tr2.caveat is None


def test_system_prompt_covers_the_defects_seen_in_live_esg_answers():
    from guardian.agent.agent import SYSTEM_PROMPT
    assert "Ne qualifie jamais une « information insuffisante » de « conflit »" in SYSTEM_PROMPT
    assert "ne les additionne pas" in SYSTEM_PROMPT and "nombre exact de sources" in SYSTEM_PROMPT
    assert "aucune émotion, aucun besoin ni aucune situation absents du profil" in SYSTEM_PROMPT


def test_coincidental_match_is_now_caught_when_the_percentage_is_anchored_to_a_category(real_service):
    """V3.2 : « 20 % vérifié » passait car 20 figure ailleurs (poids de XIU.TO). V3.3 : le pourcentage est rattaché à la couverture ESG et refusé."""
    ag, _, _ = make_agent(real_service, "mateo", [("tools", [ESG]), ("text", "Environ 20 % du portefeuille a été vérifié.")])
    tr = ag.ask("Ce portefeuille respecte-t-il les préférences ESG ?")
    assert tr.withheld and tr.text is None and tr.fallback and any(v["category"] == "valeur_associee" for v in tr.claims["violations"])


def test_uncertainty_counts_only_the_sources_actually_used_for_the_portfolio(real_service):
    a = real_service.check_esg(MATEO_A, "mateo")          # MSFT, JNJ, PG cherchés dans NBIM ; aucun FNB filtré
    assert [s["id"] for s in a.sources] == ["nbim_exclusion_list"]
    assert any(u.startswith("Seule 1 source a été utilisée pour ce portefeuille (nbim_exclusion_list)") for u in a.uncertainties)
    assert not any("Seules 2" in u for u in a.uncertainties)
    both = real_service.check_esg({"ESGV": .5, "MSFT": .5}, "mateo")
    assert {s["id"] for s in both.sources} == {"nbim_exclusion_list", "vanguard_esgv_profile"}
    assert any(u.startswith("2 sources ont été utilisées pour ce portefeuille") for u in both.uncertainties)
    none = evaluate_esg({"SPY": 1.0}, real_service.bundle.universe, "mateo", real_service.profiles["mateo"], empty_esg_data())
    assert any("Aucune source n'a été utilisée pour ce portefeuille" in u for u in none.uncertainties)


def test_system_prompt_forbids_filling_unexamined_parts():
    from guardian.agent.agent import SYSTEM_PROMPT
    assert "non examiné dans cette réponse" in SYSTEM_PROMPT and "sans avoir appelé check_profile_constraints" in SYSTEM_PROMPT
