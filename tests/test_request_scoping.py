"""Régression : la validation d'une requête n'utilise QUE les outils exécutés pendant cette requête.

Contexte (incident du test manuel) : « Tour 2 · 0 appel(s) d'outil » = une 2e requête utilisateur, pas un cycle interne.
Avant correction, l'agent gardait l'historique : à la requête 2 le modèle voyait les résultats d'outils de la requête 1.
"""
import threading

import pytest
from streamlit.testing.v1 import AppTest

from conftest import REPO, StepModel
from guardian.agent import agent as agent_mod
from guardian.agent.agent import GuardianAgent
from guardian.agent.tools import SessionContext
from guardian.agent.tracer import Tracer

W = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}
EV, CK = "evaluate_portfolio", "check_profile_constraints"
NUMBERS = "La volatilité annualisée est de 22,3 % et le drawdown de 36,1 %."


def make(service, steps, fail=()):
    model = StepModel(steps)
    ctx = SessionContext(W, "robert", fail_tools=set(fail))
    return GuardianAgent(service, ctx, Tracer(), model_factory=lambda: model), model, ctx


# 1. plusieurs cycles internes, outils au premier cycle (et au second)
def test_multiple_internal_cycles_all_tools_count_for_the_request(real_service):
    ag, model, _ = make(real_service, [("tools", [EV]), ("tools", [CK]), ("text", NUMBERS)])
    tr = ag.ask("Pourquoi risqué pour Robert ?")
    assert tr.turn == 1 and tr.cycles == 3                       # 3 cycles internes, 1 seule requête utilisateur
    assert sorted(r.tool for r in tr.tool_records) == [CK, EV]
    assert all(r.status == "ok" and r.turn == 1 for r in tr.tool_records)
    assert not tr.withheld and tr.text == NUMBERS and tr.caveat is None


def test_tools_in_first_cycle_then_numbers_in_later_cycle(real_service):
    ag, _, _ = make(real_service, [("tools", [EV, CK]), ("text", NUMBERS)])
    tr = ag.ask("q")
    assert tr.cycles == 2 and len(tr.tool_records) == 2 and not tr.withheld


# 2. demande sans aucun outil
@pytest.mark.parametrize("text,withheld", [(NUMBERS, True), ("Je peux vous aider à analyser un portefeuille.", False)])
def test_request_without_any_tool(real_service, text, withheld):
    ag, _, _ = make(real_service, [("text", text)])
    tr = ag.ask("q")
    assert tr.tool_records == [] and tr.withheld is withheld
    if withheld:
        assert tr.text is None and "chiffres" in tr.withheld_reason
    else:
        assert tr.text == text and "Aucun outil" in tr.caveat       # affiché avec avertissement, rien de vérifié


# 3. nouvelle demande après une demande réussie
def test_new_request_is_never_validated_by_a_previous_trace(real_service):
    ag, model, _ = make(real_service, [("tools", [EV, CK]), ("text", NUMBERS), ("text", NUMBERS)])
    t1 = ag.ask("Q1")
    assert not t1.withheld and len(t1.tool_records) == 2
    t2 = ag.ask("Q2")                                              # le « modèle » répond avec des chiffres, sans outil
    assert t2.turn == 2 and t2.tool_records == []                  # la trace de la requête 1 n'est pas réutilisée
    assert t2.withheld and t2.text is None
    assert len(ag.tracer.records) == 2 and {r.turn for r in ag.tracer.records} == {1}
    assert model.seen[2] == [["text"]]                              # début de la requête 2 : aucun toolResult ancien dans le contexte


def test_new_request_with_its_own_tools_is_validated_by_its_own_records(real_service):
    ag, model, _ = make(real_service, [("tools", [EV]), ("text", NUMBERS), ("tools", [EV, CK]), ("text", NUMBERS)])
    t1, t2 = ag.ask("Q1"), ag.ask("Q2")
    assert not t1.withheld and not t2.withheld
    assert [r.turn for r in t1.tool_records] == [1] and {r.turn for r in t2.tool_records} == {2}
    assert len(t1.tool_records) == 1 and len(t2.tool_records) == 2
    assert model.seen[2] == [["text"]]                              # pas de mémoire de la requête 1


# 4. outil qui échoue
def test_failing_tool_withholds_even_if_another_tool_succeeded(real_service):
    ag, _, _ = make(real_service, [("tools", [EV, CK]), ("text", NUMBERS)], fail={CK})
    tr = ag.ask("q")
    status = {r.tool: r.status for r in tr.tool_records}
    assert status == {EV: "ok", CK: "error"}                       # les deux sont tracés
    assert tr.withheld and tr.text is None and CK in tr.withheld_reason
    assert "22,3" not in str(tr.__dict__)


def test_failure_does_not_poison_the_next_request(real_service):
    ag, model, ctx = make(real_service, [("tools", [EV]), ("text", NUMBERS), ("tools", [EV]), ("text", NUMBERS)], fail={EV})
    t1 = ag.ask("Q1")
    assert t1.withheld
    ctx.fail_tools = set()                                         # la panne est réparée
    t2 = ag.ask("Q2")
    assert not t2.withheld and [r.status for r in t2.tool_records] == ["ok"] and t2.tool_records[0].turn == 2
    assert model.seen[2] == [["text"]]                              # la réponse retenue n'est pas réinjectée


# 5. deux outils en parallèle (même cycle), répété pour détecter une course
def test_two_parallel_tools_are_both_attributed_to_the_request(real_service):
    for _ in range(15):
        ag, _, _ = make(real_service, [("tools", [EV, CK]), ("text", NUMBERS)])
        tr = ag.ask("q")
        assert sorted(r.tool for r in tr.tool_records) == [CK, EV]
        assert len({r.id for r in tr.tool_records}) == 2 and all(r.turn == 1 for r in tr.tool_records)
        assert not tr.withheld


def test_concurrent_requests_never_mix_their_records(real_service):
    ag, _, _ = make(real_service, [("tools", [EV]), ("text", NUMBERS)] * 2)
    out = []
    threads = [threading.Thread(target=lambda: out.append(ag.ask("q"))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(t.turn for t in out) == [1, 2]
    for t in out:
        assert len(t.tool_records) == 1 and t.tool_records[0].turn == t.turn and not t.withheld


# 6. interface : plusieurs requêtes affichées, libellés « Requête », aucune validation croisée
def _patched_app(monkeypatch, steps):
    model = StepModel(steps)
    original = agent_mod.GuardianAgent.__init__

    def patched(self, *a, **kw):
        kw["model_factory"] = lambda: model
        original(self, *a, **kw)
    monkeypatch.setattr(agent_mod.GuardianAgent, "__init__", patched)
    return AppTest.from_file(str(REPO / "app" / "app.py"), default_timeout=60).run()


def _ask(at, q):
    at.text_area[0].set_value(q)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    return at.run()


def test_ui_second_request_with_tools_is_not_flagged_incomplete(monkeypatch):
    at = _patched_app(monkeypatch, [("tools", [EV, CK]), ("text", NUMBERS), ("tools", [EV, CK]), ("text", NUMBERS)])
    _ask(at, "Q1")
    _ask(at, "Q2")
    assert not at.exception, at.exception
    assert not any("Analyse incomplète" in w.value for w in at.warning)
    captions = " ".join(c.value for c in at.caption)
    assert "Requête n° 2 · 2 appel(s) d'outil dans cette requête (2 réussi(s))" in captions
    assert "Requête n° 1 · 2 appel(s)" in captions                 # la requête 1 reste visible
    assert "Tour " not in captions


def test_ui_request_without_tools_shows_zero_tools_and_keeps_previous_request(monkeypatch):
    at = _patched_app(monkeypatch, [("tools", [EV, CK]), ("text", NUMBERS), ("text", NUMBERS)])
    _ask(at, "Q1")
    _ask(at, "Q2")
    assert any("Analyse incomplète" in w.value for w in at.warning)
    captions = " ".join(c.value for c in at.caption)
    assert "Requête n° 2 · 0 appel(s) d'outil dans cette requête" in captions
    assert "Requête n° 1 · 2 appel(s) d'outil dans cette requête (2 réussi(s))" in captions   # requête 1 valide, toujours affichée
