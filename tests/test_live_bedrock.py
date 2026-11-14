"""Tests réels contre Amazon Bedrock. Désactivés par défaut : exécuter avec  RUN_LIVE=1 pytest -m live -s

Chaque test appelle réellement le modèle (quelques milliers de jetons au total). Les traces sont exportées dans traces/.
"""
import json
import os
from pathlib import Path

import pytest

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
        assert ev[0].result == {**real_service.analyze(WEIGHTS).to_tool_dict(), "portfolio": "A"}
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
    assert cmp_rec.result == {**real_service.compare(a, b, "robert").to_tool_dict(), "profile": real_service.profiles["robert"]}   # trace = moteur déterministe


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
