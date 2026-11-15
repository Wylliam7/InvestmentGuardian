"""Corrections finales V1 : (1) conflit de profil, (2) scénarios par profil, (3) lisibilité, (4) preuve de compare_scenarios."""
import tomllib

import pytest

pytestmark = pytest.mark.legacy_ui
from streamlit.testing.v1 import AppTest

from conftest import REPO, StepModel
from guardian.agent import agent as agent_mod
from guardian.agent.agent import GuardianAgent, clarification_message, profile_conflict, profiles_mentioned
from guardian.agent.tools import SessionContext
from guardian.agent.tracer import Tracer
from guardian.finance.presets import load_presets
from profile_flow import CUSTOM, EDITED, PRESET, loadable, matches_suggestion, plan_switch, slot_status

NVDA40 = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}
GP, EV, CK, CMP = "get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios"
P = load_presets()


# ============================================================ 1. conflit entre profil sélectionné et question
@pytest.mark.parametrize("question,named", [
    ("Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?", ["robert"]),
    ("Cette allocation est-elle adaptée à AMIRA ?", ["amira"]),
    ("Compare pour Robert et pour Amira.", ["robert", "amira"]),
    ("Pourquoi ce portefeuille est-il risqué ?", []),
    ("Et pour Róbert ?", ["robert"]),                       # accents ignorés
    ("Roberto et Amirah n'existent pas.", []),               # mots entiers seulement
])
def test_profiles_mentioned(real_service, question, named):
    assert profiles_mentioned(question, real_service.profiles) == named


@pytest.mark.parametrize("question,active,conflict", [
    ("Pourquoi risqué pour Robert ?", "robert", False),
    ("Pourquoi risqué pour Robert ?", "amira", True),
    ("Adapté à Amira ?", "robert", True),
    ("Adapté à Amira ?", "amira", False),
    ("Compare pour Robert et Amira", "amira", False),          # le profil actif est nommé : l'autre est demandé explicitement
    ("Compare pour Robert et Amira", "robert", False),
    ("Pourquoi ce portefeuille est-il risqué ?", "robert", False),   # aucun profil nommé : profil actif
    ("Pourquoi ce portefeuille est-il risqué ?", "amira", False),
])
def test_profile_conflict_rule(real_service, question, active, conflict):
    assert (profile_conflict(question, active, real_service.profiles) is not None) is conflict


class NeverCalledModel:
    """Le modèle ne doit pas être créé : un conflit de profil ne doit déclencher aucun appel à Bedrock."""
    calls = 0

    def __call__(self):
        NeverCalledModel.calls += 1
        raise AssertionError("Le modèle ne devait pas être appelé")


def make_agent(service, active, steps=None, tool_args=None, weights_b=None):
    model = StepModel(steps or [("text", "Aucun outil nécessaire.")], tool_args)
    ctx = SessionContext(NVDA40, active, weights_b=weights_b)
    return GuardianAgent(service, ctx, Tracer(), model_factory=lambda: model), model, ctx


@pytest.mark.parametrize("active,question,asked", [
    ("amira", "Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?", ["robert"]),
    ("robert", "Cette allocation serait-elle évaluée différemment pour Amira ?", ["amira"]),
])
def test_conflicting_question_asks_for_clarification_without_any_model_or_tool_call(real_service, active, question, asked):
    NeverCalledModel.calls = 0
    ctx = SessionContext(NVDA40, active)
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=NeverCalledModel())
    tr = ag.ask(question)
    assert NeverCalledModel.calls == 0 and ag._agent is None                      # aucun agent Strands ni appel Bedrock
    assert tr.clarification and tr.text is None and tr.tool_records == [] and not tr.withheld and tr.error is None
    assert tr.clarification_profiles == tuple(asked)
    assert real_service.profiles[asked[0]]["display_name"] in tr.clarification and real_service.profiles[active]["display_name"] in tr.clarification
    assert "Aucune analyse n'a été lancée" in tr.clarification
    assert tr.context["profile_id"] == active and tr.turn == 1 and ag.tracer.records == []


def test_clarification_text_names_the_two_ways_out(real_service):
    msg = clarification_message({"named": ["robert"], "active": "amira"}, real_service.profiles)
    assert "Sélectionnez Robert" in msg and "reformulez votre question pour Amira" in msg


def test_question_matching_active_profile_is_analysed_normally(real_service):
    ag, model, ctx = make_agent(real_service, "robert", [("tools", [CK]), ("text", "Interprétation : volatilité de 22,3 %.")])
    tr = ag.ask("Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?")
    assert tr.clarification is None and not tr.withheld and tr.tool_records[0].status == "ok"
    assert tr.tool_records[0].result["profile_id"] == "robert" and ctx.allowed_profiles == {"robert"}


def test_question_without_profile_uses_the_selected_profile(real_service):
    for active in ("robert", "amira"):
        ag, _, ctx = make_agent(real_service, active, [("tools", [CK]), ("text", "Interprétation : volatilité de 22,3 %.")])
        tr = ag.ask("Pourquoi ce portefeuille est-il risqué ?")
        assert tr.clarification is None and tr.tool_records[0].result["profile_id"] == active and ctx.allowed_profiles == {active}


def test_explicitly_named_other_profile_is_allowed_alongside_the_active_one(real_service):
    ag, _, ctx = make_agent(real_service, "robert", [("tools", [CK]), ("text", "Comparaison : volatilité de 22,3 %.")],
                            tool_args={CK: {"profile_id": "amira"}})
    tr = ag.ask("Compare l'évaluation pour Robert et pour Amira.")
    assert ctx.allowed_profiles == {"robert", "amira"}
    assert tr.tool_records[0].status == "ok" and tr.tool_records[0].result["profile_id"] == "amira" and not tr.withheld


def test_model_cannot_pick_another_profile_on_its_own(real_service):
    """Le modèle demande Amira alors que l'utilisateur n'a pas nommé Amira et que Robert est sélectionné : refus côté outil."""
    ag, _, _ = make_agent(real_service, "robert", [("tools", [CK]), ("text", "La volatilité est de 22,3 %.")], tool_args={CK: {"profile_id": "amira"}})
    tr = ag.ask("Pourquoi ce portefeuille est-il risqué ?")
    rec = tr.tool_records[0]
    assert rec.status == "error" and "n'est pas autorisé" in rec.error and rec.arguments["profile_id"] == "amira"
    assert tr.withheld and tr.text is None


def test_allowed_profiles_are_rebuilt_for_every_request(real_service):
    ag, _, ctx = make_agent(real_service, "robert", [("tools", [CK]), ("text", "ok 1."), ("tools", [CK]), ("text", "ok 2.")],
                            tool_args={CK: {"profile_id": "amira"}})
    t1 = ag.ask("Compare pour Robert et Amira.")                    # Amira nommée : autorisée
    t2 = ag.ask("Et maintenant ?")                                   # plus nommée : refusée, pas de droit hérité de la requête 1
    assert t1.tool_records[0].status == "ok" and t2.tool_records[0].status == "error" and ctx.allowed_profiles == {"robert"}


def test_context_note_lists_allowed_profiles(real_service):
    ag, _, _ = make_agent(real_service, "robert")
    assert "Profils autorisés pour cette requête : amira, robert" in ag.compose_prompt("Compare Robert et Amira")
    assert "Profils autorisés pour cette requête : robert " in ag.compose_prompt("Question sans profil")


def run_app():
    return AppTest.from_file(str(REPO / "app" / "app.py"), default_timeout=90).run()


def patch_model(monkeypatch, steps=None):
    model = StepModel(steps or [("text", "Ne devrait pas être appelé.")])
    original = agent_mod.GuardianAgent.__init__

    def patched(self, *a, **kw):
        kw["model_factory"] = lambda: model
        original(self, *a, **kw)
    monkeypatch.setattr(agent_mod.GuardianAgent, "__init__", patched)
    return model


def ask(at, q):
    at.text_area[0].set_value(q)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    return at.run()


def test_ui_conflict_shows_clarification_and_one_click_profile_selection(monkeypatch):
    model = patch_model(monkeypatch)
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    ask(at, "Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?")
    assert not at.exception, at.exception
    assert any("Sélectionnez Robert" in w.value and "Aucune analyse n'a été lancée" in w.value for w in at.warning), [w.value for w in at.warning]
    assert model.i == 0 and at.session_state.agent.tracer.records == []                    # aucun appel au modèle ni aux outils
    btn = [b for b in at.button if b.label == "Sélectionner Robert"]
    assert btn, [b.label for b in at.button]
    btn[0].click()
    at.run()
    assert at.selectbox(key="profile_id").value == "robert" and at.session_state.ctx.profile_id == "robert"


# ============================================================ 2. scénarios par profil sans écrasement
def test_slot_status_and_switch_planning_pure_logic():
    intact = {"preset": "robert_nvda_40", "applied_pct": P["robert_nvda_40"]["weights_pct"], "dirty": False}
    assert slot_status(intact, P) == PRESET
    assert slot_status({**intact, "dirty": True}, P) == EDITED
    assert slot_status({**intact, "preset": "custom"}, P) == CUSTOM
    assert slot_status({**intact, "applied_pct": {"NVDA": 50, "XBB.TO": 50}}, P) == CUSTOM          # préréglage modifié puis appliqué
    assert plan_switch({"A": PRESET, "B": PRESET}, touched=False) == "auto_load"
    assert plan_switch({"A": PRESET, "B": PRESET}, touched=True) == "suggest"
    assert plan_switch({"A": CUSTOM, "B": PRESET}, touched=False) == "suggest"
    assert plan_switch({"A": EDITED, "B": PRESET}, touched=False) == "suggest"
    assert loadable({"A": CUSTOM, "B": PRESET}) == ["B"] and loadable({"A": EDITED, "B": CUSTOM}) == []
    d = {"a": "amira_tech_crypto", "b": "amira_croissance"}
    assert matches_suggestion({"A": {"preset": "amira_tech_crypto"}, "B": {"preset": "amira_croissance"}}, d)
    assert not matches_suggestion({"A": {"preset": "robert_nvda_40"}, "B": {"preset": "amira_croissance"}}, d)


def test_profile_defaults_config_points_to_matching_presets(real_service):
    from guardian.finance.presets import load_profile_defaults, validate_profile_defaults
    d = load_profile_defaults()
    validate_profile_defaults(d, P, real_service.profiles)
    for pid, ab in d.items():
        assert P[ab["a"]]["profile_id"] == pid and P[ab["b"]]["profile_id"] == pid


def test_untouched_session_loads_default_scenarios_of_the_new_profile_and_can_revert():
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    assert not at.exception, at.exception
    s = at.session_state.slots
    assert s["A"]["preset"] == "amira_tech_crypto" and s["B"]["preset"] == "amira_croissance"
    assert at.session_state.ctx.weights == {t: v / 100 for t, v in P["amira_tech_crypto"]["weights_pct"].items()}
    assert any("Scénarios par défaut de **Amira** chargés" in i.value for i in at.info)
    [b for b in at.button if "Revenir à mon allocation précédente" in b.label][0].click()
    at.run()
    assert at.session_state.slots["A"]["preset"] == "robert_nvda_40" and at.session_state.slots["B"]["preset"] == "robert_prudent"
    assert at.selectbox(key="profile_id").value == "amira"                               # on peut évaluer l'allocation de Robert pour Amira
    assert at.session_state.ctx.profile_id == "amira" and at.session_state.ctx.weights == NVDA40


def test_explicit_choice_is_never_replaced_automatically_only_proposed():
    at = run_app()
    at.selectbox(key="preset_A").set_value("robert_prudent").run()                       # l'utilisateur choisit
    before = at.session_state.slots["A"]["applied_pct"]
    at.selectbox(key="profile_id").set_value("amira").run()
    assert at.session_state.slots["A"]["applied_pct"] == before and at.session_state.slots["A"]["preset"] == "robert_prudent"
    assert any("Scénarios suggérés pour Amira" in i.value and "rien n'a été remplacé" in i.value for i in at.info)
    [b for b in at.button if "Charger les scénarios suggérés pour Amira" in b.label][0].click()      # action explicite
    at.run()
    assert at.session_state.slots["A"]["preset"] == "amira_tech_crypto" and at.session_state.slots["B"]["preset"] == "amira_croissance"


def test_custom_portfolio_is_never_overwritten_even_by_the_explicit_load():
    at = run_app()
    at.selectbox(key="preset_A").set_value("custom").run()
    mine = dict(at.session_state.slots["A"]["applied_pct"])
    at.selectbox(key="profile_id").set_value("amira").run()
    assert at.session_state.slots["A"]["preset"] == "custom" and at.session_state.slots["B"]["preset"] == "robert_prudent"
    [b for b in at.button if "Charger les scénarios suggérés" in b.label][0].click()
    at.run()
    s = at.session_state.slots
    assert s["A"]["preset"] == "custom" and s["A"]["applied_pct"] == mine                  # intact
    assert s["B"]["preset"] == "amira_croissance"                                          # l'emplacement non personnalisé a été chargé
    assert any("conservé(s)" in i.value and "A" in i.value for i in at.info)


def test_dirty_slot_is_protected_like_a_custom_one():
    """Un emplacement dont la saisie diffère des poids analysés (édition en cours) n'est jamais écrasé."""
    at = run_app()
    s = at.session_state.slots
    s["A"]["dirty"] = True                                                                 # état calculé par l'éditeur à chaque rendu
    s["B"]["dirty"] = False
    at.session_state.touched = True
    at.selectbox(key="profile_id").set_value("amira").run()
    assert at.session_state.slots["A"]["preset"] == "robert_nvda_40"                       # pas remplacé


def test_any_allocation_can_be_evaluated_for_any_profile(real_service):
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    at.selectbox(key="preset_A").set_value("robert_nvda_40").run()
    assert at.session_state.ctx.profile_id == "amira" and at.session_state.ctx.weights == NVDA40
    r = real_service.analyze(NVDA40)
    assert {m.label: m.value for m in at.metric}["Fluctuations du portefeuille"] == f"{100 * r.volatility:.1f}".replace(".", ",") + " %"


def test_preset_menu_lists_the_selected_profile_scenarios_first_with_a_marker():
    at = run_app()
    opts = at.selectbox(key="preset_A").options
    assert opts[0].startswith("★ Robert") and opts[1].startswith("★ Robert") and not opts[2].startswith("★")
    at.selectbox(key="profile_id").set_value("amira").run()
    assert at.selectbox(key="preset_A").options[0].startswith("★ Amira")


def test_replaced_slots_get_a_new_editor_version_so_old_edits_cannot_reappear():
    at = run_app()
    v0 = at.session_state.slots["A"]["ver"]
    at.selectbox(key="profile_id").set_value("amira").run()
    assert at.session_state.slots["A"]["ver"] > v0
    v1 = at.session_state.slots["A"]["ver"]
    at.selectbox(key="preset_A").set_value("robert_prudent").run()
    assert at.session_state.slots["A"]["ver"] > v1


# ============================================================ 3. lisibilité
def test_theme_and_layout_for_readability():
    cfg = tomllib.loads((REPO / ".streamlit" / "config.toml").read_text())["theme"]
    assert cfg["baseFontSize"] >= 16 and float(cfg["headingFontSizes"][0].rstrip("rem")) >= 3.0
    src = (REPO / "app" / "app.py").read_text(encoding="utf-8")
    assert 'layout="wide"' in src and "max-width: 100%" in src and "1250px" not in src
    assert "font-size: 3.4rem" in src and 'st.title("🛡️ Investment Guardian")' in src
    assert not any(w in (REPO / ".streamlit" / "config.toml").read_text().lower() for w in ("secret", "token", "password"))


def test_title_and_subtitle_are_rendered():
    at = run_app()
    assert at.title[0].value == "🛡️ Investment Guardian"
    assert any("Comprenez les risques de vos décisions d'investissement." in m.value and "ig-sub" in m.value for m in at.markdown)
    assert any("Your decisions. Your risks. Explained." in c.value for c in at.caption)


# ============================================================ 4. preuve de compare_scenarios dans l'interface
def test_ui_shows_real_proof_when_compare_scenarios_was_called(monkeypatch):
    patch_model(monkeypatch, [("tools", [CMP]), ("text", "Compromis historiques entre rendement et risque.")])
    at = run_app()
    ask(at, "Pour Robert, compare le portefeuille contenant 40 % de NVDA avec une allocation plus diversifiée.")
    assert not at.exception, at.exception
    recs = at.session_state.agent.tracer.records
    assert [(r.tool, r.status) for r in recs] == [(CMP, "ok")]
    assert any("compare_scenarios : appelé avec succès" in s.value and f"appel n° {recs[0].id}" in s.value for s in at.success)
    md = " ".join(m.value for m in at.markdown)
    assert f"`compare_scenarios` · appel n° {recs[0].id}" in md and "✅" in md
    assert any(e.label == "Voir les détails techniques de l'analyse" for e in at.expander)          # V2 : trace technique dans une section repliée
    assert any(f"#{recs[0].id} · requête 1 · compare_scenarios" in m.value for m in at.markdown)    # ligne de la trace réelle


def test_ui_never_claims_compare_scenarios_when_it_was_not_called(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV]), ("text", "Interprétation : volatilité de 22,3 %.")])
    at = run_app()
    ask(at, "Pour Robert, compare le portefeuille contenant 40 % de NVDA avec une allocation plus diversifiée.")
    assert not at.exception, at.exception
    assert [r.tool for r in at.session_state.agent.tracer.records] == [EV]
    assert not any("compare_scenarios : appelé" in s.value for s in at.success)
    assert any("compare_scenarios : non appelé pendant cette requête" in c.value for c in at.caption)
    assert not any(f"requête 1 · compare_scenarios" in m.value for m in at.markdown)


def test_ui_reports_a_failed_compare_scenarios_call(monkeypatch):
    patch_model(monkeypatch, [("tools", [CMP]), ("text", "Le portefeuille A est meilleur : 22,3 %.")])
    at = run_app()
    at.checkbox(key="use_b").uncheck().run()                                              # pas de portefeuille B : l'outil échoue
    ask(at, "Compare A et B pour Robert.")
    assert not at.exception, at.exception
    assert any("compare_scenarios : appelé mais en échec" in e.value for e in at.error)
    assert any("Analyse incomplète" in w.value for w in at.warning)
    assert not any("compare_scenarios : appelé avec succès" in s.value for s in at.success)
