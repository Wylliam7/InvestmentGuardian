"""V2 — cœur déterministe : non-régression V1, cartes Guardian, résumé prioritaire, diversification, comparaison, traçabilité niveau 1."""
import json
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from conftest import REPO
from guardian.explain.cards import LEVELS, PLAIN_TITLES, build_cards, diversification_sentence
from guardian.explain.compare_plain import plain_tradeoffs
from guardian.explain.format import fr, pct, pct_value
from guardian.explain.glossary import DIVERSIFICATION_HELP, METRIC_HELP, TERMS
from guardian.explain.summary import THEMES, build_priority_summary
from guardian.explain.trace_view import describe_calls, summary_lines
from guardian.finance.presets import load_presets
from guardian.rules.engine import ATTENTION, CONFLIT, INFO, OK

BASELINE = json.loads((REPO / "tests" / "golden" / "v1_baseline.json").read_text(encoding="utf-8"))["cases"]
NVDA40 = {"NVDA": .40, "XBB.TO": .35, "XIU.TO": .25}
V1_COMMIT = "e5044f8"
JARGON = [r"[Ss]euil heuristique", r"[Rr]ègle métier Python", r"max\(poids_i\)", r"[Cc]onfiguration 0\.2", r"\bR(1|2|4|5|7|10)\b", r"\bCONFLIT\b", r"\bATTENTION\b", r"\bHHI\b"]


def cases():
    for key in BASELINE:
        pid, prof = key.split("|")
        yield pid, prof, {t: v / 100 for t, v in load_presets()[pid]["weights_pct"].items()}


# ============================================================ 17. calculs, seuils et statuts inchangés depuis V1
def test_engine_results_match_the_v1_baseline_exactly(real_service):
    for pid, prof, w in cases():
        res, rep = real_service.check(w, prof)
        d, ref = res.to_tool_dict(), BASELINE[f"{pid}|{prof}"]
        assert d["metrics"] == ref["metrics"], (pid, prof)
        assert d["concentration"] == ref["concentration"], (pid, prof)
        for rid, rf in ref["findings"].items():
            f = rep.by_id()[rid]
            assert f.status == rf["status"], (pid, prof, rid)                              # statuts inchangés entre V1 et V2
            assert f.threshold_attention == rf["attention"] and f.threshold_conflict == rf["conflict"], (pid, prof, rid)
            if rf["measured"] is not None:
                assert f.measured == pytest.approx(rf["measured"], rel=1e-12), (pid, prof, rid)


@pytest.mark.skipif(shutil.which("git") is None, reason="git indisponible")
def test_financial_engine_rules_data_and_thresholds_are_untouched_since_v1():
    probe = subprocess.run(["git", "cat-file", "-t", V1_COMMIT], cwd=REPO, capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("commit V1 absent de ce dépôt")
    # le code de calcul (finance, règles, données) est identique à V1 ; V3 n'ajoute que des profils et des modules distincts
    diff = subprocess.run(["git", "diff", "--stat", V1_COMMIT, "--", "src/guardian/finance/analysis.py", "src/guardian/finance/metrics.py",
                           "src/guardian/finance/panel.py", "src/guardian/finance/portfolio.py", "src/guardian/finance/compare.py",
                           "src/guardian/rules", "src/guardian/data", "config/data_manifest.yaml"], cwd=REPO, capture_output=True, text=True)
    assert diff.stdout.strip() == "", diff.stdout
    def old(path):
        return yaml.safe_load(subprocess.run(
            ["git", "show", f"{V1_COMMIT}:{path}"], cwd=REPO, capture_output=True,
            text=True, encoding="utf-8", check=True,
        ).stdout)
    cur_rules = yaml.safe_load((REPO / "config" / "guardian_rules.yaml").read_text(encoding="utf-8"))
    old_rules = yaml.safe_load(subprocess.run(
        ["git", "show", f"{V1_COMMIT}:config/guardian_rules.yaml"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    assert old_rules["volatile_asset_vol_threshold"] == cur_rules["volatile_asset_vol_threshold"]
    for rid, rule in old_rules["rules"].items():
        for prof, th in rule["thresholds"].items():                                         # seuils de Robert et d'Amira : valeurs identiques à V1
            assert cur_rules["rules"][rid]["thresholds"][prof] == th, (rid, prof)
        assert {k: v for k, v in cur_rules["rules"][rid].items() if k != "thresholds"} == {k: v for k, v in rule.items() if k != "thresholds"}
    cur_profiles = yaml.safe_load((REPO / "config" / "profiles.yaml").read_text(encoding="utf-8"))["profiles"]
    old_profiles = old("config/profiles.yaml")["profiles"]
    for pid, prof in old_profiles.items():
        assert cur_profiles[pid] == prof, pid                                               # profils Robert et Amira inchangés


def test_official_csv_files_are_unchanged():
    from guardian.data.loader import load_bundle
    assert load_bundle().manifest_mismatch == ()


# ============================================================ cartes Guardian
def test_card_for_r1_matches_the_expected_wording_for_robert(real_service):
    res, rep = real_service.check(NVDA40, "robert")
    cards = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg)}
    c = cards["R1"]
    assert c.status == CONFLIT and c.level_label == "Risque important à examiner"
    assert c.headline == "Votre portefeuille dépend beaucoup de NVIDIA."
    assert c.measure == "NVIDIA représente 40 % de votre argent fictif."
    assert c.why.startswith("Pour Robert (horizon de 3 à 5 ans, risque faible à modéré) :") and "Préserver" not in c.why     # rappel court : l'objectif complet est affiché une fois au-dessus des cartes
    assert "une position qui dépasse 20 % mérite une vigilance importante pour le profil de Robert" in c.precision
    assert "pédagogique" in c.precision and "norme universelle" in c.precision
    assert any("Un fonds qui détient plusieurs entreprises peut être plus diversifié qu'une action individuelle" in lim for lim in c.limits)
    assert c.advanced["Règle"] == "R1" and c.advanced["Statut interne"] == "CONFLIT" and "Version de la configuration" in c.advanced
    assert "max(poids_i)" in c.advanced["Méthode (technique)"]                                # le jargon reste disponible, mais seulement ici


def test_cards_keep_internal_statuses_and_map_to_plain_vigilance_levels(real_service):
    expected = {CONFLIT: "Risque important à examiner", ATTENTION: "Point de vigilance", OK: "Aucun dépassement détecté selon ce critère", INFO: "Information complémentaire"}
    assert {k: v[1] for k, v in LEVELS.items()} == expected
    for pid, prof, w in cases():
        res, rep = real_service.check(w, prof)
        cards = build_cards(res, rep, real_service.profiles[prof], real_service.bundle.universe, real_service.rules_cfg)
        assert [c.rule_id for c in cards] == ["R1", "R2", "R4", "R5", "R7", "R10"]
        for c in cards:
            assert c.status == rep.by_id()[c.rule_id].status == BASELINE[f"{pid}|{prof}"]["findings"][c.rule_id]["status"]
            assert c.level_label == expected[c.status]


def test_main_card_text_contains_no_jargon_but_details_keep_it(real_service):
    for pid, prof, w in cases():
        res, rep = real_service.check(w, prof)
        for c in build_cards(res, rep, real_service.profiles[prof], real_service.bundle.universe, real_service.rules_cfg):
            main = " ".join([c.level_label, c.headline, c.measure, c.why, c.precision])
            for pat in JARGON:
                assert not re.search(pat, main), (pid, prof, c.rule_id, pat, main)
            assert c.how and c.limits and c.advanced["Règle"] == c.rule_id and c.advanced["Statut interne"] == c.status


def test_every_card_value_matches_the_engine_measurement(real_service):
    res, rep = real_service.check(NVDA40, "robert")
    cards = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles["robert"], real_service.bundle.universe, real_service.rules_cfg)}
    assert fr(100 * rep.by_id()["R4"].measured) in cards["R4"].measure                           # 22,3
    assert fr(100 * rep.by_id()["R5"].measured) in cards["R5"].measure and "du 29 novembre 2021 au 14 octobre 2022" in cards["R5"].measure
    assert "le 17 mai 2023" in cards["R5"].measure
    assert "40 %" in cards["R2"].measure and "NVIDIA" in cards["R2"].measure
    assert cards["R7"].measure == diversification_sentence(res)


def test_profile_changes_the_why_and_the_precision_but_not_the_measure(real_service):
    res, _ = real_service.check(NVDA40, "robert")
    out = {}
    for prof in ("robert", "amira"):
        rep = real_service.check(NVDA40, prof)[1]
        out[prof] = {c.rule_id: c for c in build_cards(res, rep, real_service.profiles[prof], real_service.bundle.universe, real_service.rules_cfg)}
    assert out["robert"]["R1"].measure == out["amira"]["R1"].measure and out["robert"]["R4"].measure == out["amira"]["R4"].measure
    assert "Robert" in out["robert"]["R1"].why and "Amira" in out["amira"]["R1"].why and "Amira" in out["amira"]["R1"].precision
    assert "35 %" in out["amira"]["R1"].precision and "20 %" in out["robert"]["R1"].precision
    assert "certaine diversification" in out["amira"]["R1"].why                                # préférence officielle d'Amira citée
    assert out["amira"]["R4"].status == OK and out["amira"]["R4"].level_label == "Aucun dépassement détecté selon ce critère"
    assert "tolérance personnelle réelle" in out["robert"]["R5"].why


def test_amira_info_card_shows_the_tech_share_without_any_threshold(real_service):
    w = {t: v / 100 for t, v in load_presets()["amira_tech_crypto"]["weights_pct"].items()}
    res, rep = real_service.check(w, "amira")
    c = {x.rule_id: x for x in build_cards(res, rep, real_service.profiles["amira"], real_service.bundle.universe, real_service.rules_cfg)}["R10"]
    assert c.status == INFO and c.level_label == "Information complémentaire" and "technologie" in c.measure and "aucun repère" in c.precision.lower()


# ============================================================ 5. résumé prioritaire fidèle
def test_priority_summary_is_faithful_to_the_flagged_rules(real_service):
    theme_of = {r: th for th, rules in THEMES for r in rules}
    for pid, prof, w in cases():
        res, rep = real_service.check(w, prof)
        s = build_priority_summary(res, rep, real_service.profiles[prof], real_service.bundle.universe)
        flagged = {rid for rid, f in rep.by_id().items() if f.status in (CONFLIT, ATTENTION)}
        covered = {r for it in s.items for r in it.rules}
        assert covered == flagged, (pid, prof)                                                 # ni plus, ni moins que les constats réels
        assert {theme_of[r] for r in flagged} == {it.theme for it in s.items} and s.n_items <= 3
        assert all(rep.by_id()[r].status in (CONFLIT, ATTENTION) for it in s.items for r in it.rules)
        assert s.n_flagged_rules == len(flagged) and s.profile_name == real_service.profiles[prof]["display_name"]
        words = {0: "aucun repère", 1: "un élément mérite", 2: "deux éléments méritent", 3: "trois éléments méritent"}[s.n_items]
        assert words in s.sentence, (pid, prof, s.sentence)
        if s.n_items == 0:
            assert "particulièrement" not in s.sentence and "sans risque" in s.sentence


def test_summary_never_claims_more_items_than_exist_and_groups_correlated_rules(real_service):
    # Robert prudent : un seul constat (R1 : attention) → un seul élément, jamais « trois »
    w = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    res, rep = real_service.check(w, "robert")
    s = build_priority_summary(res, rep, real_service.profiles["robert"], real_service.bundle.universe)
    assert s.n_items == 1 and "un élément mérite" in s.sentence and "trois" not in s.sentence and s.related_note is None
    # Robert Nvidia 40 % : cinq règles dépassées mais seulement trois thèmes (R1+R7, R2, R4+R5), jamais « cinq risques »
    res, rep = real_service.check(NVDA40, "robert")
    s = build_priority_summary(res, rep, real_service.profiles["robert"], real_service.bundle.universe)
    assert s.n_flagged_rules == 5 and s.n_items == 3 and "cinq" not in s.sentence
    assert "NVIDIA" in s.items[0].text and "40 %" in s.sentence and fr(100 * res.volatility) in s.sentence
    assert s.related_note and "ne s'agit donc pas de risques entièrement indépendants" in s.related_note


def test_summary_is_deterministic_and_needs_no_ai(real_service):
    res, rep = real_service.check(NVDA40, "amira")
    a = build_priority_summary(res, rep, real_service.profiles["amira"], real_service.bundle.universe)
    b = build_priority_summary(res, rep, real_service.profiles["amira"], real_service.bundle.universe)
    assert a == b and a.sentence.startswith("Pour Amira,")


# ============================================================ 6. nombre effectif vs nombre réel
def test_diversification_sentence_distinguishes_real_and_effective_positions(real_service):
    res = real_service.analyze(NVDA40)
    assert diversification_sentence(res) == ("Votre portefeuille contient 3 actifs. Selon la répartition de leurs poids, sa diversification est "
                                             "équivalente à environ 2,9 positions de poids égal.")
    w = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    res12 = real_service.analyze(w)
    assert "contient 12 actifs" in diversification_sentence(res12) and "environ 10,0 positions de poids égal" in diversification_sentence(res12)
    assert res.concentration.effective_n == pytest.approx(1 / res.concentration.hhi)       # calcul HHI inchangé
    assert "nombre d'entreprises sous-jacentes" in DIVERSIFICATION_HELP and "corrélations" in DIVERSIFICATION_HELP and "FNB" in DIVERSIFICATION_HELP
    one = real_service.analyze({"SPY": 1.0})
    assert "contient 1 actif." in diversification_sentence(one) and "1,0 position de poids égal" in diversification_sentence(one)


def test_glossary_covers_the_five_required_terms_and_tooltips_keep_technical_names():
    assert set(TERMS) == {"Actif", "Pondération", "FNB", "Allocation", "Portefeuille fictif"}
    assert "volatilité" in METRIC_HELP["volatility"] and "drawdown" in METRIC_HELP["drawdown"] and "rendement cumulé" in METRIC_HELP["return"].lower()
    assert "pas un rendement attendu" in METRIC_HELP["return"] and "1/HHI" in METRIC_HELP["diversification"]


# ============================================================ comparaison simplifiée
def test_plain_tradeoffs_use_exact_values_and_never_name_a_winner(real_service):
    prudent = {t: v / 100 for t, v in load_presets()["robert_prudent"]["weights_pct"].items()}
    cmp_ = real_service.compare(NVDA40, prudent, "robert")
    lines = plain_tradeoffs(cmp_)
    text = " ".join(lines)
    assert any(l.startswith("A a eu un rendement historique supérieur : 180,9 % contre 62,9 % pour B") for l in lines)
    assert any(l.startswith("B a connu des fluctuations moins importantes : 6,9 % par an contre 22,3 % pour A") for l in lines)
    assert any(l.startswith("A a connu une baisse maximale plus profonde : −36,1 % contre −8,4 % pour B") for l in lines)
    assert any("B est plus réparti entre ses positions : environ 10,0 positions de poids égal (12 actifs) contre 2,9 pour A (3 actifs)" in l for l in lines)
    assert not re.search(r"\b(meilleur|meilleure|pire|gagnant|recommand\w*|optimal\w*)\b", text, re.I)


def test_plain_tradeoffs_for_identical_portfolios_say_close(real_service):
    lines = plain_tradeoffs(real_service.compare(NVDA40, dict(NVDA40), "robert"))
    assert all("proches" in l or "comparable" in l for l in lines) and len(lines) == 4


# ============================================================ 15. traçabilité niveau 1 = uniquement des appels réellement exécutés
def rec(i, tool, status="ok", args=None, result=None, error=None, refs=None):
    return SimpleNamespace(id=i, tool=tool, status=status, arguments=args or {}, result=result, error=error, duration_ms=1.5, data_refs=refs or {})


PROFILES = {"robert": {"display_name": "Robert"}, "amira": {"display_name": "Amira"}}


def test_level1_lines_only_describe_executed_calls():
    recs = [rec(1, "evaluate_portfolio", args={"portfolio": "A"})]
    lines = describe_calls(recs, PROFILES, "robert")
    assert [l.text for l in lines] == ["A analysé votre portefeuille A (rendement, fluctuations, baisses, répartition)."]
    assert not any("comparé" in l.text for l in lines)                                      # aucune phrase pour un outil non exécuté
    assert describe_calls([], PROFILES, "robert") == []


def test_level1_describes_each_tool_with_a_plain_name_and_reports_failures():
    recs = [rec(1, "get_profile", args={"profile_id": "amira"}, result={"profile_id": "amira"}),
            rec(2, "check_profile_constraints", args={"portfolio": "B"}, result={"profile_id": "robert"}),
            rec(3, "compare_scenarios", result={"profile_id": "robert"}),
            rec(4, "evaluate_portfolio", status="error", args={"portfolio": "A"}, error="RuntimeError: panne")]
    texts = [l.text for l in describe_calls(recs, PROFILES, "robert")]
    assert texts[0] == "A consulté le profil officiel de Amira."
    assert texts[1] == "A comparé les risques du portefeuille B avec le profil de Robert (Guardian Check)."
    assert texts[2] == "A comparé les deux allocations A et B sur la même période pour Robert."
    assert texts[3].startswith("Tentative échouée") and "panne" in texts[3]


def test_level1_summary_has_period_currency_provenance_and_honest_disclaimers():
    refs = {"window": {"start": "2021-11-12", "end": "2026-11-12", "n_observations": 1228}, "reference_currency": "CAD",
            "files_sha256_prefix": {"prices_daily.csv": "ff2a3f2d0a7d"}}
    s = summary_lines([rec(1, "evaluate_portfolio", args={"portfolio": "A"}, refs=refs)], PROFILES, "robert")
    notes = " ".join(s["notes"])
    assert "2021-11-12" in notes and "1228" in notes and "CAD" in notes and "Yahoo Finance" in notes and "Banque du Canada" in notes
    disc = " ".join(s["disclaimers"])
    assert "interprétation" in disc and "pas vérifié phrase par phrase" in disc and "Python" in disc
    assert not re.search(r"entièrement vérifi|totalement vérifi|100 ?% vérifi", disc, re.I)
    assert s["n_ok"] == 1 and s["n_failed"] == 0
    none = summary_lines([], PROFILES, "robert")
    assert none["notes"] == [] and "Aucun outil financier n'a été exécuté avec succès" in none["disclaimers"][0]


def test_french_date_format():
    import datetime as dt
    from guardian.explain.format import fr_date
    assert fr_date(dt.date(2021, 11, 29)) == "29 novembre 2021" and fr_date(dt.date(2023, 1, 1)) == "1er janvier 2023"
