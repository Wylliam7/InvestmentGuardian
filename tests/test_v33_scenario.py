"""V3.3 (stabilisation) : questions conditionnelles (« si tel actif baissait… »), catégories d'actifs et statuts identifiés par leur code (R1…R7).
Aucun scénario, aucune probabilité, aucune corrélation et aucune perte future ne sont calculés : on montre seulement les expositions connues.
"""
from types import SimpleNamespace as NS

import pytest
from conftest import StepModel

pytestmark = pytest.mark.legacy_ui

from guardian.agent.agent import SYSTEM_PROMPT, GuardianAgent
from guardian.agent.claims import check_claims
from guardian.agent.fallback import SCENARIO_LIMIT, build_fallback, cited_assets, verified_facts
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.finance.presets import load_presets
from test_v2_app import patch_model, run_app

P = load_presets()
W = {k: {t: v / 100 for t, v in P[k]["weights_pct"].items()} for k in P}
EV, CK = "evaluate_portfolio", "check_profile_constraints"
Q_AMIRA = "Si Nvidia et Bitcoin baissaient fortement en même temps, qu'est-ce que cela pourrait signifier pour mon portefeuille ?"


def recs(service, preset, pid, tools=(EV,)):
    t = {x.tool_spec["name"]: x for x in build_tools(service, SessionContext(W[preset], pid), Tracer())}
    return [NS(tool=n, status="ok", result=t[n](), id=i + 1) for i, n in enumerate(tools)]


def verdict(service, text, rr, pid):
    return check_claims(text, rr, service.profiles, pid, service.bundle.universe)


def cats(rep):
    return {v.category for v in rep.violations}


# ============================================================ actifs cités dans une question conditionnelle
def test_amira_conditional_question_shows_known_exposures_and_what_cannot_be_concluded(real_service):
    rr = recs(real_service, "amira_tech_crypto", "amira")
    lines = cited_assets(Q_AMIRA, rr)
    assets = {a["ticker"]: a for a in rr[0].result["assets"]}
    assert lines[0].startswith("NVDA (NVIDIA, action individuelle) : 25 % du portefeuille")
    assert lines[1].startswith("BTC-USD (Bitcoin, cryptoactif) : 20 % du portefeuille")
    for line, t in ((lines[0], "NVDA"), (lines[1], "BTC-USD")):
        assert f"{assets[t]['annualized_volatility_pct']:.1f}".replace(".", ",") in line and f"{assets[t]['max_drawdown_pct']:.1f}".replace(".", ",") in line
    assert lines[2] == "Poids combiné des actifs cités : 45 % du portefeuille (somme de leurs poids actuels, pas une perte)."
    assert lines[3] == SCENARIO_LIMIT and "ni probabilité, ni corrélation" in SCENARIO_LIMIT and "ni perte future" in SCENARIO_LIMIT


@pytest.mark.parametrize("preset,pid,question,expected", [
    ("robert_nvda_40", "robert", "Et si Nvidia chutait de moitié l'an prochain, que deviendrait mon portefeuille ?", ["NVDA"]),
    ("mateo_actions_canadiennes", "mateo", "Si CNQ et TD reculaient fortement, quel serait l'effet sur mon portefeuille ?", ["TD.TO", "CNQ.TO"]),
    ("amira_tech_crypto", "amira", "Que se passerait-il si le Bitcoin et l'Ether s'effondraient ?", ["BTC-USD", "ETH-USD"]),
])
def test_conditional_questions_for_the_three_personas_cite_only_portfolio_assets(real_service, preset, pid, question, expected):
    lines = cited_assets(question, recs(real_service, preset, pid))
    assert [x.split(" ")[0] for x in lines[:len(expected)]] == expected and lines[-1] == SCENARIO_LIMIT
    assert ("Poids combiné" in lines[-2]) == (len(expected) > 1)


@pytest.mark.parametrize("question", [
    "Quelle est la volatilité de NVDA ?",                                                          # pas de condition
    "Si Apple baissait fortement, que se passerait-il ?",                                          # actif absent du portefeuille
    "Comment se compare mon portefeuille au marché ?",
])
def test_no_scenario_block_without_a_conditional_question_on_held_assets(real_service, question):
    assert cited_assets(question, recs(real_service, "amira_tech_crypto", "amira")) == []


def test_scenario_block_leads_the_fallback_and_appears_in_the_verified_section(real_service):
    rr = recs(real_service, "amira_tech_crypto", "amira")
    fb = build_fallback(rr, Q_AMIRA)
    first = fb.split("\n\n")[1]
    assert first.startswith("**Actifs cités dans votre question (expositions actuelles, aucun scénario calculé)**") and SCENARIO_LIMIT in first
    titles = [t for t, _ in verified_facts(rr, Q_AMIRA)]
    assert titles[2] == "Actifs cités dans la question (expositions actuelles, aucun scénario calculé)"
    assert "Actifs cités" not in " ".join(t for t, _ in verified_facts(rr, "Quelle est ma volatilité ?"))


def test_withheld_scenario_answer_shows_the_scenario_facts(real_service):
    bad = "Actions : 45 % (dont 25 % en FNB QQQ). R1 → OK avec 25 %, seuil d'attention > 20 %."                 # erreurs observées en test manuel
    model = StepModel([("tools", [EV]), ("text", bad)])
    tr = GuardianAgent(real_service, SessionContext(W["amira_tech_crypto"], "amira"), Tracer(), model_factory=lambda: model).ask(Q_AMIRA)
    assert tr.withheld and {"categorie_actif", "statut_guardian"} <= {v["category"] for v in tr.claims["violations"]}
    assert "Poids combiné des actifs cités : 45 % du portefeuille" in tr.fallback and SCENARIO_LIMIT in tr.fallback


def test_page_shows_the_scenario_block_in_the_verified_section(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV]), ("text", "Je ne peux pas estimer l'effet d'une baisse simultanée : le prototype ne calcule pas de scénario.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    at.selectbox(key="preset_A").set_value("amira_tech_crypto").run()
    at.text_area(key="q_text").set_value(Q_AMIRA)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    exp = [e for e in at.expander if e.label.startswith("Faits et contrôles vérifiés")]
    inside = " ".join(m.value for m in exp[0].markdown)
    assert "Actifs cités dans la question" in inside and "Poids combiné des actifs cités : 45 %" in inside and "ni perte future" in inside
    assert "aucun statut évalué" in inside


def test_prompt_states_the_hypothetical_rule_once_and_briefly():
    rule = SYSTEM_PROMPT.split("15. CONTRAT D'EXPLICATION.")[1]
    assert "Question hypothétique : donne seulement les expositions connues ; aucun scénario, probabilité, corrélation ni perte future n'est calculé." in rule


# ============================================================ catégories d'actifs
@pytest.mark.parametrize("tools", [(EV,), (EV, CK)])
def test_an_etf_counted_inside_individual_stocks_is_rejected(real_service, tools):
    rr = recs(real_service, "amira_tech_crypto", "amira", tools)
    assert "categorie_actif" in cats(verdict(real_service, "Actions : 45 % (dont 25 % en FNB QQQ).", rr, "amira"))          # erreur observée
    assert "categorie_actif" in cats(verdict(real_service, "Cryptoactifs : 30 % (dont 25 % en NVDA).", rr, "amira"))
    for ok in ("Actions individuelles : 45 % (dont 25 % en NVDA).", "Cryptoactifs : 30 % (dont 20 % en BTC-USD).", "FNB d'actions : 25 % (QQQ).",
               "Actions individuelles : 45 % ; FNB d'actions : 25 % ; cryptoactifs : 30 %."):
        rep = verdict(real_service, ok, rr, "amira")
        assert rep.ok, (ok, [v.to_dict() for v in rep.violations])


def test_key_facts_give_the_engine_class_breakdown_with_members(real_service):
    ev = recs(real_service, "amira_tech_crypto", "amira")[0].result
    cl = {c["classe"]: c for c in ev["key_facts"]["répartition_par_classe"]["classes"]}
    assert cl["actions individuelles"]["pct"] == ev["asset_class_exposure_pct"]["equity"] == 45.0 and set(cl["actions individuelles"]["titres"]) == {"NVDA", "TSLA", "SHOP.TO"}
    assert cl["FNB d'actions"]["titres"] == ["QQQ"] and cl["cryptoactifs"]["pct"] == 30.0
    assert "ne sont pas inclus dans les actions individuelles" in ev["key_facts"]["répartition_par_classe"]["note"]


# ============================================================ statuts : codes de règle, avec et sans Guardian Check
@pytest.mark.parametrize("tools,field", [((EV,), "status_derived"), ((EV, CK), "status_checked")])
def test_status_claims_by_rule_code_are_checked(real_service, tools, field):
    rr = recs(real_service, "amira_tech_crypto", "amira", tools)
    bad = verdict(real_service, "R1 → OK avec 25 %, seuil d'attention > 20 %.", rr, "amira")                        # erreur observée
    assert "statut_guardian" in cats(bad) and getattr(bad, field) == 1
    for ok in ("R1 → Attention avec 25 %, seuil d'attention > 20 %.", "R7 → OK (5,0 positions effectives, attention < 5).",
               "- **Plus grande position** : vigilance si > 20 %, conflit si > 35 %.",                                   # définition de repères, pas un statut
               "- **Nombre effectif de positions** : vigilance si < 5, conflit si < 3."):
        rep = verdict(real_service, ok, rr, "amira")
        assert "statut_guardian" not in cats(rep), (ok, [v.to_dict() for v in rep.violations])


def test_robert_and_mateo_rule_codes(real_service):
    rob = recs(real_service, "robert_nvda_40", "robert", (EV, CK))
    assert "statut_guardian" in cats(verdict(real_service, "R5 → OK : la plus forte baisse reste acceptable.", rob, "robert"))
    assert not cats(verdict(real_service, "R5 → Conflit (36,14 % > 25 %).", rob, "robert")) & {"statut_guardian"}
    mat = recs(real_service, "mateo_croissance_equilibree", "mateo", (EV, CK))
    assert "statut_guardian" in cats(verdict(real_service, "R4 : conflit.", mat, "mateo"))
    assert not cats(verdict(real_service, "R4 : OK.", mat, "mateo")) & {"statut_guardian"}


# ============================================================ réponses réelles (Bedrock, 2026-11-14) et faux positifs corrigés
LIVE = __import__("json").loads((__import__("pathlib").Path(__file__).parent / "golden" / "v33_live_scenario_answers.json").read_text(encoding="utf-8"))
LIVE_W = {"amira": "amira_tech_crypto", "robert": "robert_nvda_40"}
# (retenue attendue, catégories attendues). « avant » : prédictions de perte non détectées (limite documentée, voir claims.NOT_CHECKED).
LIVE_EXPECT = {"avant": (False, set()), "apres": (False, set()), "robert_apres": (True, {"statut_guardian"})}


@pytest.mark.parametrize("i", range(3))
def test_real_scenario_answers_get_the_reviewed_verdict(real_service, i):
    g = LIVE[i]
    rep = verdict(real_service, g["text"], recs(real_service, LIVE_W[g["persona"]], g["persona"], tuple(g["tools"])), g["persona"])
    held, cats_ = LIVE_EXPECT[g["label"]]
    assert (not rep.ok) == held and cats(rep) == cats_, [v.to_dict() for v in rep.violations]
    if g["label"] == "robert_apres":
        assert len(rep.violations) == 3 and rep.status_derived == 3          # ATTENTION au lieu de conflit (R1), OK au lieu de conflit (R7), « point de vigilance »


def test_values_of_an_asset_named_in_the_previous_sentence_are_attached_to_it(real_service):
    rr = recs(real_service, "robert_nvda_40", "robert")
    ok = ("Si NVIDIA chutait, cela toucherait 40 % du portefeuille. Historiquement, cette action a connu une volatilité de 50,71 % "
          "et une baisse maximale de -63,46 %.")
    assert verdict(real_service, ok, rr, "robert").ok
    assert not verdict(real_service, ok.replace("50,71", "45,2"), rr, "robert").ok
    two = "NVDA et XIU.TO pèsent ensemble 65 %. Historiquement, cette action a connu une volatilité de 50,71 %."          # deux titres : référence ambiguë
    # LIMITE DOCUMENTÉE : deux titres dans la phrase précédente, la reprise est ambiguë ; la valeur n'est pas rattachée et la phrase est refusée
    # (faux positif conservateur plutôt qu'une valeur acceptée au hasard).
    assert "valeur_associee" in cats(verdict(real_service, two, rr, "robert"))


def test_measured_value_next_to_a_threshold_is_accepted_without_guardian_check(real_service):
    rr = recs(real_service, "robert_nvda_40", "robert")
    rep = verdict(real_service, "Plus grande position : seuil d'attention > 10 %, seuil de conflit > 20 % → Conflit (40 % > 20 %).", rr, "robert")
    assert rep.ok and rep.status_derived == 1, [v.to_dict() for v in rep.violations]
    assert "statut_guardian" in cats(verdict(real_service, "Plus grande position : seuil de conflit > 20 % → ATTENTION (40 % > 20 %).", rr, "robert"))
