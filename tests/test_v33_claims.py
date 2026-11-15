"""V3.3 : contrôle déterministe des affirmations essentielles (rattachement valeur ↔ titre / indicateur / catégorie ESG, persona, distinctions ESG),
réponse de repli, isolation des requêtes, erreurs, non-régression du moteur financier. Le contrôle est PARTIEL : voir claims.CHECKED / NOT_CHECKED.
"""
import re
from types import SimpleNamespace as NS

import pytest
from conftest import StepModel
from guardian.agent.agent import GuardianAgent
from guardian.agent.claims import CHECKED, NOT_CHECKED, check_claims, fold
from guardian.agent.fallback import build_fallback
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.finance.presets import load_presets
from test_v2_app import patch_model, run_app

P = load_presets()
W = {k: {t: v / 100 for t, v in P[k]["weights_pct"].items()} for k in P}
MA, MB = W["mateo_croissance_equilibree"], W["mateo_actions_canadiennes"]
ESG, EV, CK = "check_esg_preferences", "evaluate_portfolio", "check_profile_constraints"
Q_ESG = "Mateo veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?"


def records(service, weights, pid, tools=(EV, CK, ESG), weights_b=None):
    ctx = SessionContext(weights, pid, weights_b=weights_b)
    t = {x.tool_spec["name"]: x for x in build_tools(service, ctx, Tracer())}
    return [NS(tool=n, status="ok", result=t[n]()) for n in tools]


def verdict(service, text, recs, pid="mateo"):
    return check_claims(text, recs, service.profiles, pid, service.bundle.universe)


def cats(rep):
    return {v.category for v in rep.violations}


@pytest.fixture(scope="module")
def rb(real_service):
    return records(real_service, MB, "mateo")


@pytest.fixture(scope="module")
def ra(real_service):
    return records(real_service, MA, "mateo")


# ============================================================ 1-2. valeurs rattachées au bon titre / au bon indicateur
def test_a_correct_value_attached_to_the_wrong_ticker_is_detected(real_service, rb):
    assert verdict(real_service, "TD.TO pèse 20 % du portefeuille et CNQ.TO 15 %.", rb).violations                     # 20 existe (RY.TO) mais pas pour TD.TO
    assert cats(verdict(real_service, "TD.TO pèse 20 % du portefeuille et CNQ.TO 15 %.", rb)) == {"valeur_associee"}
    assert verdict(real_service, "RY.TO pèse 20 % du portefeuille et CNQ.TO 15 %.", rb).ok
    assert verdict(real_service, "Le portefeuille détient 15 % de Toronto-Dominion Bank et 20 % de Royal Bank of Canada.", rb).ok
    assert not verdict(real_service, "Le portefeuille détient 20 % de Toronto-Dominion Bank et 15 % de Royal Bank of Canada.", rb).ok


def test_a_correct_value_attached_to_the_wrong_indicator_is_detected(real_service, ra):
    assert verdict(real_service, "La volatilité annualisée est de 9,6 % et la plus forte baisse historique de 15,5 %.", ra).ok
    swapped = verdict(real_service, "La volatilité annualisée est de 15,5 % et la plus forte baisse historique de 9,6 %.", ra)
    assert not swapped.ok and len([v for v in swapped.violations if v.category == "valeur_associee"]) == 2
    assert not verdict(real_service, "La plus grande position (XIU.TO) représente 30 % du portefeuille.", ra).ok


def test_asset_level_measures_are_accepted_for_their_own_ticker_only(real_service, ra):
    assert verdict(real_service, "QQQ : 22,8 % de volatilité.", ra).ok
    assert not verdict(real_service, "SPY : 22,8 % de volatilité.", ra).ok


def test_group_sum_of_listed_tickers_is_accepted(real_service, rb):
    assert verdict(real_service, "RY.TO, ENB.TO, CNR.TO et FTS.TO : 55 % du portefeuille sans controverse identifiée.", rb).ok


def test_rounding_to_the_displayed_precision_is_tolerated(real_service, ra):
    assert verdict(real_service, "La volatilité annualisée est d'environ 10 % et la baisse maximale de 15,48 %.", ra).ok


def test_percentage_without_any_anchor_is_only_counted_and_left_to_the_global_check(real_service, ra):
    rep = verdict(real_service, "Environ 25 % de cet ensemble appelle une lecture prudente.", ra)
    assert rep.ok and rep.free_numbers == 1 and rep.anchored_numbers == 0


# ============================================================ 3. persona
def test_persona_identity_horizon_age_and_risk_are_attached_to_the_right_persona(real_service, rb):
    assert verdict(real_service, "Mateo, 41 ans, a un horizon de 8 à 12 ans et un risque modéré.", rb).ok
    bad = verdict(real_service, "Mateo, 59 ans, a un horizon de 3 à 5 ans et un risque élevé.", rb)
    assert cats(bad) == {"persona"} and len(bad.violations) == 3
    assert "persona" in cats(verdict(real_service, "Mateo a 26 ans.", rb))                                      # âge d'Amira


def test_another_persona_occupation_is_not_attributed(real_service, rb):
    amira_job = real_service.profiles["amira"]["occupation"]
    assert "persona" in cats(verdict(real_service, f"Mateo travaille comme {amira_job.lower()}.", rb))


def test_horizon_of_each_official_persona_is_accepted_for_that_persona_only(real_service):
    r = records(real_service, W["robert_nvda_40"], "robert", (EV, CK))
    assert verdict(real_service, "Robert a un horizon de 3 à 5 ans.", r, "robert").ok
    assert not verdict(real_service, "Robert a un horizon de 8 à 12 ans.", r, "robert").ok
    a = records(real_service, W["amira_tech_crypto"], "amira", (EV, CK))
    assert verdict(real_service, "Amira a un horizon de 15 ans ou plus et un risque élevé.", a, "amira").ok
    assert not verdict(real_service, "Amira a un horizon de 3 à 5 ans.", a, "amira").ok


def test_traits_absent_from_the_official_profile_are_rejected(real_service, rb):
    for text in ("Mateo est anxieux face aux baisses.", "Mateo a besoin de liquidités à court terme.", "Mateo craint une crise."):
        assert "persona_invente" in cats(verdict(real_service, text, rb)), text
    assert verdict(real_service, "Mateo, père de deux enfants, a une expérience intermédiaire.", rb).ok            # présent dans le profil
    r = records(real_service, W["robert_nvda_40"], "robert", (EV, CK))
    assert verdict(real_service, "Robert envisage la retraite dans les prochaines années.", r, "robert").ok


def test_buy_or_sell_orders_are_rejected(real_service, ra):
    for text in ("Vendez XIU.TO et achetez des obligations.", "Je vous recommande de réduire NVIDIA.", "Vous devriez acheter des obligations."):
        assert "ordre" in cats(verdict(real_service, text, ra)), text
    assert verdict(real_service, "Une piste d'exploration neutre : comparer avec une autre répartition.", ra).ok


# ============================================================ 4. distinctions ESG
def test_exclusion_is_not_confused_with_observation_and_the_dimension_is_kept(real_service, rb):
    ok = ("Canadian Natural Resources (CNQ.TO) fait l'objet d'une exclusion environnementale ; Toronto-Dominion Bank (TD.TO) est sous observation, "
          "ce qui relève de la gouvernance.")
    assert verdict(real_service, ok, rb).ok
    assert "exclusion_observation" in cats(verdict(real_service, "Toronto-Dominion Bank (TD.TO) a été exclue de la liste.", rb))
    assert "exclusion_observation" in cats(verdict(real_service, "Canadian Natural Resources (CNQ.TO) est sous observation.", rb))
    assert "dimension_esg" in cats(verdict(real_service, "TD.TO est signalée pour un enjeu environnemental.", rb))
    assert "dimension_esg" in cats(verdict(real_service, "CNQ.TO est signalée pour un enjeu de gouvernance.", rb))
    assert verdict(real_service, "TD.TO concerne la gouvernance, hors des critères environnementaux ou sociaux déclarés.", rb).ok


def test_conflict_information_complementary_and_insufficient_are_kept_apart(real_service, rb, ra):
    assert "conflit_esg" in cats(verdict(real_service, "TD.TO représente un conflit avec les préférences de Mateo.", rb))
    assert verdict(real_service, "TD.TO n'est pas un conflit avec les préférences de Mateo : c'est une information complémentaire.", rb).ok
    assert "conflit_esg" in cats(verdict(real_service, "XBB.TO est en conflit avec les préférences ESG.", rb))
    merged = verdict(real_service, "30 % du portefeuille est en conflit avec les préférences ESG.", rb)
    assert "conflit_esg" in cats(merged)
    assert verdict(real_service, "15 % du portefeuille (CNQ.TO) est en conflit potentiel avec la préférence déclarée.", rb).ok


def test_coverage_percentages_must_match_their_category(real_service, rb):
    ok = ("Controverse documentée à examiner : 15 %. Information complémentaire : 15 %. Aucune controverse identifiée : 55 %. "
          "Information insuffisante : 15 %.")
    assert verdict(real_service, ok, rb).ok
    swapped = verdict(real_service, "Information insuffisante : 55 %. Aucune controverse identifiée : 15 %.", rb)
    assert len([v for v in swapped.violations if v.category == "valeur_associee"]) == 2
    assert not verdict(real_service, "Environ 20 % du portefeuille a été vérifié dans nos sources.", rb).ok            # 20 existe (poids), pas la couverture


# ============================================================ 5. information insuffisante et absence ≠ conformité
def test_absence_of_match_is_never_presented_as_compliance(real_service, ra):
    for text in ("Le portefeuille est conforme aux préférences ESG de Mateo.", "Ce portefeuille est durable et éthique.",
                 "Aucun conflit ESG : les préférences de Mateo sont respectées, le portefeuille est sans controverse."):
        assert "conformite_esg" in cats(verdict(real_service, text, ra)), text
    for text in ("Une absence de résultat n'est pas une preuve de conformité ESG.", "Le portefeuille ne peut pas être considéré comme conforme en l'état.",
                 "Information insuffisante pour confirmer sa conformité avec les préférences ESG."):
        assert verdict(real_service, text, ra).ok, text


def test_assets_checked_not_evaluable_and_not_applicable_are_not_mixed(real_service, ra):
    bad = verdict(real_service, "Couverture vérifiée : 15 % (seulement MSFT, JNJ, PG et GLD ont été vérifiées).", ra)
    assert "verification_actif" in cats(bad)
    assert "verification_actif" in cats(verdict(real_service, "Les FNB ont été vérifiés et ne présentent aucune controverse.", ra))
    assert "verification_actif" in cats(verdict(real_service, "GLD est conforme et sans controverse.", ra))
    assert verdict(real_service, "GLD est sans objet pour ce critère : il n'a pas été vérifié.", ra).ok
    assert verdict(real_service, "80 % du portefeuille (les FNB) ne peut pas être vérifié faute de données sur leur composition.", ra).ok
    assert "controverse_inventee" in cats(verdict(real_service, "RY.TO est exclue pour un motif environnemental.", records(real_service, MB, "mateo")))


# ============================================================ 6. aucun seuil ESG fictif
def test_esg_thresholds_do_not_exist_and_cannot_be_claimed(real_service, rb):
    for text in ("Le portefeuille présente un conflit potentiel avec les préférences ESG déclarées de Mateo selon les seuils heuristiques du prototype.",
                 "Le seuil ESG de 15 % est dépassé pour les controverses."):
        assert "seuil_esg" in cats(verdict(real_service, text, rb)), text
    assert verdict(real_service, "Le module ESG n'applique aucun seuil et ne calcule aucun score.", rb).ok
    assert verdict(real_service, "Le Guardian Check financier dépasse le seuil d'attention de 15 % pour la concentration.", rb).ok


# ============================================================ 7. FNB
def test_fund_wording_covers_cards_summary_and_comparison_with_asset_class_metadata(real_service):
    from guardian.explain.cards import TECH_LIMIT, build_cards
    from guardian.explain.compare_plain import plain_tradeoffs
    from guardian.explain.funds import EFFECTIVE_N_NOTE
    from guardian.explain.summary import build_priority_summary
    w = {"XIU.TO": 0.5, "SPY": 0.5}
    res, rep = real_service.check(w, "robert")
    cards = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg)}
    assert cards["R1"].status == rep.by_id()["R1"].status and "FNB" in cards["R1"].headline
    assert "peu de lignes" in cards["R7"].headline and "économiquement non diversifié" in cards["R7"].why
    assert EFFECTIVE_N_NOTE in cards["R7"].note and EFFECTIVE_N_NOTE in cards["R7"].limits
    assert "pas sur les entreprises sous-jacentes" in build_priority_summary(res, rep, real_service.profiles["robert"], real_service.bundle.universe).sentence
    same = {"NVDA": 0.5, "AAPL": 0.5}
    res2, rep2 = real_service.check(same, "robert")
    c2 = {c.rule_id: c for c in build_cards(res2, rep2, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg)}
    assert "peu de positions" in c2["R7"].headline and c2["R7"].note is None and "FNB" not in c2["R1"].headline
    cmp_ = real_service.compare(w, same, "robert")
    assert "dont la diversification n'est pas mesurée" in plain_tradeoffs(cmp_)[-1]
    assert "FNB" not in plain_tradeoffs(real_service.compare(same, {"NVDA": 0.4, "AAPL": 0.6}, "robert"))[-1]
    assert "PARTIELLE" in TECH_LIMIT


def test_fund_wording_does_not_change_any_measure_threshold_or_status(real_service):
    res, rep = real_service.check(MA, "mateo")
    f = rep.by_id()
    assert f["R1"].measured == pytest.approx(0.20) and f["R1"].status == "ATTENTION" and f["R7"].measured == pytest.approx(res.concentration.effective_n)
    assert (f["R1"].threshold_attention, f["R1"].threshold_conflict) == (0.15, 0.30)


def test_amira_technology_limit_is_explicit_in_the_analysis(real_service):
    from guardian.explain.cards import build_cards
    w = W["amira_tech_crypto"]
    res, rep = real_service.check(w, "amira")
    r10 = next(c for c in build_cards(res, rep, real_service.profiles["amira"], real_service.bundle.universe, real_service.rules_cfg) if c.rule_id == "R10")
    assert "30 %" in r10.measure and "QQQ" in r10.measure                                       # la préférence est visible dans l'analyse
    assert any("MESURE PARTIELLE" in x.upper() and "n'est pas mesurée" in x for x in r10.limits)
    assert any("ne peut donc pas conclure" in x for x in r10.limits)
    res_r, rep_r = real_service.check(W["robert_prudent"], "robert")
    r10r = next(c for c in build_cards(res_r, rep_r, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg) if c.rule_id == "R10")
    assert not any("PARTIELLE" in x for x in r10r.limits)                                       # pas de limite technologique pour un profil sans cette préférence


# ============================================================ 8. A/B et 12. non-régression
def test_comparison_uses_the_same_window_currency_and_rebalancing_and_keeps_engine_values(real_service):
    a, b = W["robert_prudent"], W["robert_nvda_40"]
    c = real_service.compare(a, b, "robert")
    assert c.conventions["currency"] == "CAD" and c.a.n_obs == c.b.n_obs and c.a.provenance["window"] == c.b.provenance["window"]
    assert c.deltas["annualized_volatility_pts"] == pytest.approx(100 * (c.b.volatility - c.a.volatility), abs=0.01)
    assert c.a.volatility == real_service.analyze(a).volatility and c.b.drawdown.max_drawdown == real_service.analyze(b).drawdown.max_drawdown


def test_financial_metrics_are_identical_for_the_three_personas_while_findings_differ(real_service):
    w = W["robert_nvda_40"]
    out = {pid: real_service.check(w, pid) for pid in ("robert", "amira", "mateo")}
    metrics = {pid: (r.volatility, r.cumulative_return, r.drawdown.max_drawdown, r.concentration.hhi) for pid, (r, _) in out.items()}
    assert metrics["robert"] == metrics["amira"] == metrics["mateo"]
    statuses = {pid: tuple(f.status for f in rep.findings) for pid, (_, rep) in out.items()}
    assert len(set(statuses.values())) == 3                                                       # les constats dépendent du profil


def test_robert_nvidia_concentration_triggers_adapted_warnings(real_service):
    res, rep = real_service.check(W["robert_nvda_40"], "robert")
    f = rep.by_id()
    assert f["R1"].status == "CONFLIT" and f["R1"].evidence["largest_position"] == "NVDA" and f["R2"].status == "CONFLIT"
    assert real_service.check(W["robert_prudent"], "robert")[1].by_id()["R1"].status in ("OK", "ATTENTION")      # le portefeuille prudent ne déclenche pas le même constat


# ============================================================ agent : repli, isolation, erreurs
def agent(service, steps, weights=MB, pid="mateo", tool_args=None):
    model = StepModel(steps, tool_args)
    ctx = SessionContext(weights, pid)
    return GuardianAgent(service, ctx, Tracer(), model_factory=lambda: model), model


def test_incorrect_text_is_withheld_and_replaced_by_verified_facts(real_service):
    ag, _ = agent(real_service, [("tools", [EV, CK, ESG]), ("text", "TD.TO pèse 20 % du portefeuille et 30 % du portefeuille est en conflit avec les préférences ESG.")])
    tr = ag.ask(Q_ESG)
    assert tr.withheld and tr.text is None and "affirmation(s)" in tr.withheld_reason and tr.claims and not tr.claims["ok"]
    fb = tr.fallback
    assert fb and "Faits vérifiés" in fb and "Préférences ESG" in fb and "Guardian Check" in fb
    ev = next(r for r in tr.tool_records if r.tool == EV).result
    assert f"{ev['metrics']['annualized_volatility_pct']:.1f}".replace(".", ",") in fb
    assert "exclusion environnementale : 15 % du portefeuille (CNQ.TO)" in fb
    assert "TD.TO pèse 20 %" not in fb                                                         # le texte rejeté n'est pas repris
    assert tr.tool_records and all(r.status == "ok" for r in tr.tool_records)                  # traces réelles conservées


def test_fallback_numbers_come_from_tool_results_only(real_service, rb):
    fb = build_fallback(rb)
    ev = next(r for r in rb if r.tool == EV).result
    m = ev["metrics"]
    assert f"{m['annualized_volatility_pct']:.1f}".replace(".", ",") in fb and f"{m['max_drawdown_pct']:.1f}".replace(".", ",") in fb
    assert "15 % du portefeuille (CNQ.TO)" in fb and "15 % du portefeuille (TD.TO)" in fb
    assert "Aucune vérification complète des entreprises sous-jacentes" in fb and "pas une preuve de conformité ESG" in fb
    assert "pas d'une recherche Internet en temps réel" in fb
    esg_part = fb.split("**Préférences ESG")[1].split("**Limites générales")[0]
    assert not re.search(r"30\s*%[^.\n]{0,60}conflit", esg_part)
    assert build_fallback([NS(tool=EV, status="error", result={"status": "error"})]) is None


def test_a_correct_text_is_shown_with_an_honest_partial_check_notice(real_service):
    good = "Canadian Natural Resources (CNQ.TO) fait l'objet d'une exclusion environnementale (15 % du portefeuille). TD.TO est une information complémentaire de gouvernance (15 %)."
    ag, _ = agent(real_service, [("tools", [ESG]), ("text", good)])
    tr = ag.ask(Q_ESG)
    assert not tr.withheld and tr.text == good and tr.fallback is None and tr.claims["ok"] and tr.claims["anchored_numbers"] >= 2
    s = tr.claims["summary"]
    assert "PARTIEL" in s and "Non vérifié automatiquement" in s and "interprétation" in s and "vérifié" in s
    assert tr.claims["checked"] == list(CHECKED) and tr.claims["not_checked"] == list(NOT_CHECKED)


def test_requests_are_isolated_claims_use_only_the_current_request_tools(real_service):
    """Un chiffre exact de la requête 1 ne valide pas une requête 2 qui n'a appelé aucun outil comportant ce chiffre."""
    ag, _ = agent(real_service, [("tools", [ESG]), ("text", "CNQ.TO (15 % du portefeuille) est une exclusion environnementale."),
                                 ("tools", ["get_profile"]), ("text", "Mateo détient 15 % dans CNQ.TO.")])
    t1 = ag.ask(Q_ESG)
    assert not t1.withheld
    t2 = ag.ask("Quel est le profil de Mateo ?")
    assert t2.turn == 2 and {r.tool for r in t2.tool_records} == {"get_profile"} and all(r.turn == 2 for r in t2.tool_records)
    # la requête 2 n'a appelé aucun outil de portefeuille : le « 15 % » de CNQ.TO issu de la requête 1 ne la valide pas
    assert t2.withheld and t2.claims and any(v["category"] == "valeur_associee" for v in t2.claims["violations"])


def test_tool_failure_still_withholds_without_fallback_numbers(real_service):
    ctx = SessionContext(MB, "mateo", fail_tools={ESG})
    model = StepModel([("tools", [ESG]), ("text", "CNQ.TO est exclue (15 %).")])
    tr = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model).ask(Q_ESG)
    assert tr.withheld and tr.text is None and tr.fallback is None and "Au moins un outil a échoué" in tr.withheld_reason and tr.claims is None


def test_bedrock_error_yields_no_claim_check_and_no_fallback(real_service):
    from botocore.exceptions import NoCredentialsError

    class Boom(StepModel):
        async def stream(self, *a, **k):
            raise NoCredentialsError()
            yield
    ctx = SessionContext(MB, "mateo")
    tr = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: Boom([])).ask(Q_ESG)
    assert tr.error and tr.error["kind"] == "no_credentials" and tr.text is None and tr.claims is None and tr.fallback is None


def test_required_tool_missing_still_withholds(real_service):
    ag, _ = agent(real_service, [("text", "Le portefeuille est conforme aux préférences ESG.")])
    tr = ag.ask(Q_ESG)
    assert tr.withheld and "check_esg_preferences" in tr.withheld_reason


# ============================================================ interface
def test_page_shows_fallback_and_unconfirmed_claims_when_text_is_rejected(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK, ESG]), ("text", "TD.TO pèse 20 % et 30 % du portefeuille est en conflit avec les préférences ESG.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.selectbox(key="preset_A").set_value("mateo_actions_canadiennes").run()
    at.text_area(key="q_text").set_value(Q_ESG)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Faits vérifiés, issus directement des calculs Python" in text and "Analyse incomplète" in " ".join(w.value for w in at.warning)
    assert "Références ESG utilisées dans cette réponse" in text
    exp = [e for e in at.expander if e.label.startswith("Affirmations non confirmées")]
    assert exp and "valeur_associee" in " ".join(m.value for m in exp[0].markdown)
    assert "TD.TO pèse 20 %" not in text


def test_page_shows_the_partial_check_notice_for_a_verified_text(monkeypatch):
    patch_model(monkeypatch, [("tools", [ESG]), ("text", "CNQ.TO (15 % du portefeuille) fait l'objet d'une exclusion environnementale.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.selectbox(key="preset_A").set_value("mateo_actions_canadiennes").run()
    at.text_area(key="q_text").set_value(Q_ESG)
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert any("Contrôle automatique PARTIEL" in c.value for c in at.caption)


def test_esg_data_nature_and_temporal_notice_are_shown_and_returned(real_service):
    out = records(real_service, MB, "mateo", (ESG,))[0].result
    assert "pas d'une recherche Internet en temps réel" in out["data_nature"] and "2021-2026" in out["data_nature"] and "aucun résultat financier historique" in out["data_nature"]
    assert "n'applique aucun seuil" in out["no_threshold_notice"]
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    assert any("pas d'une recherche Internet en temps réel" in c.value for c in at.caption)


def test_general_limitations_cover_rates_fx_rebalancing_and_esg_dating(real_service):
    _, rep = real_service.check(MA, "mateo")
    blob = fold(" ".join(rep.general_limitations))
    for needle in ("taux d'interet", "usd/cad", "reequilibrage mensuel", "etat date", "sans couts de transaction", "une seule trajectoire", "pas une prevision", "impots", "cryptos"):
        assert needle in blob, needle


def test_fold_keeps_positions_valid():
    s = "Électricité à l’œuvre — 15 %"
    assert len(fold(s)) == len(s) and fold(s).startswith("electricite a l'")


# ============================================================ cas relevés dans des réponses réelles (V3.3)
def test_class_exposure_without_ticker_accepts_a_line_weight_but_a_tech_share_must_exist(real_service):
    r = records(real_service, W["robert_nvda_40"], "robert", (CK,))
    ok = "Composition : 40 % en actions individuelles (NVDA), 60 % en FNB (35 % en obligations canadiennes, 25 % en actions canadiennes)."
    assert verdict(real_service, ok, r, "robert").ok
    assert not verdict(real_service, "Composition : 45 % en obligations canadiennes.", r, "robert").ok


def test_asset_values_from_tool_evidence_are_attached_to_their_ticker(real_service):
    r = records(real_service, W["robert_nvda_40"], "robert", (CK,))
    vol = next(a["volatility_pct"] if "volatility_pct" in a else a.get("annualized_volatility_pct")
               for f in r[0].result["findings"] if f["rule_id"] == "R2" for a in f["evidence"]["volatile_assets"] if a["ticker"] == "NVDA")
    assert verdict(real_service, f"NVDA a une volatilité annualisée de {str(round(vol, 2)).replace('.', ',')} %.", r, "robert").ok
    assert not verdict(real_service, "NVDA a une volatilité annualisée de 12,5 %.", r, "robert").ok


def test_a_percentage_called_technology_must_be_the_measured_technology_share(real_service):
    amira = W["amira_tech_crypto"]
    ev_only = records(real_service, amira, "amira", (EV,))
    assert "valeur_associee" in cats(verdict(real_service, "Le portefeuille présente une forte concentration dans les technologies (70 % du portefeuille).", ev_only, "amira"))
    full = records(real_service, amira, "amira", (EV, CK))
    assert verdict(real_service, "La part des positions étiquetées technologie est de 30 % du portefeuille (NVIDIA, Shopify).", full, "amira").ok
    assert not verdict(real_service, "La part technologique est de 70 %.", full, "amira").ok


def test_ticker_named_in_the_previous_clause_still_owns_its_figure(real_service):
    r = records(real_service, W["robert_nvda_40"], "robert", (EV, CK))
    assert verdict(real_service, "Exposition aux actifs volatils : 40 % dans NVDA, dont la volatilité annuelle est de 50,71 % (seuils : attention > 10 %, conflit > 20 %).", r, "robert").ok
    assert not verdict(real_service, "Exposition aux actifs volatils : 40 % dans NVDA, dont la volatilité annuelle est de 45,2 %.", r, "robert").ok


def test_fallback_shows_the_partial_technology_measure_for_amira(real_service):
    fb = build_fallback(records(real_service, W["amira_tech_crypto"], "amira", (EV, CK)))
    assert "Part des positions étiquetées technologie ou communication : 30 %" in fb and "plus 25 % dans QQQ" in fb and "Mesure PARTIELLE" in fb
    assert "Amira : 26 ans" in fb and "horizon 15 ans ou plus" in fb


def test_a_sum_computed_by_the_model_is_not_accepted_as_a_tool_value(real_service):
    r = records(real_service, W["amira_tech_crypto"], "amira", (EV, CK))
    rep = verdict(real_service, "Plus de la moitié (55 %) provient de positions technologiques.", r, "amira")
    assert "valeur_associee" in cats(rep)          # 30 % + 25 % est une addition du modèle : seules les valeurs retournées par les outils sont acceptées


# ============================================================ anti-sur-blocage : réponses réelles correctes (Bedrock, 2026-11-14)
GOOD = __import__("json").loads((__import__("pathlib").Path(__file__).parent / "golden" / "v33_live_good_answers.json").read_text(encoding="utf-8"))
GOOD_CTX = {"mateo_b_documented": (MB, None, (ESG, "get_profile")), "robert_compare": (W["robert_nvda_40"], W["robert_prudent"], ("compare_scenarios",))}


@pytest.mark.parametrize("key", sorted(GOOD))
def test_real_correct_answers_are_not_blocked(real_service, key):
    """Textes réels de Nova 2 Lite relus à la main et jugés corrects : le contrôle ne doit pas les retenir (régression de sur-blocage)."""
    g = GOOD[key]
    wa, wb, tools = GOOD_CTX[key]
    recs = records(real_service, wa, g["pid"], tools, weights_b=wb)
    rep = verdict(real_service, g["text"], recs, g["pid"])
    assert rep.ok, [v.to_dict() for v in rep.violations]
    assert rep.anchored_numbers >= 3


def test_known_miss_is_documented_not_hidden(real_service):
    """LIMITE DOCUMENTÉE : cette réponse réelle passe le contrôle alors qu'elle prête une réaction psychologique au persona et exagère la concentration.
    Le contrôle ne couvre pas les qualificatifs ni les réactions formulées au conditionnel (voir claims.NOT_CHECKED)."""
    g = __import__("json").loads((__import__("pathlib").Path(__file__).parent / "golden" / "v33_live_known_misses.json").read_text(encoding="utf-8"))["amira_explain"]
    rep = verdict(real_service, g["text"], records(real_service, W["amira_tech_crypto"], "amira", (EV, CK)), "amira")
    assert rep.ok                                     # si ce test échoue, le contrôle a été étendu : mettre à jour la limite documentée
    assert "qualificatifs" in " ".join(NOT_CHECKED)


# ============================================================ V3.3.1 : deux défauts relevés en test manuel (réponse réelle pour Mateo)
SEUILS_CNQ = ("Canadian Natural Resources (CNQ.TO) fait l'objet d'une exclusion environnementale par NBIM (15 % du portefeuille). "
              "Selon les seuils heuristiques du prototype, cela représente un conflit potentiel.")
COUVERTURE_55 = "85 % du portefeuille a été recherché dans les sources consultées. NBIM couvre 55 % du portefeuille."


def test_esg_thresholds_in_the_sentence_after_the_cnq_exclusion_are_rejected(real_service, rb):
    """« cela » renvoie à l'exclusion de CNQ dans la phrase précédente : le module ESG n'a aucun seuil."""
    rep = verdict(real_service, SEUILS_CNQ, rb)
    assert "seuil_esg" in cats(rep)
    assert any("Selon les seuils heuristiques du prototype, cela représente un conflit potentiel" in v.excerpt for v in rep.violations)
    esg = next(r for r in rb if r.tool == ESG).result
    assert esg["documented_categories"][0]["tickers"] == ["CNQ.TO"] and "n'applique aucun seuil" in esg["no_threshold_notice"]


def test_financial_thresholds_after_an_esg_sentence_remain_accepted(real_service, rb):
    vol = next(r for r in rb if r.tool == EV).result["metrics"]["annualized_volatility_pct"]
    ok = (f"CNQ.TO fait l'objet d'une exclusion environnementale. Selon les seuils heuristiques du prototype, la volatilité de "
          f"{str(round(vol, 1)).replace('.', ',')} % reste un point à examiner.")
    assert verdict(real_service, ok, rb).ok
    assert verdict(real_service, "CNQ.TO fait l'objet d'une exclusion environnementale. Le module ESG n'applique aucun seuil.", rb).ok


def test_not_found_share_is_not_accepted_as_nbim_coverage(real_service, rb):
    """55 % = actions cherchées SANS correspondance ; la couverture (part cherchée dans les sources) est 85 %."""
    esg = next(r for r in rb if r.tool == ESG).result
    assert esg["coverage"]["checked_in_sources_pct"] == 85.0 and esg["search_scope"][0]["weight_pct"] == 55.0
    rep = verdict(real_service, COUVERTURE_55, rb)
    assert [v.category for v in rep.violations] == ["valeur_associee"] and "55 %" in rep.violations[0].message and "couverture" in rep.violations[0].message
    real = "Seule une source (NBIM) a été utilisée, couvrant 55 % du portefeuille."               # même confusion, réponse réelle enregistrée le 2026-11-14
    assert "valeur_associee" in cats(verdict(real_service, real, rb))


def test_correct_coverage_and_not_found_wordings_remain_accepted(real_service, rb):
    for text in ("NBIM couvre 85 % du portefeuille.", "85 % du portefeuille a été recherché dans les sources consultées.",
                 "55 % du portefeuille a été cherché dans NBIM sans correspondance.", "Les sources ne couvrent pas toutes les controverses possibles."):
        assert verdict(real_service, text, rb).ok, text


def test_agent_withholds_the_reported_mateo_answer_and_shows_the_fallback(real_service):
    ag, _ = agent(real_service, [("tools", [ESG]), ("text", SEUILS_CNQ + " " + COUVERTURE_55)])
    tr = ag.ask(Q_ESG)
    assert tr.withheld and tr.text is None and {"seuil_esg", "valeur_associee"} <= {v["category"] for v in tr.claims["violations"]}
    assert "85 %" in tr.fallback and "Cherchés et non trouvés" in tr.fallback
