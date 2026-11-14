"""Tests réels contre Amazon Bedrock. Désactivés par défaut : exécuter avec  RUN_LIVE=1 pytest -m live -s

Chaque test appelle réellement le modèle (quelques milliers de jetons au total). Les traces sont exportées dans traces/.
"""
import json
import os
from pathlib import Path

import pytest

from conftest import expected_compare, expected_evaluate
from guardian.agent.agent import GuardianAgent
from guardian.agent.tools import SessionContext
from guardian.agent.tracer import Tracer

pytestmark = [pytest.mark.live, pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="RUN_LIVE=1 requis")]
WEIGHTS = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}
TRACES = Path(__file__).resolve().parents[1] / "traces"
QUESTION = "Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?"


def _agent(service, fail=()):
    return GuardianAgent(service, SessionContext(WEIGHTS, "robert", fail_tools=set(fail)), Tracer())


def test_live_agent_calls_real_financial_tool(real_service):
    ag = _agent(real_service)
    tr = ag.ask(QUESTION)
    print("\nOUTILS :", [(r.tool, r.status, r.duration_ms) for r in tr.tool_records])
    print("USAGE :", tr.usage, "cycles :", tr.cycles, "durée :", tr.duration_s)
    print("TEXTE :", tr.text)
    TRACES.mkdir(exist_ok=True)
    (TRACES / "live_robert_nvda40.json").write_text(json.dumps(
        {"question": QUESTION, "model_id": tr.model_id, "region": tr.region, "started_at": tr.started_at,
         "answer": tr.text, "withheld": tr.withheld, "usage": tr.usage, "tool_records": ag.tracer.export()},
        ensure_ascii=False, indent=2))
    assert tr.error is None, tr.error
    assert len(tr.tool_records) >= 1 and all(r.status == "ok" for r in tr.tool_records)
    # la trace correspond à l'exécution réelle : le résultat tracé est celui du moteur
    ev = [r for r in tr.tool_records if r.tool == "evaluate_portfolio"]
    if ev:
        assert ev[0].result == expected_evaluate(real_service, WEIGHTS)
    assert not tr.withheld and tr.text


def test_live_tool_failure_does_not_surface_improvised_numbers(real_service):
    ag = _agent(real_service, fail={"evaluate_portfolio", "check_profile_constraints"})
    tr = ag.ask(QUESTION)
    print("\nOUTILS :", [(r.tool, r.status, r.error) for r in tr.tool_records])
    print("RETENUE :", tr.withheld, "|", tr.withheld_reason)
    assert tr.tool_records and all(r.status == "error" for r in tr.tool_records)
    assert tr.withheld and tr.text is None
    assert real_service.analyze(WEIGHTS).volatility > 0      # le moteur reste disponible


def test_live_two_consecutive_requests_each_validated_by_its_own_tools(real_service):
    """Scénario du test manuel : même question posée deux fois de suite à l'agent réel."""
    q = ("Pourquoi ce portefeuille composé de 40 % de NVDA, 35 % de XBB.TO et 25 % de XIU.TO "
         "pourrait-il être risqué pour Robert ?")
    ag = _agent(real_service)
    t1, t2 = ag.ask(q), ag.ask(q)
    for t in (t1, t2):
        print("\nREQUÊTE", t.turn, "| outils :", [(r.tool, r.status) for r in t.tool_records],
              "| cycles :", t.cycles, "| retenue :", t.withheld, "|", t.withheld_reason)
    assert t1.error is None and t2.error is None
    assert not t1.withheld and not t2.withheld
    assert len(t1.tool_records) >= 1 and len(t2.tool_records) >= 1       # la requête 2 appelle ses propres outils
    assert {r.turn for r in t1.tool_records} == {1} and {r.turn for r in t2.tool_records} == {2}


# ----------------------------------------------------------------------------- V1
def _preset_fractions(pid):
    from guardian.finance.presets import load_presets
    return {t: v / 100 for t, v in load_presets()[pid]["weights_pct"].items()}


def test_live_v1_compare_nvda40_with_diversified_portfolio_for_robert(real_service):
    """Fonctionnalité démontrée : l'agent réel utilise compare_scenarios sur les allocations sélectionnées."""
    a, b = _preset_fractions("robert_nvda_40"), _preset_fractions("robert_prudent")
    ag = GuardianAgent(real_service, SessionContext(a, "robert", weights_b=b), Tracer())
    q = ("Pour Robert, compare le portefeuille contenant 40 % de NVDA avec une allocation plus diversifiée. "
         "Quels compromis historiques observes-tu ?")
    tr = ag.ask(q)
    print("\nOUTILS :", [(r.tool, r.status, r.arguments) for r in tr.tool_records], "| cycles :", tr.cycles, "| usage :", tr.usage)
    print("RETENUE :", tr.withheld, tr.withheld_reason, "\nTEXTE :\n", tr.text)
    TRACES.mkdir(exist_ok=True)
    (TRACES / "live_v1_compare.json").write_text(json.dumps(
        {"question": q, "model_id": tr.model_id, "region": tr.region, "started_at": tr.started_at, "context": tr.context,
         "answer": tr.text, "withheld": tr.withheld, "usage": tr.usage, "tool_records": ag.tracer.export()}, ensure_ascii=False, indent=2))
    assert tr.error is None, tr.error
    assert "compare_scenarios" in {r.tool for r in tr.tool_records}
    assert all(r.status == "ok" for r in tr.tool_records) and not tr.withheld and tr.text
    cmp_rec = next(r for r in tr.tool_records if r.tool == "compare_scenarios")
    assert cmp_rec.result == expected_compare(real_service, a, b, "robert")   # trace = moteur déterministe


def test_live_v1_same_portfolio_evaluated_for_both_named_profiles(real_service):
    """Fonctionnalité démontrée : quand l'utilisateur NOMME Robert et Amira, l'agent réel interroge les deux profils."""
    a = _preset_fractions("robert_nvda_40")
    ag = GuardianAgent(real_service, SessionContext(a, "robert"), Tracer())
    tr = ag.ask("Compare l'évaluation de cette allocation pour Robert et pour Amira : les diagnostics diffèrent-ils ?")
    print("\nOUTILS :", [(r.tool, r.status, r.arguments) for r in tr.tool_records], "| cycles :", tr.cycles, "| usage :", tr.usage)
    print("RETENUE :", tr.withheld, tr.withheld_reason, "\nTEXTE :\n", tr.text)
    assert tr.error is None and tr.clarification is None, (tr.error, tr.clarification)
    assert tr.tool_records and all(r.status == "ok" for r in tr.tool_records) and not tr.withheld
    profs = {(r.arguments.get("profile_id") or "robert").lower() for r in tr.tool_records if r.tool in ("get_profile", "check_profile_constraints")}
    assert profs == {"robert", "amira"}, profs


def test_live_ui_trace_shows_a_real_successful_compare_scenarios_call():
    """Interface réelle + Bedrock réel : la trace de la requête montre (ou ne montre pas) compare_scenarios selon ce qui s'est vraiment passé."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app" / "app.py"), default_timeout=180).run()
    q = ("Pour Robert, compare le portefeuille contenant 40 % de NVDA avec une allocation plus diversifiée. "
         "Quels compromis historiques observes-tu ?")
    at.text_area[0].set_value(q)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    recs = at.session_state.agent.tracer.records
    print("\nTRACE RÉELLE :", [(r.id, r.tool, r.status, r.arguments) for r in recs])
    print("MESSAGES success :", [s.value for s in at.success])
    print("LIGNES de trace :", [e.label for e in at.expander if "requête" in e.label])
    cmp_ok = [r for r in recs if r.tool == "compare_scenarios" and r.status == "ok"]
    assert cmp_ok, "compare_scenarios n'a pas été appelé avec succès : " + str([(r.tool, r.status) for r in recs])
    assert any("compare_scenarios : appelé avec succès" in s.value and f"appel n° {cmp_ok[0].id}" in s.value for s in at.success)
    assert any(f"#{cmp_ok[0].id} · requête 1 · compare_scenarios" in e.label for e in at.expander)
    assert not any("Analyse incomplète" in w.value for w in at.warning)


# ----------------------------------------------------------------------------- V2 : bouton « Explique-moi mes risques avec l'IA »
def _live_explain(profile_id: str):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app" / "app.py"), default_timeout=240).run()
    if profile_id != "robert":
        at.selectbox(key="preset_A").set_value("robert_prudent").run()          # choix explicite, puis retour au scénario Nvidia pour le même portefeuille
        at.selectbox(key="preset_A").set_value("robert_nvda_40").run()
        at.selectbox(key="profile_id").set_value(profile_id).run()
    at.button(key="explain_btn").click()
    at.run()
    assert not at.exception, at.exception
    return at


def _report_live(at, name):
    tr = at.session_state.history[-1]
    print("\nOUTILS :", [(r.id, r.tool, r.status, r.arguments) for r in tr.tool_records], "| cycles :", tr.cycles, "| usage :", tr.usage)
    print("RETENUE :", tr.withheld, tr.withheld_reason, "\nTEXTE :\n", tr.text)
    TRACES.mkdir(exist_ok=True)
    (TRACES / f"live_v2_explain_{name}.json").write_text(json.dumps(
        {"question": tr.question, "kind": tr.kind, "model_id": tr.model_id, "region": tr.region, "started_at": tr.started_at, "context": tr.context,
         "answer": tr.text, "withheld": tr.withheld, "usage": tr.usage, "tool_records": at.session_state.agent.tracer.export()}, ensure_ascii=False, indent=2))
    return tr


def test_live_v2_explain_my_risks_for_robert():
    at = _live_explain("robert")
    tr = _report_live(at, "robert")
    assert tr.error is None and tr.kind == "explain_risks" and not tr.withheld and tr.text
    tools = {r.tool: r for r in tr.tool_records if r.status == "ok"}
    assert "evaluate_portfolio" in tools and "check_profile_constraints" in tools
    assert tr.context["profile_id"] == "robert" and tr.context["weights_a_pct"] == {"NVDA": 40.0, "XBB.TO": 35.0, "XIU.TO": 25.0}
    assert all(r.turn == 1 for r in tr.tool_records)
    md = " ".join(m.value for m in at.markdown)
    assert "A analysé votre portefeuille A" in md and "A comparé les risques du portefeuille A avec le profil de Robert" in md
    assert "Faits historiques utilisés (valeurs calculées par le moteur)" in md


def test_live_v2_explain_my_risks_for_amira_same_portfolio():
    at = _live_explain("amira")
    tr = _report_live(at, "amira")
    assert tr.error is None and not tr.withheld and tr.text
    assert tr.context["profile_id"] == "amira" and tr.context["weights_a_pct"] == {"NVDA": 40.0, "XBB.TO": 35.0, "XIU.TO": 25.0}
    chk = next(r for r in tr.tool_records if r.tool == "check_profile_constraints" and r.status == "ok")
    assert chk.result["profile_id"] == "amira"


# ----------------------------------------------------------------------------- V3 : Mateo et préférences ESG
ESG_FALSE_CLAIMS = r"conforme ESG|portefeuille (est )?durable|est durable|respecte (toutes )?(ses|ses) préférences ESG\b(?! )|entièrement vérifi"


def _mateo_agent(service, weights, weights_b=None):
    return GuardianAgent(service, SessionContext(weights, "mateo", weights_b=weights_b), Tracer())


def _show(tr):
    print("\nOUTILS :", [(r.id, r.tool, r.status, r.arguments) for r in tr.tool_records], "| cycles :", tr.cycles, "| usage :", tr.usage)
    print("RETENUE :", tr.withheld, tr.withheld_reason, "\nTEXTE :\n", tr.text)


def test_live_v3_mateo_esg_question_with_insufficient_data(real_service):
    """Question d'exemple du cahier V3 : l'agent réel doit appeler check_esg_preferences et ne pas affirmer la conformité."""
    a = _preset_fractions("mateo_croissance_equilibree")
    ag = _mateo_agent(real_service, a)
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Est-ce que ce portefeuille respecte ses préférences ESG ?")
    _show(tr)
    TRACES.mkdir(exist_ok=True)
    (TRACES / "live_v3_mateo_esg_insuffisant.json").write_text(json.dumps(
        {"question": tr.question, "model_id": tr.model_id, "region": tr.region, "started_at": tr.started_at, "context": tr.context,
         "answer": tr.text, "withheld": tr.withheld, "usage": tr.usage, "tool_records": ag.tracer.export()}, ensure_ascii=False, indent=2))
    assert tr.error is None and tr.clarification is None and not tr.withheld and tr.text, (tr.error, tr.withheld_reason)
    esg = [r for r in tr.tool_records if r.tool == "check_esg_preferences"]
    assert esg and esg[0].status == "ok" and esg[0].result["overall_state"] == "INSUFFICIENT" and all(r.turn == 1 for r in tr.tool_records)
    import re
    assert not re.search(ESG_FALSE_CLAIMS, tr.text, re.I), tr.text
    assert re.search(r"insuffisan|ne peux pas confirmer|ne permettent pas|non évalu|impossible de confirmer", tr.text, re.I), tr.text


def test_live_v3_mateo_esg_question_with_documented_information(real_service):
    b = _preset_fractions("mateo_actions_canadiennes")
    ag = _mateo_agent(real_service, b)
    tr = ag.ask("Ce portefeuille contient-il des entreprises liées à des controverses documentées pour Mateo ?")
    _show(tr)
    assert tr.error is None and not tr.withheld and tr.text
    esg = next(r for r in tr.tool_records if r.tool == "check_esg_preferences" and r.status == "ok")
    assert esg.result["overall_state"] == "DOCUMENTED"
    import re
    assert re.search(r"Canadian Natural|CNQ", tr.text) and re.search(r"Toronto|TD", tr.text)
    assert not re.search(ESG_FALSE_CLAIMS, tr.text, re.I) and not re.search(r"\bcoupable|\bcorrompu|a été condamn", tr.text, re.I), tr.text
    # V3.1 : CNQ (exclusion environnementale) et TD (observation de gouvernance) ne sont pas fusionnés en un conflit unique
    assert re.search(r"exclu|exclusion", tr.text, re.I) and re.search(r"observation", tr.text, re.I) and re.search(r"gouvernance", tr.text, re.I), tr.text
    assert not re.search(r"30\s*%[^.\n]{0,60}(conflit|préférences? ESG)", tr.text, re.I), tr.text
    assert esg.result["documented_categories"][0]["tickers"] == ["CNQ.TO"] and esg.result["complementary_information"][0]["tickers"] == ["TD.TO"]


def test_live_v3_explain_my_risks_for_mateo_with_separate_esg_section():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app" / "app.py"), default_timeout=240).run()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.button(key="explain_btn").click()
    at.run()
    assert not at.exception, at.exception
    tr = at.session_state.history[-1]
    _show(tr)
    TRACES.mkdir(exist_ok=True)
    (TRACES / "live_v3_explain_mateo.json").write_text(json.dumps(
        {"question": tr.question, "kind": tr.kind, "context": tr.context, "answer": tr.text, "withheld": tr.withheld, "usage": tr.usage,
         "tool_records": at.session_state.agent.tracer.export()}, ensure_ascii=False, indent=2))
    assert tr.error is None and not tr.withheld and tr.text, tr.withheld_reason
    ok = {r.tool for r in tr.tool_records if r.status == "ok"}
    assert {"evaluate_portfolio", "check_profile_constraints", "check_esg_preferences"} <= ok
    import re
    assert not re.search(ESG_FALSE_CLAIMS, tr.text, re.I), tr.text
