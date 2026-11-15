"""V3.3 (A + B) : contrôle générique des statuts Guardian (R1, R2, R4, R5, R7) et section « Faits et contrôles vérifiés ».

Les statuts de référence viennent du Guardian Check réel (aucune valeur codée en dur n'est supposée : chaque test vérifie d'abord sa précondition).
"""
from types import SimpleNamespace as NS

import pytest
from conftest import StepModel

pytestmark = pytest.mark.legacy_ui

from guardian.agent.agent import GuardianAgent
from guardian.agent.claims import check_claims
from guardian.agent.fallback import verified_facts
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.finance.presets import load_presets
from test_v2_app import patch_model, run_app

P = load_presets()
W = {k: {t: v / 100 for t, v in P[k]["weights_pct"].items()} for k in P}
EV, CK, CMP, GP, ESG = "evaluate_portfolio", "check_profile_constraints", "compare_scenarios", "get_profile", "check_esg_preferences"


def recs(service, preset, pid, tools=(EV, CK), preset_b=None):
    ctx = SessionContext(W[preset], pid, weights_b=W[preset_b] if preset_b else None)
    t = {x.tool_spec["name"]: x for x in build_tools(service, ctx, Tracer())}
    return [NS(tool=n, status="ok", result=t[n](), id=i + 1) for i, n in enumerate(tools)]


def statuses(rr, pf="A"):
    for r in rr:
        if r.tool == CK:
            return {f["rule_id"]: f["status"] for f in r.result["findings"]}
        if r.tool == CMP:
            return {f["rule_id"]: f["status"] for f in r.result[f"guardian_{pf}"]["findings"]}


def verdict(service, text, rr, pid):
    return check_claims(text, rr, service.profiles, pid, service.bundle.universe)


def status_viol(rep):
    return [v for v in rep.violations if v.category == "statut_guardian"]


@pytest.fixture(scope="module")
def amira(real_service):
    rr = recs(real_service, "amira_tech_crypto", "amira")
    assert statuses(rr) == {"R1": "ATTENTION", "R2": "CONFLIT", "R4": "CONFLIT", "R5": "CONFLIT", "R7": "OK", "R10": "INFO"}
    return rr


@pytest.fixture(scope="module")
def robert(real_service):
    rr = recs(real_service, "robert_nvda_40", "robert")
    assert {k: v for k, v in statuses(rr).items() if k != "R10"} == {r: "CONFLIT" for r in ("R1", "R2", "R4", "R5", "R7")}
    return rr


@pytest.fixture(scope="module")
def mateo(real_service):
    rr = recs(real_service, "mateo_croissance_equilibree", "mateo")
    assert {k: v for k, v in statuses(rr).items() if k != "R10"} == {"R1": "ATTENTION", "R2": "OK", "R4": "OK", "R5": "OK", "R7": "OK"}
    return rr


@pytest.fixture(scope="module")
def compare_ab(real_service):
    rr = recs(real_service, "robert_nvda_40", "robert", (CMP,), preset_b="robert_prudent")
    assert statuses(rr, "A")["R1"] == "CONFLIT" and statuses(rr, "B")["R1"] == "ATTENTION"
    return rr


# ============================================================ phrases fausses : refusées
@pytest.mark.parametrize("fixture,pid,text", [
    ("amira", "amira", "Le nombre effectif de positions (5,0) franchit le seuil de conflit."),                    # R7 = OK (exemple de la consigne)
    ("amira", "amira", "Le seuil de conflit du nombre effectif de positions est dépassé."),
    ("amira", "amira", "La concentration dans NVDA est en conflit avec le profil d'Amira."),                        # R1 = ATTENTION
    ("amira", "amira", "La plus grande position (25 %) dépasse le seuil de conflit."),
    ("amira", "amira", "La concentration dans un actif reste sous le seuil d'attention."),
    ("amira", "amira", "Aucun risque lié aux actifs volatils pour Amira."),                                         # R2 = CONFLIT (exemple de la consigne)
    ("amira", "amira", "La volatilité du portefeuille ne dépasse pas le seuil de conflit."),                        # R4 = CONFLIT
    ("amira", "amira", "La plus forte baisse historique est sous le seuil de conflit."),                            # R5 = CONFLIT
    ("amira", "amira", "Aucun repère n'est dépassé pour Amira."),                                                    # constat général faux
    ("amira", "amira", "Le Guardian Check identifie cinq conflits potentiels."),                                    # 3 en réalité
    ("robert", "robert", "La volatilité du portefeuille (22,28 %) reste sous les repères du prototype pour Robert."),
    ("robert", "robert", "Le nombre effectif de positions (2,9) est au-dessus du seuil de conflit."),             # R7 plancher : au-dessus = pas en conflit
    ("robert", "robert", "Le Guardian Check ne signale qu'un seul point de vigilance pour Robert."),
    ("robert", "robert", "La concentration dans un actif : statut OK."),
    ("mateo", "mateo", "La concentration dans un actif dépasse le seuil de conflit pour Mateo."),                  # R1 = ATTENTION
    ("mateo", "mateo", "La volatilité du portefeuille est en conflit avec le profil de Mateo."),                    # R4 = OK
    ("mateo", "mateo", "Le nombre effectif de positions est sous le seuil d'attention."),                          # R7 plancher : sous = vigilance
])
def test_wrong_status_claims_are_rejected(request, real_service, fixture, pid, text):
    rep = verdict(real_service, text, request.getfixturevalue(fixture), pid)
    assert status_viol(rep), [v.to_dict() for v in rep.violations]


# ============================================================ phrases correctes : acceptées
@pytest.mark.parametrize("fixture,pid,text", [
    ("amira", "amira", "Le nombre effectif de positions (5,0) est au niveau OK : il ne franchit pas le seuil de conflit."),
    ("amira", "amira", "Nombre effectif de positions (lignes) : 5,0 : OK (au-dessus du seuil de vigilance)."),       # réponse réelle
    ("amira", "amira", "La plus grande position (25 %) dépasse le seuil d'attention mais reste sous le seuil de conflit."),
    ("amira", "amira", "Plus grande position à 25 % : vigilance (au-dessus du seuil de vigilance mais en dessous du seuil de conflit)."),
    ("amira", "amira", "La concentration dans un actif n'est pas en conflit : c'est un point de vigilance."),
    ("amira", "amira", "La volatilité du portefeuille (35,32 %) dépasse le seuil de conflit de 35 %."),
    ("amira", "amira", "Le Guardian Check a identifié 3 conflits potentiels et 1 point d'attention pour Amira."),   # réponse réelle
    ("robert", "robert", "R7 (Diversification) : 2,9 positions effectives < seuil de conflit à 4 → Conflit."),       # réponse réelle
    ("robert", "robert", "Le Guardian Check identifie cinq conflits potentiels avec les objectifs déclarés de Robert."),
    ("robert", "robert", "Aucun point d'attention."),
    ("mateo", "mateo", "La concentration dans un actif (20 %) dépasse le seuil d'attention de 15 % défini pour Mateo."),
    ("mateo", "mateo", "La volatilité du portefeuille ne dépasse pas le seuil d'attention."),
])
def test_correct_status_claims_are_accepted(request, real_service, fixture, pid, text):
    rep = verdict(real_service, text, request.getfixturevalue(fixture), pid)
    assert not status_viol(rep), [v.to_dict() for v in rep.violations]
    assert rep.status_checked >= 1


# ============================================================ cas ambigus : aucun verdict (pas de faux positif)
@pytest.mark.parametrize("text", [
    "La diversification d'Amira présente un conflit potentiel selon les seuils heuristiques du prototype.",          # « diversification » : R7 ou constat général
    "La forte concentration et la volatilité élevée exposent le portefeuille à des baisses importantes.",           # deux critères
    "Ce portefeuille est concentré et volatil, ce qui mérite une attention particulière.",                          # qualitatif nuancé
    "Le portefeuille présente plusieurs conflits potentiels avec les objectifs déclarés d'Amira.",                  # nombre non précisé
    "Cette concentration présente un conflit potentiel avec la préférence d'Amira pour les technologies.",         # préférence technologique (aucun statut)
    "NVDA est un actif très volatil (50,71 % de volatilité annualisée).",                                          # deux critères, aucun statut affirmé
])
def test_ambiguous_or_qualitative_sentences_get_no_status_verdict(real_service, amira, text):
    assert not status_viol(verdict(real_service, text, amira, "amira"))


# ============================================================ portefeuilles A et B, profils multiples
def test_portfolios_a_and_b_are_not_confused(real_service, compare_ab):
    assert not status_viol(verdict(real_service, "Le portefeuille B présente un point de vigilance sur la concentration dans un actif.", compare_ab, "robert"))
    assert status_viol(verdict(real_service, "Le portefeuille A présente un simple point de vigilance sur la concentration dans un actif.", compare_ab, "robert"))
    assert status_viol(verdict(real_service, "La concentration dans un actif du portefeuille B est en conflit.", compare_ab, "robert"))
    head = "- **Portefeuille B** (Robert)\n  - Concentration dans un actif (15 % > seuil d'attention à 10 %)"         # en-tête de liste (réponse réelle)
    assert not status_viol(verdict(real_service, head, compare_ab, "robert"))
    assert not status_viol(verdict(real_service, "La concentration dans un actif est en conflit.", compare_ab, "robert"))   # A ou B ? statuts différents : pas de verdict


def test_two_profiles_in_one_request_are_not_confused(real_service):
    rr = recs(real_service, "robert_nvda_40", "robert", (CK,))
    ctx = SessionContext(W["robert_nvda_40"], "robert", allowed_profiles={"robert", "amira"})
    ck_amira = {x.tool_spec["name"]: x for x in build_tools(real_service, ctx, Tracer())}[CK](profile_id="amira")
    rr = rr + [NS(tool=CK, status="ok", result=ck_amira, id=9)]
    st_a = {f["rule_id"]: f["status"] for f in ck_amira["findings"]}
    assert st_a["R2"] == "ATTENTION" and statuses(rr[:1])["R2"] == "CONFLIT"                    # même portefeuille, statut R2 différent selon le profil
    assert not status_viol(verdict(real_service, "Pour Amira, l'exposition aux actifs volatils est un point de vigilance.", rr, "robert"))
    assert status_viol(verdict(real_service, "Pour Robert, l'exposition aux actifs volatils est un simple point de vigilance.", rr, "robert"))
    assert not status_viol(verdict(real_service, "L'exposition aux actifs volatils est un point de vigilance.", rr, "amira"))   # profil non nommé = profil actif (Amira)


def test_without_guardian_check_no_status_is_claimed_as_verified(real_service):
    """Sans Guardian Check : aucune affirmation n'est comptée comme vérifiée par lui. R1 / R7 sont seulement comparés à la mesure et aux repères
    transmis par evaluate_portfolio (cohérence), et le message le dit."""
    rr = recs(real_service, "amira_tech_crypto", "amira", (EV,))
    rep = verdict(real_service, "Le nombre effectif de positions franchit le seuil de conflit.", rr, "amira")
    assert rep.status_checked == 0 and rep.status_derived == 1 and rep.status_unverified
    assert status_viol(rep) and "le Guardian Check n'a pas été exécuté pendant cette requête" in status_viol(rep)[0].message
    assert "le Guardian Check n'a pas été exécuté pendant cette requête" in rep.summary() and "pas un statut du Guardian Check" in rep.summary()
    ok = verdict(real_service, "Le nombre effectif de positions (5,0) ne franchit pas le seuil de conflit.", rr, "amira")
    assert not status_viol(ok) and ok.status_derived == 1
    assert not status_viol(verdict(real_service, "La volatilité du portefeuille dépasse le seuil de conflit.", rr, "amira"))   # R4 : ni mesure ni repère transmis


# ============================================================ agent : retenue et repli
def test_agent_withholds_a_status_contradiction_and_shows_the_real_statuses(real_service):
    model = StepModel([("tools", [EV, CK]), ("text", "Le nombre effectif de positions (5,0) franchit le seuil de conflit.")])
    tr = GuardianAgent(real_service, SessionContext(W["amira_tech_crypto"], "amira"), Tracer(), model_factory=lambda: model).ask("Ma diversification est-elle suffisante ?")
    assert tr.withheld and "statut_guardian" in {v["category"] for v in tr.claims["violations"]}
    assert "Diversification (nombre effectif de positions) : Conforme" in tr.fallback


# ============================================================ A : section « Faits et contrôles vérifiés »
def flat(secs):
    return "\n".join(t + "\n" + "\n".join(lines) for t, lines in secs)


def test_section_with_evaluate_only_shows_configured_thresholds_but_no_status(real_service):
    secs = verified_facts(recs(real_service, "amira_tech_crypto", "amira", (EV,)))
    txt = flat(secs)
    assert "evaluate_portfolio (métriques du portefeuille)" in txt and "check_profile_constraints" not in txt
    assert "Amira, 26 ans · risque élevé · horizon 15 ans ou plus" in txt
    assert "Trois plus grandes positions : NVDA 25 %, QQQ 25 %, BTC-USD 20 % · total 70 %" in txt
    assert "aucun statut évalué : le Guardian Check n'a pas été exécuté pendant cette requête" in txt
    assert "Plus grande position : attention > 20 %, conflit > 35 %" in txt
    assert not any(w in txt for w in ("**Conflit**", "**Attention**", "**Conforme**", "Statuts évalués"))


def test_section_with_guardian_check_shows_each_evaluated_status_with_measure_and_thresholds(real_service, amira):
    txt = flat(verified_facts(amira))
    assert "Statuts évalués par le Guardian Check (portefeuille A" in txt and "Repères configurés" not in txt
    for f in amira[1].result["findings"]:
        if f["status"] != "INFO":
            assert f"{f['rule_id']} · {f['title']} : **{f['status_label']}**" in txt
    assert "R7 · Diversification (nombre effectif de positions) : **Conforme**" in txt and "R1 · Concentration dans un actif : **Attention**" in txt


def test_section_for_a_b_comparison_keeps_portfolios_separate(real_service, compare_ab):
    txt = flat(verified_facts(compare_ab))
    assert "— portefeuille A" in txt and "— portefeuille B" in txt
    a, b = txt.split("Statuts évalués par le Guardian Check — portefeuille A")[1].split("Statuts évalués par le Guardian Check — portefeuille B")
    assert "R1 · Concentration dans un actif : **Conflit**" in a and "R1 · Concentration dans un actif : **Attention**" in b


def test_section_for_esg_shows_state_coverage_categories_and_limits(real_service):
    txt = flat(verified_facts(recs(real_service, "mateo_actions_canadiennes", "mateo", (ESG,))))
    assert "État global : Controverse documentée à examiner · couverture (part cherchée dans les sources) : 85 %" in txt
    assert "exclusion environnementale : 15 % du portefeuille (CNQ.TO)" in txt and "mise sous observation de gouvernance : 15 % du portefeuille (TD.TO)" in txt
    assert "FNB sans composition (XBB.TO)" in txt and "Aucun seuil ni score ESG" in txt
    assert "Statuts évalués" not in txt and "Repères configurés" not in txt                       # aucun outil financier : rien d'inventé


def test_section_lists_failed_tools_and_uses_nothing_from_them(real_service):
    rr = recs(real_service, "amira_tech_crypto", "amira", (EV,)) + [NS(tool=CK, status="error", result=None, id=2)]
    txt = flat(verified_facts(rr))
    assert "En échec : check_profile_constraints" in txt and "Statuts évalués" not in txt
    assert verified_facts([NS(tool=CK, status="error", result=None, id=1)]) == []


def test_page_shows_the_section_from_tool_results_not_from_the_model_text(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK]), ("text", "Texte libre du modèle, sans chiffres.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    at.selectbox(key="preset_A").set_value("amira_tech_crypto").run()
    at.text_area(key="q_text").set_value("Ma diversification est-elle suffisante ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    exp = [e for e in at.expander if e.label.startswith("Faits et contrôles vérifiés")]
    assert len(exp) == 1 and exp[0].proto.expanded is True
    inside = " ".join(m.value for m in exp[0].markdown)
    assert "R7 · Diversification (nombre effectif de positions) : **Conforme**" in inside and "NVDA 25 %, QQQ 25 %, BTC-USD 20 % · total 70 %" in inside
    assert "Texte libre du modèle" not in inside


def test_page_does_not_duplicate_facts_when_the_answer_is_withheld(monkeypatch):
    patch_model(monkeypatch, [("tools", [EV, CK]), ("text", "Le nombre effectif de positions (5,0) franchit le seuil de conflit.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("amira").run()
    at.selectbox(key="preset_A").set_value("amira_tech_crypto").run()
    at.text_area(key="q_text").set_value("Ma diversification est-elle suffisante ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert any("Faits vérifiés, issus directement des calculs Python" in m.value for m in at.markdown)
    assert not [e for e in at.expander if e.label.startswith("Faits et contrôles vérifiés")]


# ============================================================ constats globaux sans Guardian Check, réponses réelles (Bedrock, après A + B)
@pytest.mark.parametrize("text", [
    "En résumé, le portefeuille reste dans les limites des seuils de vigilance du prototype pour le profil d'Amira.",   # réponse réelle
    "Aucun repère n'est dépassé pour ce portefeuille.",
    "Tous les repères sont respectés.",
])
def test_global_status_claims_without_guardian_check_are_unverifiable(real_service, text):
    rep = verdict(real_service, text, recs(real_service, "amira_tech_crypto", "amira", (EV,)), "amira")
    assert "statut_non_verifiable" in {v.category for v in rep.violations}


def test_global_claim_naming_a_criterion_is_ambiguous_and_not_blocked(real_service):
    """La phrase réelle vise peut-être seulement R1/R7 (repères cités juste avant) : portée ambiguë, pas de verdict."""
    text = "Bien qu'aucun seuil de conflit ne soit franchi selon les seuils heuristiques du prototype, cette concentration expose le portefeuille à un risque."
    rep = verdict(real_service, text, recs(real_service, "amira_tech_crypto", "amira", (EV,)), "amira")
    assert not {"statut_non_verifiable", "statut_guardian"} & {v.category for v in rep.violations}


def test_collective_figure_on_three_assets_is_the_top3_total(real_service):
    rep = verdict(real_service, "La concentration élevée sur trois actifs (70 % du portefeuille) mérite attention.",
                  recs(real_service, "amira_tech_crypto", "amira", (EV,)), "amira")
    assert not [v for v in rep.violations if v.category == "valeur_associee"], [v.to_dict() for v in rep.violations]


LIVE = __import__("json").loads((__import__("pathlib").Path(__file__).parent / "golden" / "v33_live_status_answers.json").read_text(encoding="utf-8"))
LIVE_CTX = {"amira": ("amira_tech_crypto", None), "robert": ("robert_nvda_40", "robert_prudent"), "mateo": ("mateo_croissance_equilibree", None)}
LIVE_EXPECT = {"amira": (True, {"statut_non_verifiable"}, 0), "robert": (False, set(), 2), "mateo": (True, {"ordre", "valeur_associee"}, 6)}


@pytest.mark.parametrize("i", range(3))
def test_real_answers_after_a_and_b_get_the_reviewed_verdict(real_service, i):
    """Réponses Bedrock réelles relues à la main : Amira (constat global invérifiable), Robert A/B (juste), Mateo (conseil + unité « 3,5 % »)."""
    g = LIVE[i]
    pa, pb = LIVE_CTX[g["persona"]]
    rep = verdict(real_service, g["text"], recs(real_service, pa, g["persona"], tuple(g["tools"]), preset_b=pb), g["persona"])
    held, cats_, n = LIVE_EXPECT[g["persona"]]
    assert (not rep.ok) == held and {v.category for v in rep.violations} == cats_ and rep.status_checked == n, [v.to_dict() for v in rep.violations]
