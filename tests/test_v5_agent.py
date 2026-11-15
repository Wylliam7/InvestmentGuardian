"""V5 : Nova choisit et appelle les outils ; Python calcule. Faux modèles Strands uniquement (aucun appel AWS).

Ces tests vérifient le MÉCANISME (origine des appels, relance, absence de préexécution, doublons, isolement des requêtes, erreurs)
et l'exactitude des données Python pour le parcours Amira. Ils ne disent rien de la qualité du texte de Nova (voir le banc Bedrock).
"""
import pytest
from conftest import StepModel

from guardian.agent.tools import SessionContext
from guardian.agent_v5.agent import RELAUNCH, SYSTEM_PROMPT_V5, UNCONFIRMED, AgentV5, needs_guardian

EV, CK, GP, CMP = "evaluate_portfolio", "check_profile_constraints", "get_profile", "compare_scenarios"
AMIRA_A = {"NVDA": .25, "TSLA": .15, "QQQ": .25, "SHOP.TO": .05, "BTC-USD": .20, "ETH-USD": .10}
Q = ("Mon portefeuille contient six positions. Est-ce que cela signifie automatiquement que je suis bien diversifiée ? "
     "Explique la différence entre le nombre de positions et les risques auxquels je suis exposée.")


def make(service, steps, tool_args=None, model=None, fail=(), ctx=None):
    model = model or StepModel(steps, tool_args=tool_args)
    ctx = ctx or SessionContext(dict(AMIRA_A), "amira", fail_tools=set(fail))
    return AgentV5(service, ctx, model_factory=lambda: model), model, ctx


def user_texts(r):
    return ["".join(b.get("text", "") for b in m["content"]) for m in r.messages if m["role"] == "user" and any("text" in b for b in m["content"])]


# ---------------------------------------------------------------- données Python du parcours Amira (déterministe)
def test_python_returns_the_expected_amira_guardian_statuses_and_facts(real_service):
    ag, _, _ = make(real_service, [("tools", [CK, EV]), ("text", "Réponse.")])
    r = ag.ask(Q)
    ck = next(c.result for c in r.calls if c.tool == CK)
    status = {f["rule_id"]: f["status"] for f in ck["findings"]}
    assert status == {"R1": "ATTENTION", "R2": "CONFLIT", "R4": "CONFLIT", "R5": "CONFLIT", "R7": "OK", "R10": "INFO"}
    ev = next(c.result for c in r.calls if c.tool == EV)
    assert len(ev["weights_pct"]) == 6 and ev["concentration"]["effective_number_of_positions"] == 5.0
    assert ev["fund_exposure"]["underlying_diversification_measured"] is False
    assert ev["key_facts"]["technology"]["exposition_technologique_totale_mesurée"] is False


# ---------------------------------------------------------------- origine des appels : le modèle, jamais une préexécution
class InspectingModel(StepModel):
    """Note le nombre d'appels d'outils déjà exécutés au moment où le modèle est sollicité pour la première fois."""
    def __init__(self, steps, holder):
        super().__init__(steps)
        self.holder, self.calls_at_first_turn = holder, None

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        if self.calls_at_first_turn is None:
            self.calls_at_first_turn = self.holder[0].computed if self.holder else 0
        async for ev in super().stream(messages, tool_specs, system_prompt, **kw):
            yield ev


def test_no_tool_runs_before_the_model_and_every_call_matches_a_model_tool_use(real_service, monkeypatch):
    from guardian.agent_v5 import agent as mod
    holder = []
    real = mod.RequestTools

    def spy(*a, **k):
        rt = real(*a, **k)
        holder.append(rt)
        return rt
    monkeypatch.setattr(mod, "RequestTools", spy)
    model = InspectingModel([("tools", [CK]), ("text", "Réponse.")], holder)
    ag, _, _ = make(real_service, [], model=model)
    r = ag.ask(Q)
    assert model.calls_at_first_turn == 0                                   # aucune préexécution Python
    assert [(c.tool, c.origin) for c in r.calls] == [(CK, "model")]
    assert r.model_tool_uses == [(r.calls[0].tool_use_id, CK)] and r.provenance_ok
    assert r.sdk_tool_counts == {CK: 1} and not r.relaunched and r.confirmed


# ---------------------------------------------------------------- omission : une relance ciblée, Nova fait l'appel
def test_missing_guardian_check_triggers_one_targeted_relaunch_and_nova_makes_the_call(real_service):
    ag, model, _ = make(real_service, [("tools", [EV]), ("text", "Six lignes ne suffisent pas."), ("tools", [CK]), ("text", "Réponse complète.")])
    r = ag.ask(Q)
    assert r.relaunched and r.confirmed and r.text == "Réponse complète."
    assert [c.tool for c in r.calls] == [EV, CK] and r.provenance_ok
    relaunch = [t for t in user_texts(r) if t.startswith("[CONTRÔLE DE L'APPLICATION]")]
    assert relaunch == [RELAUNCH.format(why="les risques, la diversification ou l'adéquation au profil")]
    assert "check_profile_constraints" in relaunch[0] and "statuts du Guardian Check" in relaunch[0]


def test_still_missing_after_relaunch_is_reported_as_unconfirmed_with_available_facts(real_service):
    ag, _, _ = make(real_service, [("tools", [EV]), ("text", "Réponse."), ("text", "Toujours sans Guardian Check.")])
    r = ag.ask(Q)
    assert r.relaunched and not r.confirmed and r.notice == UNCONFIRMED
    titles = [t for t, _ in r.facts]
    assert any(t.startswith("Faits historiques utilisés") for t in titles) and not any("Statuts évalués" in t for t in titles)


def test_only_one_relaunch_is_ever_sent(real_service):
    ag, model, _ = make(real_service, [("text", "a"), ("text", "b"), ("text", "c")])
    r = ag.ask(Q)
    assert sum(1 for t in user_texts(r) if t.startswith("[CONTRÔLE")) == 1 and model.i == 2


def test_factual_question_without_risk_wording_is_not_relaunched(real_service):
    ag, _, _ = make(real_service, [("tools", [EV]), ("text", "NVDA pèse 25 %.")])
    r = ag.ask("Quel est le poids de NVDA dans mon portefeuille ?")
    assert not needs_guardian("Quel est le poids de NVDA dans mon portefeuille ?")
    assert not r.relaunched and r.confirmed and [c.tool for c in r.calls] == [EV]


# ---------------------------------------------------------------- doublons, anciennes requêtes, contexte figé
def test_identical_calls_are_not_recomputed_and_the_reuse_is_traced(real_service):
    ag, _, _ = make(real_service, [("tools", [CK, CK]), ("tools", [CK]), ("text", "Réponse.")])
    r = ag.ask(Q)
    assert len(r.calls) == 3 and r.computed == 1
    first = r.calls[0]
    assert all(c.reused_from == first.id and c.result is first.result for c in r.calls[1:])
    assert len({c.tool_use_id for c in r.calls}) == 3 and r.provenance_ok


class MutatingModel(StepModel):
    def __init__(self, steps, ctx_holder):
        super().__init__(steps)
        self.ctx_holder = ctx_holder

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.ctx_holder[0].weights = {"XBB.TO": 1.0}           # l'utilisateur change de portefeuille pendant la requête
        async for ev in super().stream(messages, tool_specs, system_prompt, **kw):
            yield ev


def test_results_never_come_from_a_portfolio_selected_after_the_request_started_nor_from_a_previous_request(real_service):
    holder = []
    model = MutatingModel([("tools", [EV]), ("text", "a"), ("tools", [EV]), ("text", "b")], holder)
    ag, _, ctx = make(real_service, [], model=model)
    holder.append(ctx)
    r1 = ag.ask("Quelle est la composition de mon portefeuille ?")
    assert r1.calls[0].result["weights_pct"]["NVDA"] == 25.0
    r2 = ag.ask("Quelle est la composition de mon portefeuille ?")
    assert r2.request_id == 2 and [c.request_id for c in r2.calls] == [2]
    assert r2.calls[0].reused_from is None and r2.calls[0].result["weights_pct"] == {"XBB.TO": 100.0}


# ---------------------------------------------------------------- erreurs d'outils, profil non autorisé, B absent, refus du modèle
def test_tool_failure_is_visible_and_the_guardian_requirement_stays_unmet(real_service):
    ag, _, _ = make(real_service, [("tools", [CK]), ("text", "a"), ("tools", [CK]), ("text", "b")], fail=(CK,))
    r = ag.ask(Q)
    assert all(c.status == "error" and "Panne simulée" in c.error for c in r.calls)
    assert r.relaunched and not r.confirmed and r.notice == UNCONFIRMED


def test_model_cannot_use_a_profile_the_user_did_not_name(real_service):
    ag, _, _ = make(real_service, [("tools", [CK]), ("text", "a"), ("text", "b")], tool_args={CK: {"profile_id": "robert"}})
    r = ag.ask(Q)
    assert r.calls[0].status == "error" and "n'est pas autorisé" in r.calls[0].error and not r.confirmed


def test_comparison_without_portfolio_b_is_an_error_not_an_invented_result(real_service):
    ag, _, _ = make(real_service, [("tools", [CMP]), ("text", "Aucun portefeuille B.")])
    r = ag.ask("Compare A et B.")
    assert r.calls[0].status == "error" and "portefeuille B" in r.calls[0].error and r.notice.startswith("Au moins un outil a échoué")


class FailingModel(StepModel):
    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        raise RuntimeError("ThrottlingException: Rate exceeded")
        yield  # pragma: no cover


def test_generation_failure_returns_no_text_and_an_explicit_notice(real_service):
    ag, _, _ = make(real_service, [], model=FailingModel([]))
    r = ag.ask(Q)
    assert r.text is None and not r.confirmed and r.error and r.notice.startswith("La génération a échoué")


def test_system_prompt_is_short_and_has_no_preexecuted_data(real_service):
    ag, model, _ = make(real_service, [("tools", [CK]), ("text", "Réponse.")])
    ag.ask(Q)
    assert len(SYSTEM_PROMPT_V5) < 2600
    assert "NVDA" not in model.prompts[0] and "%" not in model.prompts[0]          # le message initial ne contient aucune donnée calculée

