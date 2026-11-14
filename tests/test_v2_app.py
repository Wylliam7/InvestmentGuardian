"""V2 — interface : confirmation d'analyse, sidebar simplifiée, bouton IA, traces à deux niveaux, mode sans Bedrock, absence de secrets."""
import os
import re

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from conftest import REPO, StepModel, V2_MAIN_LABELS, v2_expected_metrics
from guardian.agent import agent as agent_mod
from guardian.agent.service import GuardianService
from guardian.explain.summary import build_priority_summary
from guardian.finance.presets import load_presets

GP, EV, CK, CMP = "get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios"
NVDA40 = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}


def run_app():
    return AppTest.from_file(str(REPO / "app" / "app.py"), default_timeout=90).run()


def patch_model(monkeypatch, steps=None, tool_args=None):
    model = StepModel(steps or [("text", "Ne devrait pas être appelé.")], tool_args)
    original = agent_mod.GuardianAgent.__init__

    def patched(self, *a, **kw):
        kw["model_factory"] = lambda: model
        original(self, *a, **kw)
    monkeypatch.setattr(agent_mod.GuardianAgent, "__init__", patched)
    return model


def click(at, key):
    at.button(key=key).click()
    return at.run()


def all_text(at) -> str:
    parts = []
    for coll in (at.markdown, at.caption, at.text, at.info, at.success, at.warning, at.error, at.code, at.json, at.exception):
        parts += [str(getattr(e, "value", "")) for e in coll]
    parts += [e.label for e in at.expander] + [m.label + " " + str(m.value) for m in at.metric] + [b.label for b in at.button]
    parts += [str(df.value.to_string()) for df in at.dataframe if isinstance(df.value, pd.DataFrame)]
    return "\n".join(parts)


# ============================================================ 1-2. chargement, validation et confirmation visible de l'analyse
def test_analysis_button_shows_a_clear_confirmation_without_calling_bedrock(monkeypatch):
    model = patch_model(monkeypatch)
    at = run_app()
    assert not any("a été analysé" in s.value for s in at.success)                       # pas de confirmation avant tout clic
    click(at, "apply_A")
    assert not at.exception, at.exception
    msgs = [s.value for s in at.success if "a été analysé" in s.value]
    assert msgs == ["Votre portefeuille A a été analysé. Consultez l'onglet « Comprendre mes risques » pour découvrir les résultats."]
    assert any("Pondérations réellement analysées" in m.value and "NVDA 40 %" in m.value and "XBB.TO 35 %" in m.value for m in at.markdown)
    assert model.i == 0 and at.session_state.agent.tracer.records == [] and at.session_state.agent._agent is None   # aucun appel à Bedrock


def test_confirmation_names_the_portfolio_that_was_analysed():
    at = run_app()
    click(at, "apply_B")
    msgs = [s.value for s in at.success if "a été analysé" in s.value]
    assert msgs == ["Votre portefeuille B a été analysé. Consultez l'onglet « Comprendre mes risques » pour découvrir les résultats."]


def test_confirmation_disappears_when_the_analysed_weights_change():
    at = run_app()
    click(at, "apply_A")
    assert any("a été analysé" in s.value for s in at.success)
    at.selectbox(key="preset_A").set_value("robert_prudent").run()
    assert not any("a été analysé" in s.value for s in at.success)


def test_no_success_message_when_the_weights_are_invalid():
    at = run_app()
    s = at.session_state.slots["A"]
    s["df"] = pd.DataFrame([{"ticker": "NVDA", "weight_pct": 50.0}])                       # total de 50 % : invalide
    s["ver"] += 1
    at.run()
    assert at.button(key="apply_A").disabled
    assert any("La somme des poids vaut 50.00 %" in e.value for e in at.error)
    assert not any("a été analysé" in x.value for x in at.success)
    assert at.session_state.slots["A"]["applied_pct"] == {"NVDA": 40, "XBB.TO": 35, "XIU.TO": 25}      # les poids analysés n'ont pas bougé


def test_no_success_message_when_the_calculation_fails(monkeypatch):
    flag = {"fail": False}
    original = GuardianService.check

    def flaky(self, weights, profile_id, start=None, end=None):
        if flag["fail"]:
            raise ValueError("calcul indisponible (test)")
        return original(self, weights, profile_id, start, end)
    monkeypatch.setattr(GuardianService, "check", flaky)
    at = run_app()
    flag["fail"] = True
    at.button(key="apply_A").click()
    at.run()
    assert any("L'analyse a échoué" in e.value for e in at.error)
    assert not any("a été analysé" in s.value for s in at.success)
    assert at.session_state.analysis_ok is None


# ============================================================ structure, vocabulaire et aide
def test_four_tabs_with_plain_names_and_an_intro_sentence():
    at = run_app()
    labels = [t.label for t in at.tabs]
    for expected in ("1 · Mon portefeuille", "2 · Comprendre mes risques", "3 · Comparer deux choix", "4 · Assistant IA"):
        assert expected in labels
    md = " ".join(m.value for m in at.markdown)
    assert "Choisissez comment répartir votre argent fictif entre différents investissements." in md
    assert any(e.label == "Aide : comprendre les termes" for e in at.expander)
    helps = " ".join(m.value for m in at.markdown)
    for term in ("Actif", "Pondération", "FNB", "Allocation", "Portefeuille fictif"):
        assert f"**{term}**" in helps


def test_dashboard_leads_with_summary_then_alerts_then_four_plain_metrics(real_service):
    at = run_app()
    md = [m.value for m in at.markdown]
    i_sum = next(i for i, v in enumerate(md) if v.startswith("### À retenir en priorité"))
    i_alert = next(i for i, v in enumerate(md) if v.startswith("### Les alertes du Guardian Check"))
    i_nums = next(i for i, v in enumerate(md) if v.startswith("### Les chiffres à connaître"))
    i_hist = next(i for i, v in enumerate(md) if v.startswith("### L'évolution historique"))
    assert i_sum < i_alert < i_nums < i_hist
    labels = [m.label for m in at.metric if m.label in V2_MAIN_LABELS]
    assert labels == list(V2_MAIN_LABELS)
    assert {m.label: m.value for m in at.metric if m.label in V2_MAIN_LABELS} == v2_expected_metrics(real_service, NVDA40)
    assert any(e.label == "Voir plus de statistiques" for e in at.expander)
    assert not any(m.label in ("Indice HHI", "Top 3 positions") for m in at.metric)         # statistiques secondaires déplacées


def test_main_dashboard_cards_hide_jargon_and_expose_comprendre_ce_calcul():
    at = run_app()
    md = " ".join(m.value for m in at.markdown)
    assert "Votre portefeuille dépend beaucoup de NVIDIA." in md and "NVIDIA représente 40 % de votre argent fictif." in md
    assert "Risque important à examiner" in md
    labels = [e.label for e in at.expander]
    # 6 cartes dans « Comprendre mes risques », plus celles des deux onglets de détail de la comparaison A/B
    assert labels.count("Comprendre ce calcul") >= 6 and labels.count("Détails techniques (règle, seuils, version)") >= 6
    for pat in (r"#### R\d", r"\*\*R\d+ ·", r"Règle métier Python déterministe", r"max\(poids_i\)", r"[Ss]euil heuristique", r"Configuration 0\.2"):
        for m in at.markdown:
            if re.search(pat, m.value):                                                       # le jargon n'existe que dans les « Détails techniques » repliés
                assert m.value.startswith(("**R", "**Méthode.**", "**Justification.**", "**Limites (configuration).**")), (pat, m.value[:80])
    assert not any(re.match(r"#### R\d", m.value) for m in at.markdown)                        # aucun titre de carte du type « R1 »
    diversification = [c.value for c in at.caption if "Votre portefeuille contient 3 actifs" in c.value]
    assert diversification and "environ 2,9 positions de poids égal" in diversification[0]


# ============================================================ 7. Robert / Amira sans incohérence
def test_switching_profile_changes_interpretation_but_not_measures(real_service):
    at = run_app()
    at.selectbox(key="preset_A").set_value("robert_prudent").run()
    at.selectbox(key="preset_A").set_value("robert_nvda_40").run()
    before = {m.label: m.value for m in at.metric if m.label in V2_MAIN_LABELS}
    robert_summary = next(m.value for m in at.markdown if m.value.startswith("Pour Robert,"))
    at.selectbox(key="profile_id").set_value("amira").run()
    assert not at.exception, at.exception
    assert {m.label: m.value for m in at.metric if m.label in V2_MAIN_LABELS} == before
    res, rep = real_service.check(NVDA40, "amira")
    expected = build_priority_summary(res, rep, real_service.profiles["amira"], real_service.bundle.universe)
    shown = next(m.value for m in at.markdown if m.value.startswith("Pour Amira,"))
    assert shown == expected.intro and shown != robert_summary
    md = " ".join(m.value for m in at.markdown)
    assert "Amira a pour objectif : « Faire croître son capital à long terme. »" in md and "15 ans ou plus" in md


# ============================================================ 8-10. bouton « Explique-moi mes risques avec l'IA »
def explain_steps():
    return [("tools", [GP, EV, CK]), ("text", "**En bref** Interprétation de test sans chiffre.")]


def test_summary_and_page_render_never_call_the_model(monkeypatch):
    model = patch_model(monkeypatch)
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    at.selectbox(key="preset_A").set_value("amira_croissance").run()
    assert model.i == 0 and at.session_state.agent.tracer.records == [] and at.session_state.history == []
    assert any(m.value.startswith("### À retenir en priorité") for m in at.markdown)       # résumé généré sans IA


def test_explain_button_uses_the_active_profile_and_the_analysed_portfolio(monkeypatch):
    model = patch_model(monkeypatch, explain_steps())
    at = run_app()
    agent_before = at.session_state.agent
    click(at, "explain_btn")
    assert not at.exception, at.exception
    tr = at.session_state.history[-1]
    assert tr.kind == "explain_risks" and tr.question == "Explique-moi mes risques avec l'IA" and tr.turn == 1
    assert tr.context == {"profile_id": "robert", "weights_a_pct": {"NVDA": 40.0, "XBB.TO": 35.0, "XIU.TO": 25.0}, "weights_b_pct": tr.context["weights_b_pct"]}
    prompt = model.prompts[0]
    assert "TÂCHE" in prompt and "portefeuille A pour Robert" in prompt and "Profil actif : robert (Robert)" in prompt
    assert "NVDA" not in prompt and "40" not in prompt.split("Question de l'utilisateur")[0].replace("250", "")    # ni poids ni chiffres dans l'instruction
    by = {r.tool: r for r in tr.tool_records}
    assert sorted(by) == [CK, EV, GP] and all(r.status == "ok" and r.turn == 1 for r in tr.tool_records)
    assert by[EV].arguments["portfolio"] == "A" and by[EV].result["weights_pct"] == {"NVDA": 40.0, "XBB.TO": 35.0, "XIU.TO": 25.0}
    assert by[CK].result["profile_id"] == "robert"
    assert at.session_state.agent is agent_before and at.session_state.explain_turn is tr          # même agent : aucun second agent
    assert not tr.withheld and "Interprétation de test" in " ".join(m.value for m in at.markdown)


def test_explain_button_follows_profile_and_selected_portfolio(monkeypatch):
    model = patch_model(monkeypatch, explain_steps())
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()                                # scénarios par défaut d'Amira chargés
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    expected = {t: float(v) for t, v in load_presets()["amira_tech_crypto"]["weights_pct"].items()}
    assert tr.context["profile_id"] == "amira" and tr.context["weights_a_pct"] == expected
    by = {r.tool: r for r in tr.tool_records}
    assert by[CK].result["profile_id"] == "amira" and by[CK].result["weights_pct"] == expected and "portefeuille A pour Amira" in model.prompts[0]


def test_each_explain_click_is_an_independent_request_without_old_tool_calls(monkeypatch):
    model = patch_model(monkeypatch, explain_steps() + explain_steps())
    at = run_app()
    click(at, "explain_btn")
    first_ids = {r.id for r in at.session_state.history[-1].tool_records}
    click(at, "explain_btn")
    t1, t2 = at.session_state.history
    assert (t1.turn, t2.turn) == (1, 2) and first_ids.isdisjoint({r.id for r in t2.tool_records})
    assert {r.turn for r in t2.tool_records} == {2} and len(t2.tool_records) == 3
    assert model.seen[2] == [["text"]]                                                     # début de la requête 2 : aucun résultat d'outil ancien


def test_explain_answer_without_the_expected_tools_is_withheld(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV]), ("text", "Votre volatilité est de 22,3 %.")])         # check_profile_constraints jamais appelé
    at = run_app()
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    assert tr.withheld and tr.text is None and "check_profile_constraints" in tr.withheld_reason
    assert any("Analyse incomplète" in w.value for w in at.warning)
    assert "22,3 %" not in " ".join(m.value for m in at.markdown if "volatilité est de" in m.value)


def test_explain_with_a_failing_tool_keeps_the_engine_results_and_hides_the_model_text(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK]), ("text", "Votre volatilité est de 12,3 % (calcul direct).")])
    at = run_app()
    at.sidebar.checkbox(key="sim_fail_eval").check().run()
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    assert tr.withheld and {r.tool: r.status for r in tr.tool_records} == {EV: "error", CK: "ok"}
    assert "12,3" not in all_text(at)
    assert any("Analyse incomplète" in w.value and "evaluate_portfolio" in w.value for w in at.warning)
    assert any(m.value.startswith("### Les alertes du Guardian Check") for m in at.markdown)       # les résultats du moteur restent affichés
    assert len([m for m in at.metric if m.label in V2_MAIN_LABELS]) == 4


def test_explanation_is_hidden_when_the_profile_changes(monkeypatch):
    patch_model(monkeypatch, explain_steps())
    at = run_app()
    click(at, "explain_btn")
    assert any("Explication de l'assistant IA" in m.value for m in at.markdown)
    at.selectbox(key="profile_id").set_value("amira").run()
    assert not any("Explication de l'assistant IA" in m.value for m in at.markdown)
    assert any("concernait un autre profil ou un autre portefeuille" in i.value for i in at.info)


def test_facts_used_come_from_the_tool_results_not_from_the_model_text(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK]), ("text", "**En bref** Texte libre du modèle.")])
    at = run_app()
    click(at, "explain_btn")
    md = " ".join(m.value for m in at.markdown)
    assert "Faits historiques utilisés (valeurs calculées par le moteur)" in md
    assert "Rendement historique cumulé : 180,9 %" in md and "Fluctuations annualisées : 22,3 %" in md and "Plus forte baisse historique : -36,1 %" in md
    assert "Plus grande position : NVDA (40 %) · environ 2,9 positions de poids égal" in md


# ============================================================ 11-12. traces à deux niveaux
def test_level1_is_plain_and_only_lists_tools_that_really_ran(monkeypatch):
    patch_model(monkeypatch, [("tools", [CMP]), ("text", "Compromis historiques.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("robert").run()
    at.text_area[0].set_value("Compare A et B pour Robert.")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    md = " ".join(m.value for m in at.markdown)
    assert "Comment l'assistant a-t-il obtenu cette réponse ?" in md
    assert "A comparé les deux allocations A et B sur la même période pour Robert." in md
    assert "A analysé votre portefeuille" not in md and "profil officiel" not in md.split("Comment l'assistant")[1].split("détails techniques")[0]   # pas d'outil non exécuté
    assert "Période historique : du 2021-11-12 au 2026-11-12" in md and "Devise : dollar canadien (CAD)" in md and "Yahoo Finance" in md
    assert "interprétation" in md and not re.search(r"entièrement vérifi|totalement vérifi", md, re.I)


def test_level2_keeps_the_full_technical_trace_in_a_closed_section(monkeypatch):
    patch_model(monkeypatch, explain_steps())
    at = run_app()
    click(at, "explain_btn")
    exp = [e for e in at.expander if e.label == "Voir les détails techniques de l'analyse"]
    assert exp and all(e.proto.expanded is False for e in exp)                             # fermé par défaut
    recs = at.session_state.agent.tracer.records
    md = " ".join(m.value for m in at.markdown)
    for r in recs:
        assert f"#{r.id} · requête 1 · {r.tool} · {r.duration_ms} ms" in md and f"`{r.result_digest}`" in md and f"Statut : `{r.status}`" in md
    js = " ".join(str(j.value) for j in at.json)
    assert '"portfolio": "A"' in js and "files_sha256_prefix" in js and "rules_config_version" in js and "sha256" in js     # arguments, références, résultat complet
    assert any("compare_scenarios : non appelé pendant cette requête" in c.value for c in at.caption)


def test_trace_export_is_available_after_a_request(monkeypatch):
    patch_model(monkeypatch, explain_steps())
    at = run_app()
    click(at, "explain_btn")
    assert any(e.label == "Exporter la trace technique de toutes les requêtes (JSON)" for e in at.expander)


# ============================================================ 3. barre latérale
def test_sidebar_is_simple_and_technical_details_are_folded():
    at = run_app()
    adv = [e for e in at.sidebar.expander if e.label == "Paramètres avancés et diagnostic technique"]
    assert len(adv) == 1 and adv[0].proto.expanded is False
    inside = " ".join(m.value for m in adv[0].markdown)
    assert "global.amazon.nova-2-lite-v1:0" in inside and "us-east-1" in inside and "Amazon Bedrock" in inside and "Authentification" in inside
    assert any(b.label == "Tester la connexion Bedrock" for b in adv[0].button)
    assert any(c.label.startswith("Simuler une panne") for c in adv[0].checkbox)
    outside = " ".join(m.value for m in at.sidebar.markdown if m.value not in {x.value for x in adv[0].markdown}) + " ".join(c.value for c in at.sidebar.caption)
    assert "Profil actif" in outside and "Robert" in outside and "Simulation éducative" in outside
    assert "nova-2-lite" not in outside and "us-east-1" not in outside and "Région AWS" not in outside
    side_success = [s.value for s in at.sidebar.success]
    assert "Moteur financier : disponible" in side_success


def test_assistant_availability_is_shown_without_calling_bedrock(monkeypatch):
    model = patch_model(monkeypatch)
    at = run_app()
    status = [s.value for s in list(at.sidebar.success) + list(at.sidebar.warning) if s.value.startswith("Assistant IA")]
    assert len(status) == 1 and status[0] in ("Assistant IA : prêt", "Assistant IA : indisponible (aucun identifiant détecté)")
    assert model.i == 0 and at.session_state.agent.tracer.records == []


# ============================================================ 13. mode sans Bedrock
def test_without_bedrock_the_explain_button_reports_it_and_keeps_all_results(monkeypatch, real_service):
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "1")
    at = run_app()
    click(at, "explain_btn")
    assert not at.exception, at.exception
    assert any("injoignable" in e.value or "Aucun identifiant" in e.value for e in at.error), [e.value for e in at.error]
    assert any("Le moteur financier reste disponible" in i.value for i in at.info)
    assert {m.label: m.value for m in at.metric if m.label in V2_MAIN_LABELS} == v2_expected_metrics(real_service, NVDA40)
    assert any(m.value.startswith("### À retenir en priorité") for m in at.markdown)
    assert any("Votre portefeuille dépend beaucoup de NVIDIA." in m.value for m in at.markdown)
    assert any(w.value == "Assistant IA : indisponible lors du dernier essai" for w in at.sidebar.warning)


# ============================================================ 14. aucun secret affiché
def test_no_secret_or_credential_is_rendered(monkeypatch):
    patch_model(monkeypatch, explain_steps())
    at = run_app()
    click(at, "explain_btn")
    text = all_text(at)
    for pat in (r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", r"kak_[A-Za-z0-9]{10,}", r"(?i)aws_secret_access_key\s*[=:]", r"(?i)aws_session_token\s*[=:]", r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"):
        assert not re.search(pat, text), pat
    secrets = [os.environ.get(k) for k in ("KIRO_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_ACCOUNTID")]
    try:
        import boto3
        c = boto3.Session().get_credentials()
        if c is not None:
            f = c.get_frozen_credentials()
            secrets += [f.access_key, f.secret_key, f.token]
    except Exception:
        pass
    for s in [s for s in secrets if s and len(s) >= 8]:
        assert s not in text
