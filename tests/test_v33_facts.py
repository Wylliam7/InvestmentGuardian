"""V3.3 (dernière passe) : faits structurés `key_facts` fournis au modèle, contrat d'explication, faux positifs connus du validateur.
Les formulations « réelles » proviennent de réponses Bedrock enregistrées le 2026-11-14 (Nova 2 Lite, Nova Pro, Claude Haiku 4.5).
"""
from types import SimpleNamespace as NS

import pytest
from guardian.agent.agent import SYSTEM_PROMPT
from guardian.agent.claims import check_claims
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.finance.presets import load_presets

P = load_presets()
W = {k: {t: v / 100 for t, v in P[k]["weights_pct"].items()} for k in P}
EV, CK, ESG, GP = "evaluate_portfolio", "check_profile_constraints", "check_esg_preferences", "get_profile"


def outputs(service, preset, pid, tools=(GP, EV, CK, ESG)):
    t = {x.tool_spec["name"]: x for x in build_tools(service, SessionContext(W[preset], pid), Tracer())}
    return {n: t[n]() for n in tools}


def verdict(service, text, preset, pid, tools=(GP, EV, CK, ESG)):
    recs = [NS(tool=n, status="ok", result=r) for n, r in outputs(service, preset, pid, tools).items()]
    return check_claims(text, recs, service.profiles, pid, service.bundle.universe)


def cats(rep):
    return {v.category for v in rep.violations}


# ============================================================ faits structurés : repris du moteur, sans nouveau calcul
def test_key_facts_list_the_real_top3_positions_and_their_engine_total(real_service):
    out = outputs(real_service, "amira_tech_crypto", "amira", (EV, CK))
    for tool in (EV, CK):
        kf = out[tool]["key_facts"]
        assert [(p["ticker"], p["weight_pct"]) for p in kf["top_positions"]] == [("NVDA", 25.0), ("QQQ", 25.0), ("BTC-USD", 20.0)]
        assert kf["top3_total_pct"] == out[tool]["concentration"]["top3_weight_pct"] == 70.0 and kf["top3_ties"] is None
        assert [p["line_type"] for p in kf["top_positions"]] == ["action individuelle", "FNB d'actions", "cryptoactif"]
    m = out[EV]["metrics"]
    assert out[EV]["key_facts"]["indicators"]["volatilité annualisée du portefeuille (%)"] == m["annualized_volatility_pct"]
    assert out[EV]["key_facts"]["indicators"]["plus forte baisse historique du portefeuille (%)"] == m["max_drawdown_pct"]


def test_key_facts_state_ties_instead_of_inventing_a_ranking(real_service):
    kf = outputs(real_service, "mateo_actions_canadiennes", "mateo", (EV,))[EV]["key_facts"]
    assert kf["top_positions"][0]["ticker"] == "RY.TO" and kf["top3_total_pct"] == 50.0
    assert "Égalité" in kf["top3_ties"] and all(t in kf["top3_ties"] for t in ("CNQ.TO", "ENB.TO", "TD.TO", "XBB.TO")) and "50.0 %" in kf["top3_ties"]


def test_key_facts_give_the_partial_technology_share_and_say_it_is_not_a_total(real_service):
    ck = outputs(real_service, "amira_tech_crypto", "amira", (CK,))[CK]
    tech = ck["key_facts"]["technology"]
    r10 = next(f for f in ck["findings"] if f["rule_id"] == "R10")["evidence"]
    assert tech["part_directe_mesurée_pct"] == r10["tech_share_pct"] == 30.0 and tech["QQQ_pct_non_décomposé"] == r10["qqq_weight_pct"] == 25.0
    assert tech["exposition_technologique_totale_mesurée"] is False and "ne s'additionnent pas" in tech["à_dire"] and "aucun seuil" in tech["à_dire"]
    assert "technology" not in outputs(real_service, "robert_nvda_40", "robert", (CK,))[CK]["key_facts"]          # pas de mesure inventée pour Robert


def test_key_facts_list_the_guardian_findings_with_the_thresholds_really_applied(real_service):
    ck = outputs(real_service, "robert_nvda_40", "robert", (CK,))[CK]
    gf = {g["règle"]: g for g in ck["key_facts"]["guardian_findings"]}
    r1 = next(f for f in ck["findings"] if f["rule_id"] == "R1")
    assert gf["R1"]["statut"] == r1["status_label"] and gf["R1"]["mesuré"] == r1["display"]["measured"]
    assert gf["R1"]["repère d'attention"] == "> 10 %" and gf["R1"]["repère de conflit"] == "> 20 %" and "R10" not in gf


def test_esg_key_facts_separate_coverage_not_found_categories_and_state_no_threshold(real_service):
    esg = outputs(real_service, "mateo_actions_canadiennes", "mateo", (ESG,))[ESG]
    kf = esg["key_facts"]
    assert kf["couverture_pct (part cherchée dans au moins une source)"] == esg["coverage"]["checked_in_sources_pct"] == 85.0
    assert kf["cherché_sans_correspondance_pct (ce n'est ni la couverture ni une conformité)"] == 55.0
    cats_ = {c["catégorie"]: c for c in kf["catégories_documentées (ne s'additionnent pas)"]}
    assert cats_["Exclusion environnementale"]["titres"] == ["CNQ.TO"] and cats_["Exclusion environnementale"]["lien_avec_la_préférence_déclarée"] is True
    assert cats_["Mise sous observation de gouvernance"]["titres"] == ["TD.TO"] and cats_["Mise sous observation de gouvernance"]["lien_avec_la_préférence_déclarée"] is False
    assert cats_["Exclusion environnementale"]["dates_de_décision"] == ["2020-05-13"] and kf["seuils_ESG"].startswith("aucun")
    a = outputs(real_service, "mateo_croissance_equilibree", "mateo", (ESG,))[ESG]["key_facts"]
    assert a["sans_objet (non vérifiés, sans entreprise émettrice)"] == ["GLD"] and a["non_évaluable_pct (FNB sans composition, non vérifiés)"] == 80.0
    assert outputs(real_service, "robert_nvda_40", "robert", (ESG,))[ESG]["key_facts"] is None


def test_key_facts_do_not_change_engine_values(real_service):
    ev = outputs(real_service, "robert_nvda_40", "robert", (EV,))[EV]
    assert {k: v for k, v in ev.items() if k not in ("fund_exposure", "key_facts", "portfolio")} == real_service.analyze(W["robert_nvda_40"]).to_tool_dict()


def test_prompt_contract_is_short_and_covers_the_five_points():
    rule = SYSTEM_PROMPT.split("15. CONTRAT D'EXPLICATION.")[1]
    assert len(rule) < 900 and "16." not in rule
    for needle in ("key_facts", "Ne recalcule et n'additionne aucun pourcentage", "Une part sectorielle partielle n'est pas une exposition totale",
                   "Aucun seuil n'existe pour l'ESG ni pour la technologie", "faits vérifiés, ton interprétation et les informations manquantes",
                   "sans conseiller d'acheter, de vendre, de réduire ou de rééquilibrer"):
        assert needle in rule, needle


# ============================================================ Amira : trois plus grandes positions, pas de faux total technologique
AMIRA = "amira_tech_crypto"


@pytest.mark.parametrize("text", [
    "Les trois plus grandes positions sont NVDA (25 %), QQQ (25 %) et BTC-USD (20 %), soit 70 % du portefeuille.",
    "Les trois plus grandes positions (NVDA, QQQ, BTC-USD) représentent 70 % du portefeuille.",
    "La part directement mesurée des titres étiquetés technologie est de 30 % (NVDA, SHOP.TO) ; QQQ (25 %) n'est pas décomposé.",
    "L'exposition technologique totale n'est pas mesurée par le prototype.",
])
def test_amira_good_wordings_are_accepted(real_service, text):
    rep = verdict(real_service, text, AMIRA, "amira")
    assert rep.ok, [v.to_dict() for v in rep.violations]


def test_amira_correct_real_answer_is_not_blocked(real_service):
    """Réponse réelle correcte (Nova 2 Lite, après correction) retenue à tort : « 30 % » attribué à QQQ, cité dans une autre proposition."""
    ok = ("Exposition technologique totale : Non mesurée. Les 30 % directs et les 25 % de QQQ ne s'additionnent pas pour donner une exposition totale, "
          "car QQQ inclut d'autres secteurs.")
    rep = verdict(real_service, ok, AMIRA, "amira", (EV,))
    assert rep.ok, [v.to_dict() for v in rep.violations]
    assert "persona" in cats(verdict(real_service, "Amira : tolérance au risque : modérée.", AMIRA, "amira", (EV,)))   # erreur réelle du même lot


def test_robert_asset_volatility_in_parentheses_is_attached_to_nvda(real_service):
    ok = ("La plus grande position est NVIDIA à 40 % du portefeuille, ce qui représente aussi la part exposée à un actif très volatile "
          "(50,71 % de volatilité annualisée).")                                                     # réponse réelle (après), valeur exacte de NVDA
    assert verdict(real_service, ok, ROBERT, "robert").ok
    assert not verdict(real_service, ok.replace("50,71", "45,2"), ROBERT, "robert").ok


def test_amira_real_sentence_rejects_the_false_total_but_not_the_correct_partial_share(real_service):
    """Réponse réelle (Nova 2 Lite) : le « 55 % » est faux (QQQ compté comme entièrement technologique), le « 30 % » partiel est exact."""
    real = ("Ainsi, l'exposition technologique **réelle** dépasse **55 %** du portefeuille, même si la mesure partielle (sans décomposition du FNB) "
            "n'en montre que 30 %.")
    rep = verdict(real_service, real, AMIRA, "amira")
    flagged = [v.message.split(" est ")[0] for v in rep.violations]                      # « Le pourcentage X % »
    assert flagged == ["Le pourcentage 55 %"], flagged


@pytest.mark.parametrize("text,category", [
    ("Les trois plus grandes positions (NVDA, QQQ, TSLA) représentent 70 % du portefeuille.", "valeur_associee"),
    ("Les trois plus grandes positions sont NVDA, TSLA et SHOP.TO.", "valeur_associee"),
    ("La part totale des technologies est donc de 55 %.", "valeur_associee"),                                         # réponse réelle (Nova Pro)
    ("Exposition technologique totale mesurable : 55 % (30 % + 25 % QQQ).", "valeur_associee"),                       # réponse réelle (Haiku 4.5)
    ("Au total, 55 % du portefeuille est lié à la technologie, directement ou via le FNB.", "valeur_associee"),        # réponse réelle (Nova 2 Lite)
    ("La part technologique dépasse le seuil de 25 % et crée un conflit avec la préférence d'Amira pour les technologies.", "conflit_non_etabli"),
])
def test_amira_bad_wordings_are_rejected(real_service, text, category):
    assert category in cats(verdict(real_service, text, AMIRA, "amira"))


# ============================================================ Mateo : CNQ et TD distingués, sans seuil ESG
MATEO = "mateo_actions_canadiennes"


@pytest.mark.parametrize("text", [
    "CNQ.TO (15 % du portefeuille) fait l'objet d'une exclusion environnementale publiée le 2020-05-13.",
    "TD.TO (15 %) est placée sous observation pour un critère de gouvernance : c'est une information complémentaire, pas un conflit avec la préférence déclarée.",
    "85 % du portefeuille a été cherché dans la source consultée ; 55 % y a été cherché sans correspondance.",
    "Le module ESG n'applique aucun seuil.",
])
def test_mateo_good_wordings_are_accepted(real_service, text):
    rep = verdict(real_service, text, MATEO, "mateo")
    assert rep.ok, [v.to_dict() for v in rep.violations]


@pytest.mark.parametrize("text,category", [
    ("CNQ.TO fait l'objet d'une exclusion environnementale. Selon les seuils heuristiques du prototype, cela représente un conflit potentiel.", "seuil_esg"),
    ("NBIM couvre 55 % du portefeuille.", "valeur_associee"),
    ("TD.TO a été exclue pour un motif environnemental.", "exclusion_observation"),
    ("30 % du portefeuille est en conflit avec les préférences ESG.", "conflit_esg"),
])
def test_mateo_bad_wordings_are_rejected(real_service, text, category):
    assert category in cats(verdict(real_service, text, MATEO, "mateo"))


# ============================================================ Robert : concentration NVIDIA, sans ordre ni conseil
ROBERT = "robert_nvda_40"


@pytest.mark.parametrize("text", [
    "La position de NVDA représente 40 % du portefeuille, avec une volatilité annualisée de 50.71 % et un drawdown maximal de -63.46 %.",   # faux positif réel (Nova Pro)
    "Les seuils d'attention et de conflit pour la concentration dans un actif sont respectivement de 10 % et 20 %.",                      # faux positif réel (Nova Pro)
    "NVDA pèse 40 % du portefeuille, au-delà du repère de conflit de 20 % pour Robert, dont l'horizon est de 3 à 5 ans.",
    "Le compromis historique : un rendement cumulé de 180,91 % mais une plus forte baisse de -36,14 % ; le passé ne prédit pas l'avenir.",
    "Robert doit peser ce rendement contre le risque accru et décider si cette concentration correspond à sa tolérance réelle.",   # réponse réelle (après)
])
def test_robert_good_wordings_are_accepted(real_service, text):
    rep = verdict(real_service, text, ROBERT, "robert")
    assert rep.ok, [v.to_dict() for v in rep.violations]


@pytest.mark.parametrize("text,category", [
    ("Robert devrait considérer : **Rééquilibrage** pour réduire la concentration.", "ordre"),                         # réponse réelle (Nova 2 Lite)
    ("Robert devrait considérer :  \n- **Rééquilibrage** pour réduire la concentration.", "ordre"),                    # même réponse, en liste à puces
    ("Une réduction de cette concentration pourrait mieux aligner le portefeuille avec son objectif.", "ordre"),       # réponse réelle (Nova 2 Lite)
    ("Vendez une partie de NVDA.", "ordre"),
    ("Robert pourrait envisager de réduire cette exposition pour mieux aligner son portefeuille.", "ordre"),          # réponse réelle (Nova 2 Lite, après)
    ("La volatilité annualisée de NVDA est de 45,2 %.", "valeur_associee"),
    ("Les seuils d'attention et de conflit pour la concentration sont respectivement de 15 % et 30 %.", "valeur_associee"),    # repères de Mateo, pas de Robert
    ("Robert a un horizon de 8 à 12 ans.", "persona"),
])
def test_robert_bad_wordings_are_rejected(real_service, text, category):
    assert category in cats(verdict(real_service, text, ROBERT, "robert"))


def test_evaluate_portfolio_alone_gives_amira_the_measured_technology_share(real_service):
    """Cause d'erreur observée : Nova n'appelle parfois qu'evaluate_portfolio. La part mesurée (même fonction que R10) y figure désormais pour Amira."""
    ev = outputs(real_service, AMIRA, "amira", (EV,))[EV]
    r10 = next(f for f in outputs(real_service, AMIRA, "amira", (CK,))[CK]["findings"] if f["rule_id"] == "R10")["evidence"]
    tech = ev["key_facts"]["technology"]
    assert (tech["part_directe_mesurée_pct"], tech["titres_comptés"], tech["QQQ_pct_non_décomposé"]) == (r10["tech_share_pct"], r10["tech_positions"], r10["qqq_weight_pct"])
    assert "technology" not in outputs(real_service, AMIRA, "robert", (EV,))[EV]["key_facts"]          # même portefeuille, profil sans ce contexte
    rep = verdict(real_service, "Au total, 55 % du portefeuille est directement exposé aux technologies via des actions individuelles et un FNB.", AMIRA, "amira", (EV,))
    assert "valeur_associee" in cats(rep)                                                          # réponse réelle (après) : faux total toujours refusé
    assert verdict(real_service, "La part directement mesurée est de 30 % (NVDA, SHOP.TO).", AMIRA, "amira", (EV,)).ok


# ============================================================ test manuel 1 d'Amira (trois plus grosses positions)
Q_TOP3 = ("Quelles sont les trois plus grosses positions de mon portefeuille, quel est le poids de chacune et quel pourcentage total représentent-elles ? "
          "Explique ce que cela signifie pour ma diversification.")


def test_evaluate_portfolio_now_carries_amira_profile_and_her_concentration_thresholds(real_service):
    """Cause observée : avec evaluate_portfolio seul, Nova ne recevait ni le profil ni les repères et en inventait (30 %, « modéré », « 10 ans »)."""
    prof = outputs(real_service, AMIRA, "amira", (EV,))[EV]["key_facts"]["profil_actif"]
    r1 = real_service.rules_cfg["rules"]["R1"]["thresholds"]["amira"]
    assert (prof["persona"], prof["niveau_de_risque"], prof["horizon"]) == ("Amira", real_service.profiles["amira"]["risk_profile_label"], "15 ans ou plus")
    assert prof["repères_concentration_plus_grande_position"] == {"attention": f"> {100 * r1['attention']:g} %", "conflit": f"> {100 * r1['conflict']:g} %"}
    assert prof["repères_concentration_plus_grande_position"] == {"attention": "> 20 %", "conflit": "> 35 %"}
    assert outputs(real_service, AMIRA, "robert", (EV,))[EV]["key_facts"]["profil_actif"]["repères_concentration_plus_grande_position"]["conflit"] == "> 20 %"


@pytest.mark.parametrize("tools", [(EV,), (EV, CK)])
@pytest.mark.parametrize("text,category", [
    ("Le seuil de concentration de 30 % est dépassé par NVDA.", "valeur_associee"),                                   # erreur réelle
    ("Pour un profil modéré sur un horizon de 10 ans, cette concentration est élevée.", "persona"),                   # erreur réelle
    ("Amira a un horizon de 10 ans.", "persona"),
    ("Amira a un profil de risque modéré.", "persona"),
    ("La concentration dépasse le repère de conflit de 20 %.", "valeur_associee"),                                    # repère de Robert attribué à Amira
])
def test_amira_manual_test_errors_are_rejected(real_service, tools, text, category):
    assert category in cats(verdict(real_service, text, AMIRA, "amira", tools))


@pytest.mark.parametrize("tools", [(EV,), (EV, CK)])
@pytest.mark.parametrize("text", [
    "Les trois plus grosses positions sont NVDA (25 %), QQQ (25 %) et BTC-USD (20 %), soit 70 % du portefeuille.",
    "NVDA pèse 25 %, au-delà du repère d'attention de 20 % mais sous le repère de conflit de 35 % pour Amira.",
    "Amira a une tolérance élevée et un horizon de 15 ans ou plus.",
    "Pour un profil élevé sur un horizon de 15 ans ou plus, cette concentration reste un point de vigilance.",
])
def test_amira_correct_wordings_are_accepted(real_service, tools, text):
    rep = verdict(real_service, text, AMIRA, "amira", tools)
    assert rep.ok, [v.to_dict() for v in rep.violations]


def test_threshold_checks_still_accept_the_other_criteria(real_service):
    ok = "La volatilité du portefeuille de 35,32 % dépasse le seuil de conflit de 35 % ; la plus forte baisse de -55,99 % dépasse le seuil de conflit de 55 %."
    assert verdict(real_service, ok, AMIRA, "amira", (EV, CK)).ok
    assert "valeur_associee" in cats(verdict(real_service, "La volatilité du portefeuille dépasse le seuil de conflit de 25 %.", AMIRA, "amira", (EV, CK)))
    assert verdict(real_service, "Mateo a un horizon de 10 ans.", "mateo_croissance_equilibree", "mateo", (EV,)).ok        # 10 ans est dans 8 à 12 ans


def test_fallback_answers_the_top3_question_with_each_position(real_service):
    from guardian.agent.fallback import build_fallback
    for tools in ((EV,), (EV, CK)):
        recs = [NS(tool=n, status="ok", result=r) for n, r in outputs(real_service, AMIRA, "amira", tools).items()]
        fb = build_fallback(recs)
        assert ("trois plus grandes positions : NVDA 25 % (action individuelle), QQQ 25 % (FNB d'actions), BTC-USD 20 % (cryptoactif) ; "
                "total : 70 % du portefeuille.") in fb
        assert "Ce que cela signifie" in fb and "diversification sous-jacente des FNB n'est pas mesurée" in fb
        assert "attention > 20 %, conflit > 35 %" in fb and "risque élevé, horizon 15 ans ou plus" in fb
    mateo = [NS(tool=EV, status="ok", result=outputs(real_service, MATEO, "mateo", (EV,))[EV])]
    assert "Égalité" in build_fallback(mateo)                                                       # égalités signalées, pas de classement inventé


def test_agent_withholds_the_manual_test_answer_and_shows_the_complete_fallback(real_service):
    from conftest import StepModel
    from guardian.agent.agent import GuardianAgent
    bad = ("Vos trois plus grosses positions sont NVDA (25 %), QQQ (25 %) et BTC-USD (20 %), soit 70 %. Le seuil de concentration de 30 % est dépassé. "
           "Pour un profil modéré sur un horizon de 10 ans, cette concentration est élevée.")
    model = StepModel([("tools", [EV]), ("text", bad)])
    tr = GuardianAgent(real_service, SessionContext(W[AMIRA], "amira"), Tracer(), model_factory=lambda: model).ask(Q_TOP3)
    assert tr.withheld and tr.text is None and {"valeur_associee", "persona"} <= {v["category"] for v in tr.claims["violations"]}
    assert "NVDA 25 % (action individuelle), QQQ 25 % (FNB d'actions), BTC-USD 20 % (cryptoactif) ; total : 70 %" in tr.fallback


def test_real_correct_top3_answer_after_the_fix_is_accepted_and_a_wrong_threshold_in_it_is_not(real_service):
    """Essai Bedrock réel après correction (Nova 2 Lite, evaluate_portfolio seul) : texte correct, d'abord retenu à tort
    (« vigilance si > 20 %, conflit si > 35 % » et « 70 % de concentration sur trois lignes »)."""
    from pathlib import Path
    real = (Path(__file__).parent / "golden" / "v33_live_amira_top3.md").read_text(encoding="utf-8")
    rep = verdict(real_service, real, AMIRA, "amira", (EV,))
    assert rep.ok and rep.anchored_numbers >= 6, [v.to_dict() for v in rep.violations]
    for wrong in (real.replace("vigilance si > 20 %", "vigilance si > 30 %"), real.replace("représentent **70 %", "représentent **75 %"),
                  real.replace("horizon 15 ans ou plus, niveau de risque élevé", "horizon de 10 ans, niveau de risque modéré")):
        assert not verdict(real_service, wrong, AMIRA, "amira", (EV,)).ok
