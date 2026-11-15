"""Corrections V3.1 : distinction exclusion / observation et environnement-social / gouvernance (CNQ.TO vs TD.TO), poids par catégorie,
formulation sur les FNB, sorties structurées de l'agent. Aucune règle financière, aucun seuil et aucun CSV ne change (voir tests V2 de non-régression).
"""
import json
import re

import pytest
from conftest import StepModel
from guardian.agent.agent import SYSTEM_PROMPT, GuardianAgent, explain_risks_task
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.esg.engine import COMPLEMENTARY, DOCUMENTED, WORDING_RULES
from guardian.explain.cards import build_cards
from guardian.explain.esg_view import build_esg_view
from guardian.explain.funds import fund_exposure
from guardian.explain.summary import build_priority_summary
from guardian.finance.presets import load_presets

PRESETS = load_presets()
MATEO_A = {t: v / 100 for t, v in PRESETS["mateo_croissance_equilibree"]["weights_pct"].items()}
MATEO_B = {t: v / 100 for t, v in PRESETS["mateo_actions_canadiennes"]["weights_pct"].items()}
ESG, EV, CK = "check_esg_preferences", "evaluate_portfolio", "check_profile_constraints"
CONFLICT_30 = re.compile(r"30\s*%[^.\n]{0,60}(conflit|préférences? ESG)", re.I)


def esg_tool_output(service, weights=MATEO_B):
    ctx = SessionContext(weights, "mateo")
    tools = {t.tool_spec["name"]: t for t in build_tools(service, ctx, Tracer())}
    return tools[ESG]()


# ============================================================ 1. CNQ.TO et TD.TO ne sont pas deux conflits équivalents
def test_cnq_is_documented_exclusion_and_td_is_complementary_observation(real_service):
    r = real_service.check_esg(MATEO_B, "mateo")
    by = {a.ticker: a for a in r.lines}
    assert by["CNQ.TO"].state == DOCUMENTED and by["TD.TO"].state == COMPLEMENTARY
    cnq, td = by["CNQ.TO"].records[0], by["TD.TO"].records[0]
    assert (cnq["decision"], cnq["dimension"], cnq["relevance"]) == ("exclusion", "E", "direct")
    assert (td["decision"], td["dimension"], td["relevance"]) == ("observation", "G", "indirect")
    assert r.overall_state == DOCUMENTED                       # c'est CNQ qui porte l'état global, pas TD
    assert r.weights_by_state[DOCUMENTED] == pytest.approx(0.15) and r.weights_by_state[COMPLEMENTARY] == pytest.approx(0.15)


def test_td_alone_is_never_a_documented_conflict_with_the_declared_preference(real_service):
    r = real_service.check_esg({"TD.TO": 0.5, "RY.TO": 0.5}, "mateo")
    assert r.overall_state != DOCUMENTED and r.weights_by_state[DOCUMENTED] == 0.0 and r.weights_by_state[COMPLEMENTARY] == pytest.approx(0.5)
    view = build_esg_view(r, real_service.bundle.universe)
    assert view["controversies"] == [] and [c["ticker"] for c in view["complementary"]] == ["TD.TO"]
    assert "pour le critère déclaré" in view["state_label"] and "information complémentaire" in view["state_label"]
    assert "n'est pas un conflit environnemental ou social" in view["intro"]


def test_each_category_has_its_own_weight_decision_dimension_and_tickers(real_service):
    out = esg_tool_output(real_service)
    assert out["status"] == "ok"
    (doc,), (comp,) = out["documented_categories"], out["complementary_information"]
    assert (doc["decision"], doc["decision_label"], doc["dimension"], doc["dimension_label"], doc["relevance"]) == ("exclusion", "Exclusion", "E", "environnementale", "direct")
    assert doc["weight_pct"] == 15.0 and doc["tickers"] == ["CNQ.TO"] and doc["label"] == "Exclusion environnementale"
    assert (comp["decision"], comp["decision_label"], comp["dimension"], comp["dimension_label"], comp["relevance"]) == ("observation", "Mise sous observation", "G", "de gouvernance", "indirect")
    assert comp["weight_pct"] == 15.0 and comp["tickers"] == ["TD.TO"] and comp["label"] == "Mise sous observation de gouvernance"
    assert "moins forte" in comp["strength_note"] and "plus forte" in doc["strength_note"]
    assert doc["category_id"] != comp["category_id"]


def test_structured_output_contains_no_merged_30_percent_and_names_both_categories_separately(real_service):
    out = esg_tool_output(real_service)
    pcts = out["coverage"]["weights_by_state_pct"]
    assert pcts["Controverse documentée à examiner"] == 15.0 and pcts["Information complémentaire documentée (hors critère déclaré)"] == 15.0
    assert 30.0 not in pcts.values()
    summ = out["categories_summary"]
    assert "exclusion environnementale : 15 % du portefeuille (CNQ.TO)" in summ and "mise sous observation de gouvernance : 15 % du portefeuille (TD.TO)" in summ
    assert "ne sont pas additionnées" in summ and not CONFLICT_30.search(summ) and "30" not in summ
    assert out["wording_rules"] == list(WORDING_RULES) and any("un seul pourcentage" in r for r in out["wording_rules"])
    assert any("n'est pas un conflit environnemental ou social" in r for r in out["wording_rules"])


def test_sources_and_publication_dates_are_preserved_per_record(real_service):
    out = esg_tool_output(real_service)
    lines = {x["ticker"]: x for x in out["lines"]}
    cnq, td = lines["CNQ.TO"]["documented_records"][0], lines["TD.TO"]["documented_records"][0]
    assert cnq["published"] == "2020-05-13" and td["published"] == "2025-06-11"
    assert cnq["source"] == td["source"] == "nbim_exclusion_list"
    assert cnq["criterion_fr"].startswith("Émissions de gaz") and td["criterion_fr"].startswith("Corruption grave")
    assert cnq["decision_label"] == "Exclusion" and td["decision_label"] == "Mise sous observation"
    assert cnq["dimension_label"] == "environnementale" and td["dimension_label"] == "de gouvernance"
    assert "Directement liée" in cnq["relevance_label"] and "Hors de la formulation stricte" in td["relevance_label"]
    src = out["sources"][0]
    assert src["id"] == "nbim_exclusion_list" and src["consulted_on"] == "2026-11-14" and src["url"].startswith("https://www.nbim.no/")
    assert {s["id"] for s in out["provenance"]["esg_sources"]} == {"nbim_exclusion_list"}
    assert doc_records_are_all_sourced(out)


def doc_records_are_all_sourced(out) -> bool:
    for cat in out["documented_categories"] + out["complementary_information"]:
        for r in cat["records"]:
            if not (r["source"] and r["published"] and r["criterion_fr"]):
                return False
    return True


def test_view_presents_two_separate_sections_with_their_own_wording(real_service):
    view = build_esg_view(real_service.check_esg(MATEO_B, "mateo"), real_service.bundle.universe)
    (cnq,), (td,) = view["controversies"], view["complementary"]
    assert cnq["category_label"] == "Exclusion environnementale" and td["category_label"] == "Mise sous observation de gouvernance"
    assert "dimension environnementale, visée par la préférence de Mateo" in cnq["link"]
    assert "il ne correspond pas à la formulation stricte de la préférence de Mateo" in td["link"]
    assert "environnementales ou sociales" in td["link"] and "ne correspond pas" in td["link"]
    assert "Une mise sous observation est moins forte qu'une exclusion" in td["caution"] and "moins forte" not in cnq["caution"]
    assert "13 mai 2020" in cnq["headline"] and "11 juin 2025" in td["headline"]
    s = view["coverage_summary"]
    assert "Exclusion environnementale : 15 % du portefeuille (CNQ.TO)" in s and "Mise sous observation de gouvernance : 15 % du portefeuille (TD.TO)" in s
    assert "jamais additionnées" in s and not CONFLICT_30.search(s)
    assert [(c["label"], c["weight"], c["tickers"]) for c in view["categories"]] == [("Exclusion environnementale", pytest.approx(0.15), ["CNQ.TO"]),
                                                                                     ("Mise sous observation de gouvernance", pytest.approx(0.15), ["TD.TO"])]


def test_no_global_esg_percentage_or_score_appears_anywhere_in_the_view(real_service):
    out = esg_tool_output(real_service)
    blob = json.dumps(out, ensure_ascii=False)
    assert not CONFLICT_30.search(blob)
    assert not re.search(r"\bscore\b[^.]{0,20}\d|\bnote ESG\s*:?\s*\d", blob, re.I)


def test_portfolio_without_documented_company_has_empty_categories(real_service):
    out = esg_tool_output(real_service, MATEO_A)
    assert out["documented_categories"] == [] and out["complementary_information"] == []
    assert out["overall_state"] == "INSUFFICIENT"


# ============================================================ 2. FNB : même repère, formulation pédagogique, aucun changement financier
def test_fund_note_says_a_20_percent_etf_is_not_a_20_percent_company_and_that_underlying_is_not_measured(real_service):
    fx = fund_exposure(MATEO_A, real_service.bundle.universe, "XIU.TO", 0.20)
    assert fx["has_funds"] and fx["largest_position_is_fund"] and fx["underlying_diversification_measured"] is False
    note = fx["pedagogical_note"]
    assert "Une position de 20 % dans un FNB diversifié n'est pas équivalente à une position de 20 % dans une entreprise individuelle" in note
    assert "La diversification sous-jacente des FNB n'est pas mesurée ici" in note
    assert "peut surestimer la concentration réelle" in note and "Certains FNB sont eux-mêmes concentrés" in note
    assert fx["fund_weight_pct"] == 80.0 and {x["ticker"] for x in fx["fund_lines"]} == {"XIU.TO", "SPY", "QQQ", "XBB.TO", "AGG"}
    assert "GLD" not in {x["ticker"] for x in fx["fund_lines"]}                      # l'or n'est pas un FNB diversifié


def test_fund_note_for_a_single_company_top_position_is_short_and_not_misleading(real_service):
    w = {"NVDA": 0.4, "XIU.TO": 0.3, "XBB.TO": 0.3}
    fx = fund_exposure(w, real_service.bundle.universe, "NVDA", 0.4)
    assert fx["has_funds"] and not fx["largest_position_is_fund"]
    assert "n'est pas équivalente à celle d'une entreprise individuelle" in fx["pedagogical_note"] and "n'est pas mesurée" in fx["pedagogical_note"]
    assert "20 %" not in fx["pedagogical_note"] and "40 %" not in fx["pedagogical_note"]
    none = fund_exposure({"NVDA": 0.5, "AAPL": 0.5}, real_service.bundle.universe, "NVDA", 0.5)
    assert none["has_funds"] is False and "Aucun FNB" in none["pedagogical_note"] and none["fund_lines"] == []


def test_cards_add_the_fund_note_without_changing_any_financial_value(real_service):
    res, rep = real_service.check(MATEO_A, "mateo")
    cards = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles["mateo"], real_service.bundle.universe, real_service.rules_cfg)}
    assert "Une position de 20 % dans un FNB diversifié n'est pas équivalente à une position de 20 % dans une entreprise individuelle" in cards["R1"].note
    assert "n'est pas mesurée" in cards["R7"].note
    assert all(cards[r].note is None for r in ("R2", "R4", "R5", "R10"))
    # mesures et statuts : inchangés, toujours ceux du moteur
    f = rep.by_id()
    assert cards["R1"].status == f["R1"].status and cards["R7"].status == f["R7"].status
    assert "20 %" in cards["R1"].measure
    assert res.concentration.max_weight == pytest.approx(0.20) and res.concentration.effective_n == pytest.approx(1 / sum(w * w for w in res.weights.values()))


def test_no_fund_note_when_the_largest_position_is_a_single_stock_for_r1(real_service):
    w = {"NVDA": 0.4, "AAPL": 0.3, "XIU.TO": 0.3}
    res, rep = real_service.check(w, "robert")
    cards = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg)}
    assert cards["R1"].note is None and cards["R7"].note is not None


def test_priority_summary_mentions_the_fund_when_the_top_position_is_an_etf_and_keeps_the_numbers(real_service):
    w = {"XIU.TO": 0.7, "XBB.TO": 0.3}
    res, rep = real_service.check(w, "robert")
    s = build_priority_summary(res, rep, real_service.profiles["robert"], real_service.bundle.universe)
    assert "c'est un FNB" in s.sentence and "70 %" in s.sentence and "n'est pas mesurée" in s.sentence
    w2 = {"NVDA": 0.7, "AAPL": 0.3}
    res2, rep2 = real_service.check(w2, "robert")
    s2 = build_priority_summary(res2, rep2, real_service.profiles["robert"], real_service.bundle.universe)
    assert "FNB" not in s2.sentence


def test_fund_exposure_is_added_to_tool_outputs_without_changing_engine_values(real_service):
    ctx = SessionContext(MATEO_A, "mateo", weights_b=MATEO_B)
    t = {x.tool_spec["name"]: x for x in build_tools(real_service, ctx, Tracer())}
    ev, ck, cmp_ = t[EV](), t[CK](), t["compare_scenarios"]()
    for out in (ev, ck, cmp_["portfolio_A"], cmp_["portfolio_B"]):
        assert out["fund_exposure"]["underlying_diversification_measured"] is False and "pedagogical_note" in out["fund_exposure"]
    base = real_service.analyze(MATEO_A).to_tool_dict()
    assert {k: v for k, v in ev.items() if k not in ("fund_exposure", "key_facts", "portfolio")} == base                 # métriques, HHI, poids : identiques
    assert ev["fund_exposure"]["largest_position_is_fund"] is True and ev["concentration"] == base["concentration"]
    assert ck["findings"] == real_service.check(MATEO_A, "mateo")[1].to_dict()["findings"]                 # statuts et seuils : identiques


# ============================================================ 3. agent : consigne ET sorties structurées
def test_prompt_states_exclusion_vs_observation_and_environment_vs_governance_rules():
    for needle in ("Exclusion et mise sous observation sont deux décisions différentes", "une observation n'est pas une exclusion",
                   "Environnement ou social et gouvernance sont deux dimensions différentes", "documented_categories", "complementary_information",
                   "JAMAIS comme un conflit environnemental ou social", "N'additionne JAMAIS des catégories différentes en un seul pourcentage",
                   "30 % en conflit avec les préférences ESG", "décision (decision_label)", "dimension (dimension_label)", "poids (weight_pct)",
                   "la source et la date de publication", "N'écris aucune affirmation sans preuve", "sans le reformuler en accusation"):
        assert needle in SYSTEM_PROMPT, needle


def test_prompt_states_etf_rule_and_still_lists_the_five_tools():
    for needle in ("Une position de X % dans un FNB diversifié n'est pas équivalente à une position de X % dans une entreprise individuelle",
                   "fund_exposure", "largest_position_is_fund", "pedagogical_note", "la diversification sous-jacente des FNB n'est pas mesurée",
                   "Ne change ni un poids, ni un indice, ni un seuil, ni un statut"):
        assert needle in SYSTEM_PROMPT, needle
    for tool in ("get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios", "check_esg_preferences"):
        assert f"- {tool} :" in SYSTEM_PROMPT


def test_explain_task_carries_the_new_esg_and_etf_instructions():
    t = explain_risks_task("Mateo", has_esg=True)
    assert "Distingue exclusion et observation, environnement/social et gouvernance" in t and "n'additionne jamais les catégories" in t
    assert "fund_exposure.largest_position_is_fund" in t and "diversification sous-jacente des FNB n'est pas mesurée" in t
    t2 = explain_risks_task("Robert", has_esg=False)
    assert "exclusion et observation" not in t2 and "fund_exposure.largest_position_is_fund" in t2


def test_agent_keeps_five_tools_and_traces_the_structured_esg_result(real_service):
    ctx = SessionContext(MATEO_B, "mateo")
    names = sorted(t.tool_spec["name"] for t in build_tools(real_service, ctx, Tracer()))
    assert names == sorted(["get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios", ESG])
    model = StepModel([("tools", [ESG]), ("text", "Exclusion environnementale CNQ.TO (15 %). Information complémentaire de gouvernance TD.TO (15 %).")])
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model)
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?")
    rec = next(r for r in tr.tool_records if r.tool == ESG)
    assert not tr.withheld and rec.status == "ok" and rec.result["documented_categories"][0]["tickers"] == ["CNQ.TO"]
    assert rec.result["complementary_information"][0]["tickers"] == ["TD.TO"] and rec.result_digest
    assert tr.unmatched_numbers == ()                                                       # 15 % retrouvé dans la catégorie
    assert "deux décisions différentes" in ag._get_agent().system_prompt          # la consigne de distinction est bien celle donnée à l'agent


def test_agent_answer_merging_the_two_categories_into_30_percent_is_flagged_as_unverified(real_service):
    ctx = SessionContext(MATEO_B, "mateo")
    model = StepModel([("tools", [ESG]), ("text", "30 % du portefeuille est en conflit avec les préférences ESG.")])
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model)
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?")
    assert "30 %" in tr.unmatched_numbers and tr.caveat and "30 %" in tr.caveat           # la somme n'existe dans aucune sortie d'outil
