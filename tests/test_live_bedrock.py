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
        assert ev[0].result == real_service.analyze(WEIGHTS).to_tool_dict()
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
