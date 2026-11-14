"""V3 — interface : Mateo, séparation risques financiers / préférences ESG, bouton IA, assistant, mode sans Bedrock.

Aucune donnée ESG fictive ici : l'application charge uniquement config/esg_sources.yaml (données documentées avec provenance).
"""
import re

import pytest

from conftest import V2_MAIN_LABELS, v2_expected_metrics
from guardian.finance.presets import load_presets
from test_v2_app import all_text, click, patch_model, run_app

GP, EV, CK, CMP, ESG = "get_profile", "evaluate_portfolio", "check_profile_constraints", "compare_scenarios", "check_esg_preferences"
MATEO_A = {t: v / 100 for t, v in load_presets()["mateo_croissance_equilibree"]["weights_pct"].items()}
MATEO_B = {t: v / 100 for t, v in load_presets()["mateo_actions_canadiennes"]["weights_pct"].items()}
FALSE_CLAIMS = re.compile(r"conforme ESG|portefeuille (est )?durable|respecte (toutes )?(vos|ses) préférences ESG|entièrement vérifi", re.I)


def mateo_app():
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    assert not at.exception, at.exception
    return at


def md(at) -> str:
    return " ".join(m.value for m in at.markdown)


# ============================================================ profil et scénarios
def test_mateo_is_selectable_and_shows_objective_risk_horizon_and_esg_preferences():
    at = run_app()
    assert at.selectbox(key="profile_id").options == ["Robert", "Amira", "Mateo"]
    at.selectbox(key="profile_id").set_value("mateo").run()
    text = md(at)
    assert "**Mateo** · 41 ans · Gestionnaire des opérations · risque **modéré** · horizon **8 à 12 ans**" in text
    assert "**Objectif :** Faire croître son capital de façon équilibrée à moyen et à long terme." in text
    assert "**Préférences ESG :** Accorde une grande importance aux facteurs ESG. Souhaite éviter les entreprises liées à des controverses environnementales ou sociales importantes." in text


def test_mateo_default_scenarios_are_loaded_when_nothing_was_touched():
    at = mateo_app()
    s = at.session_state.slots
    assert (s["A"]["preset"], s["B"]["preset"]) == ("mateo_croissance_equilibree", "mateo_actions_canadiennes")
    assert at.session_state.ctx.weights == MATEO_A and at.session_state.ctx.weights_b == MATEO_B and at.session_state.ctx.profile_id == "mateo"
    opts = at.selectbox(key="preset_A").options
    assert opts[0].startswith("★ Mateo") and opts[1].startswith("★ Mateo") and not opts[2].startswith("★")


def test_financial_metrics_do_not_depend_on_the_persona(real_service):
    at = run_app()
    at.selectbox(key="preset_A").set_value("mateo_croissance_equilibree").run()
    values = {}
    for pid in ("robert", "amira", "mateo"):
        at.selectbox(key="profile_id").set_value(pid).run()
        values[pid] = {m.label: m.value for m in at.metric if m.label in V2_MAIN_LABELS}
    assert values["robert"] == values["amira"] == values["mateo"] == v2_expected_metrics(real_service, MATEO_A)


# ============================================================ séparation risques financiers / ESG
def test_mateo_page_separates_financial_risks_from_esg_preferences_without_any_global_score():
    at = mateo_app()
    headings = [m.value for m in at.markdown if m.value.startswith("## ")]
    assert headings.index("## A · Risques financiers") < headings.index("## B · Mes préférences ESG")
    assert any("deux analyses distinctes" in i.value and "jamais combinées en une note unique" in i.value for i in at.info)
    text = all_text(at)
    assert "Aucun score ESG n'est calculé" in text and "jamais combinés en une note unique" in text
    assert not re.search(r"\bscore\b\s*[:=]?\s*\d|\b\d+(,\d+)?\s*/\s*(10|100)\b|note (globale|esg)\s*[:=]\s*\d", text, re.I)       # aucune valeur de score affichée
    fin_metrics = [m.label for m in at.metric if m.label in V2_MAIN_LABELS]
    assert fin_metrics == list(V2_MAIN_LABELS)                                           # les quatre indicateurs financiers restent distincts de l'ESG


def test_esg_section_explains_insufficient_information_and_shows_coverage():
    at = mateo_app()
    text = md(at)
    assert ("Nous pouvons analyser les risques financiers de votre portefeuille. Toutefois, les données disponibles ne permettent pas encore "
            "de vérifier l'ensemble de vos préférences ESG.") in text
    assert any("Information insuffisante" in m.value and "⚪" in m.value for m in at.markdown)
    cov = {m.label: m.value for m in at.metric if m.label in ("Cherché dans nos sources", "Non évaluable faute de données", "Sans objet pour ce critère")}
    assert cov == {"Cherché dans nos sources": "15 %", "Non évaluable faute de données": "80 %", "Sans objet pour ce critère": "5 %"}
    assert "15 % de votre portefeuille a pu être cherché dans nos sources ; 80 % ne peut pas être évalué faute de données et 5 % est sans objet" in text
    assert "ne sont pas présentées comme conformes" in text
    assert not FALSE_CLAIMS.search(all_text(at))
    assert "Exposition par ligne : 15 % du portefeuille est investi directement dans des actions d'entreprises" in text and "80 % est détenu via des FNB" in text
    assert "n'est donc pas connue et n'est pas estimée" in text
    assert "Une exclusion documentée liée à la préférence" in text and "Une mise sous observation de gouvernance" in text and "Une information manquante" in text and "Une absence de controverse identifiée" in text


def test_documented_information_is_shown_neutrally_with_source_date_and_nuance():
    at = mateo_app()
    at.selectbox(key="preset_A").set_value("mateo_actions_canadiennes").run()
    text = md(at)
    assert any("Controverse documentée à examiner" in m.value and "🟠" in m.value for m in at.markdown)
    assert "Informations documentées à examiner (critère lié à la préférence déclarée)" in text and "Information complémentaire documentée (hors critère déclaré)" in text
    assert "La Banque de Norvège (NBIM) a exclu Canadian Natural Resources de son fonds, décision publiée le 13 mai 2020." in text
    assert "La Banque de Norvège (NBIM) a placé Toronto-Dominion Bank sous observation, décision publiée le 11 juin 2025." in text
    assert "Critère invoqué : émissions de gaz à effet de serre jugées inacceptables (critère de conduite)." in text
    assert "Critère invoqué : corruption grave ou autre crime financier grave (critère de conduite)." in text
    assert "Ce critère relève de la gouvernance" in text and "dimension environnementale, visée par la préférence de Mateo" in text
    caps = " ".join(c.value for c in at.caption)                                          # la mise en garde est affichée en légende, sous chaque information
    assert "ni un jugement de culpabilité ni une note ESG" in caps and "Une mise sous observation est moins forte qu'une exclusion" in caps
    assert "[Consulter la source officielle](https://www.nbim.no/en/responsibility/exclusion-of-companies)" in text
    assert [m.value for m in at.metric if m.label == "Cherché dans nos sources"] == ["85 %"]
    assert "Exclusion environnementale : 15 % du portefeuille (CNQ.TO)" in text and "Mise sous observation de gouvernance : 15 % du portefeuille (TD.TO)" in text
    assert "jamais additionnées" in text
    esg_blocks = [m.value for m in at.markdown if "jamais additionnées" in m.value or "Information complémentaire" in m.value or "Exclusion environnementale" in m.value]
    assert esg_blocks and not any(re.search(r"30\s*%[^.]{0,40}(conflit|préférences? ESG)", b) for b in esg_blocks)
    assert any("CNQ.TO" in m.value and "Exclusion environnementale" in m.value and "🟠" in m.value for m in at.markdown)
    assert any("TD.TO" in m.value and "Mise sous observation de gouvernance" in m.value and "🟡" in m.value for m in at.markdown)
    assert not FALSE_CLAIMS.search(all_text(at))


def test_esg_technical_details_are_in_a_closed_section_with_sources_and_rules():
    at = mateo_app()
    exp = [e for e in at.expander if e.label == "Détails techniques ESG (sources, dates, règles appliquées)"]
    assert len(exp) == 1 and exp[0].proto.expanded is False
    inside = " ".join(m.value for m in exp[0].markdown)
    assert "nbim_exclusion_list" in inside and "consultée le 14 novembre 2026" in inside and "https://www.nbim.no/en/responsibility/exclusion-of-companies" in inside
    assert "Méthode de consultation" in inside and "Règles appliquées" in inside and "Incertitudes" in inside and "0.1-v3" in inside
    assert any("Conditions d'utilisation" in c.value and "n'ont pas été examinées en détail" in c.value for c in exp[0].caption)


def test_other_profiles_do_not_get_an_esg_section_and_keep_their_v2_page():
    for pid in ("robert", "amira"):
        at = run_app()
        at.selectbox(key="profile_id").set_value(pid).run()
        text = md(at)
        assert "## B · Mes préférences ESG" not in text and "## A · Risques financiers" not in text and "Préférences ESG :" not in text
        assert not any(m.label == "Cherché dans nos sources" for m in at.metric)


def test_comparison_tab_compares_esg_state_separately_and_names_no_winner():
    at = mateo_app()
    text = md(at)
    assert "Préférences ESG : comparaison (séparée des risques financiers)" in text
    assert any("ne désigne aucun portefeuille comme plus « durable »" in c.value for c in at.caption)
    tables = [df.value for df in at.dataframe]
    esg = next(df for df in tables if "État global" in list(df.iloc[:, 0]))
    row = esg.set_index(esg.columns[0])
    assert row.loc["État global", "A"] == "Information insuffisante" and row.loc["État global", "B"] == "Controverse documentée à examiner"
    direct, comp = "Informations documentées à examiner (critère lié à la préférence)", "Information complémentaire (hors critère déclaré)"
    assert row.loc[direct, "B"] == "Exclusion environnementale : CNQ.TO (15 %)" and row.loc[comp, "B"] == "Mise sous observation de gouvernance : TD.TO (15 %)"
    assert row.loc[direct, "A"] == "aucune dans les sources consultées" and row.loc[comp, "A"] == "aucune dans les sources consultées"


# ============================================================ bouton IA et assistant
def test_explain_button_for_mateo_requires_the_esg_tool_and_requests_a_separate_esg_section(monkeypatch):
    model = patch_model(monkeypatch, [("tools", [GP, EV, CK, ESG]), ("text", "**En bref** Texte d'interprétation.\n**Préférences ESG** Je ne peux pas confirmer.")])
    at = mateo_app()
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    assert tr.kind == "explain_risks" and not tr.withheld and {r.tool for r in tr.tool_records} == {GP, EV, CK, ESG} and all(r.status == "ok" for r in tr.tool_records)
    assert tr.context["profile_id"] == "mateo" and tr.context["weights_a_pct"]["QQQ"] == 10.0
    prompt = model.prompts[0]
    assert "portefeuille A pour Mateo" in prompt and "section séparée **Préférences ESG**" in prompt and "Profil actif : mateo (Mateo)" in prompt
    assert any("A vérifié les préférences ESG de Mateo pour le portefeuille A" in m.value for m in at.markdown)
    assert any("Sources ESG consultées : nbim_exclusion_list" in m.value for m in at.markdown)
    esg_rec = next(r for r in tr.tool_records if r.tool == ESG)
    assert f"#{esg_rec.id} · requête 1 · {ESG}" in md(at)                                   # niveau 2 : ligne de la trace réelle
    assert any('"esg_sources"' in str(j.value) for j in at.json)                              # références aux sources ESG conservées dans la trace technique


def test_explain_button_for_mateo_is_withheld_without_the_esg_tool(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK]), ("text", "Votre portefeuille respecte vos préférences ESG.")])
    at = mateo_app()
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    assert tr.withheld and tr.text is None and "check_esg_preferences" in tr.withheld_reason
    assert "respecte vos préférences ESG" not in all_text(at)


def test_explain_button_for_robert_does_not_require_the_esg_tool(monkeypatch):
    patch_model(monkeypatch, [("tools", [GP, EV, CK]), ("text", "**En bref** Interprétation.")])
    at = run_app()
    click(at, "explain_btn")
    tr = at.session_state.history[-1]
    assert not tr.withheld and ESG not in {r.tool for r in tr.tool_records}


def test_assistant_esg_question_shows_the_esg_tool_in_the_trace(monkeypatch):
    patch_model(monkeypatch, [("tools", [ESG]), ("text", "Je ne peux pas confirmer que ce portefeuille respecte toutes les préférences ESG de Mateo. "
                                                        "Les informations disponibles ne permettent pas d'évaluer certains actifs.")])
    at = mateo_app()
    q = [b for b in at.button if "préférences ESG" in b.label and b.label.startswith("💬")]
    assert q, [b.label for b in at.button]
    q[0].click()
    at.run()
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    tr = at.session_state.history[-1]
    assert [r.tool for r in tr.tool_records] == [ESG] and not tr.withheld and "Je ne peux pas confirmer" in md(at)
    text = md(at)
    assert "A vérifié les préférences ESG de Mateo pour le portefeuille A" in text and f"`{ESG}` · appel n° {tr.tool_records[0].id}" in text
    assert "interprétation" in text and not re.search(r"entièrement vérifi", text, re.I)


def test_esg_question_for_another_active_profile_asks_to_select_mateo(monkeypatch):
    model = patch_model(monkeypatch)
    at = run_app()                                                                         # Robert actif
    at.text_area[0].set_value("Mateo veut éviter les entreprises controversées. Est-ce que ce portefeuille respecte ses préférences ESG ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert any("Sélectionnez Mateo" in w.value for w in at.warning) and model.i == 0 and at.session_state.agent.tracer.records == []


# ============================================================ mode sans Bedrock et secrets
def test_without_bedrock_the_esg_section_and_financial_results_remain(monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://127.0.0.1:9")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "1")
    at = mateo_app()
    click(at, "explain_btn")
    assert any("injoignable" in e.value or "Aucun identifiant" in e.value for e in at.error), [e.value for e in at.error]
    assert any(m.value.startswith("## B · Mes préférences ESG") for m in at.markdown) and any("Information insuffisante" in m.value for m in at.markdown)
    assert {m.label: m.value for m in at.metric if m.label in ("Cherché dans nos sources",)} == {"Cherché dans nos sources": "15 %"}
    assert len([m for m in at.metric if m.label in V2_MAIN_LABELS]) == 4


def test_no_secret_is_rendered_for_mateo_flows(monkeypatch):
    import os
    patch_model(monkeypatch, [("tools", [GP, EV, CK, ESG]), ("text", "**En bref** Interprétation.")])
    at = mateo_app()
    click(at, "explain_btn")
    text = all_text(at)
    for pat in (r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", r"kak_[A-Za-z0-9]{10,}", r"(?i)aws_secret_access_key\s*[=:]", r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"):
        assert not re.search(pat, text), pat
    for key in ("KIRO_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        v = os.environ.get(key)
        if v and len(v) >= 8:
            assert v not in text


def test_fnb_wording_is_shown_on_the_page_without_changing_financial_values():
    at = mateo_app()
    notes = [i.value for i in at.info]
    assert any("Une position de 20 % dans un FNB diversifié n'est pas équivalente à une position de 20 % dans une entreprise individuelle" in n for n in notes)
    assert any("La diversification sous-jacente des FNB n'est pas mesurée" in n for n in notes)
    assert any("La diversification sous-jacente des FNB n'est pas mesurée" in c.value for c in at.caption)
    text = md(at)
    assert "XIU.TO représente 20 % de votre argent fictif." in text or "S&P/TSX" in text or "20 %" in text
    # comparaison A/B : légende FNB
    assert any("À propos des FNB" in c.value and "n'est pas mesurée ici" in c.value for c in at.caption)
