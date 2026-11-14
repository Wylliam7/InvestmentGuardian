"""V3.2 : visibilité des sources ESG. Chaque constat est associé à sa source ; aucun lien n'est inventé ; sans URL vérifiée : « Référence à vérifier »."""
import copy
import re

import pytest
import yaml
from conftest import REPO, StepModel
from guardian.agent.agent import GuardianAgent
from guardian.agent.tools import SessionContext, build_tools
from guardian.agent.tracer import Tracer
from guardian.esg.data import EsgDataError, load_esg_data, parse_esg_data
from guardian.esg.engine import evaluate_esg
from guardian.esg.references import LINK_LABEL, TO_VERIFY, build_reference
from guardian.explain.esg_view import build_esg_view, build_references_from_tool_result
from guardian.finance.presets import load_presets
from test_v2_app import patch_model, run_app
from test_v3_core import fictional_esg

PRESETS = load_presets()
MATEO_A = {t: v / 100 for t, v in PRESETS["mateo_croissance_equilibree"]["weights_pct"].items()}
MATEO_B = {t: v / 100 for t, v in PRESETS["mateo_actions_canadiennes"]["weights_pct"].items()}
RAW = yaml.safe_load((REPO / "config" / "esg_sources.yaml").read_text(encoding="utf-8"))
NBIM_URL = "https://www.nbim.no/en/responsibility/exclusion-of-companies"
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def tool_out(service, weights):
    ctx = SessionContext(weights, "mateo")
    return {t.tool_spec["name"]: t for t in build_tools(service, ctx, Tracer())}["check_esg_preferences"]()


def registered_urls() -> set:
    urls = {s["url"] for s in RAW["sources"].values()}
    urls |= {r["decision_url"] for r in RAW["records"] if r.get("decision_url")}
    return urls


# ------------------------------------------------------------------ association constat -> source
def test_each_documented_finding_is_linked_to_its_own_source_decision_and_date(real_service):
    out = tool_out(real_service, MATEO_B)
    recs = {r["ticker"]: r for c in out["documented_categories"] + out["complementary_information"] for r in c["records"]}
    assert set(recs) == {"CNQ.TO", "TD.TO"}
    for t, (decision, published, company) in {"CNQ.TO": ("exclusion", "2020-05-13", "Canadian Natural Resources Ltd"),
                                              "TD.TO": ("observation", "2025-06-11", "Toronto-Dominion Bank/The")}.items():
        ref = recs[t]["reference"]
        assert ref["ticker"] == t and ref["decision"] == decision and ref["published"] == published and ref["company_name_in_source"] == company
        assert ref["source_id"] == recs[t]["source"] == "nbim_exclusion_list" and ref["consulted_on"] == "2026-11-14"
        assert "NBIM" in ref["source_name"]
    line_refs = {x["ticker"]: x["documented_records"][0]["reference"] for x in out["lines"] if x["documented_records"]}
    assert line_refs["CNQ.TO"]["decision"] == "exclusion" and line_refs["TD.TO"]["decision"] == "observation"


def test_view_cards_show_source_name_decision_type_date_and_clickable_official_link(real_service):
    view = build_esg_view(real_service.check_esg(MATEO_B, "mateo"), real_service.bundle.universe)
    cards = {c["ticker"]: c for c in view["controversies"] + view["complementary"]}
    assert cards["CNQ.TO"]["reference"]["decision_label"] == "Exclusion" and cards["CNQ.TO"]["reference"]["published_fr"] == "13 mai 2020"
    assert cards["TD.TO"]["reference"]["decision_label"] == "Mise sous observation" and cards["TD.TO"]["reference"]["published_fr"] == "11 juin 2025"
    for c in cards.values():
        r = c["reference"]
        assert r["url"] == NBIM_URL and r["link_label"] == LINK_LABEL and r["url_kind"] == "list_page" and "NBIM" in r["source_name"]
        assert "pas à une page dédiée à cette décision" in r["link_note"]            # page de liste : jamais présentée comme la décision précise


# ------------------------------------------------------------------ aucun lien inventé
def test_every_url_in_tool_output_and_view_is_a_registered_one(real_service):
    out = tool_out(real_service, MATEO_B)
    blob = repr(out) + repr(build_esg_view(real_service.check_esg(MATEO_B, "mateo"), real_service.bundle.universe))
    found = {u.rstrip(".,;") for u in URL_RE.findall(blob)}
    assert found and found <= registered_urls(), found - registered_urls()


def test_no_record_has_a_decision_url_so_no_link_claims_to_point_to_a_specific_decision(real_service):
    assert all(not r.get("decision_url") for r in RAW["records"])
    out = tool_out(real_service, MATEO_B)
    refs = [r["reference"] for c in out["documented_categories"] + out["complementary_information"] for r in c["records"]]
    assert refs and all(r["url_kind"] != "decision_page" for r in refs)


def test_decision_page_link_requires_a_registered_and_verified_decision_url():
    src = {"id": "s", "short_name": "Source", "url": "https://example.invalid/liste", "url_status": "verified", "url_kind": "list_page", "consulted_on": "2000-01-01"}
    rec = {"ticker": "X", "decision": "exclusion", "published": "2000-01-01", "criterion_fr": "c", "company_name_in_source": "X"}
    assert build_reference(src, rec)["url_kind"] == "list_page"
    with_url = {**rec, "decision_url": "https://example.invalid/decision/1", "decision_url_verified_on": "2000-01-02"}
    r = build_reference(src, with_url)
    assert r["url"] == "https://example.invalid/decision/1" and r["url_kind"] == "decision_page"
    unverified = {**rec, "decision_url": "https://example.invalid/decision/1"}                    # pas de date de vérification : ignorée
    assert build_reference(src, unverified)["url"] == "https://example.invalid/liste"
    raw = fictional_esg(documented=("MSFT",))
    raw["records"][0]["decision_url"] = "https://example.invalid/decision/1"
    with pytest.raises(EsgDataError, match="decision_url"):
        parse_esg_data(raw)


# ------------------------------------------------------------------ URL manquante ou non vérifiée
@pytest.mark.parametrize("src", [
    {"id": "s", "short_name": "Source X", "consulted_on": "2000-01-01"},                                                    # URL absente
    {"id": "s", "short_name": "Source X", "url": "", "url_status": "verified", "consulted_on": "2000-01-01"},                # URL vide
    {"id": "s", "short_name": "Source X", "url": "javascript:alert(1)", "url_status": "verified", "consulted_on": "2000-01-01"},  # schéma invalide
    {"id": "s", "short_name": "Source X", "url": "https://example.invalid/x", "url_status": "to_verify", "consulted_on": "2000-01-01"},  # non vérifiée
    None,
])
def test_missing_or_unverified_url_gives_reference_a_verifier_and_no_link(src):
    r = build_reference(src, {"ticker": "X", "decision": "exclusion", "published": "2000-01-01"})
    assert r["url"] is None and r["link_label"] == TO_VERIFY == "Référence à vérifier" and r["url_status"] == "to_verify"
    assert "Aucune adresse vérifiée" in r["link_note"]


def test_vanguard_fund_document_is_not_presented_as_a_verified_link(real_service):
    out = tool_out(real_service, {"ESGV": 0.5, "RY.TO": 0.5})
    note = out["fund_verification"]["fund_level_notes"][0]
    assert note["ticker"] == "ESGV" and note["reference"]["url"] is None and note["reference"]["link_label"] == "Référence à vérifier"
    assert "F4393" not in repr(note["reference"])


def test_unverified_source_in_config_is_declared_to_verify_in_yaml():
    assert RAW["sources"]["vanguard_esgv_profile"]["url_status"] == "to_verify"
    assert RAW["sources"]["nbim_exclusion_list"]["url_status"] == "verified" and RAW["sources"]["nbim_exclusion_list"]["url_kind"] == "list_page"
    assert load_esg_data().sources["nbim_exclusion_list"]["url_verified_on"] == "2026-11-14"


# ------------------------------------------------------------------ absence de correspondance et FNB
def test_titles_not_found_state_scope_source_date_and_that_absence_is_not_compliance(real_service):
    out = tool_out(real_service, MATEO_B)
    (sc,) = out["search_scope"]
    assert {x["ticker"] for x in sc["not_found"]} == {"RY.TO", "ENB.TO", "CNR.TO", "FTS.TO"} and sc["weight_pct"] == 55.0
    assert sc["source_id"] == "nbim_exclusion_list" and sc["consulted_on"] == "2026-11-14" and sc["scope"]
    assert "n'est pas une preuve de conformité ESG" in sc["notice"] and sc["reference"]["url"] == NBIM_URL
    view = build_esg_view(real_service.check_esg(MATEO_B, "mateo"), real_service.bundle.universe)
    assert view["search_scope"][0]["notice"] == sc["notice"]


def test_non_evaluable_funds_say_no_complete_check_of_underlying_companies(real_service):
    out = tool_out(real_service, MATEO_A)
    fv = out["fund_verification"]
    assert "Aucune vérification complète des entreprises sous-jacentes" in fv["statement"] and fv["weight_pct"] == 80.0 and "XIU.TO" in fv["tickers"]
    assert "pas présentés comme conformes" in fv["statement"]
    assert tool_out(real_service, {"MSFT": 0.5, "JNJ": 0.5})["fund_verification"] is None


# ------------------------------------------------------------------ interface
def test_page_shows_source_decision_date_link_scope_and_funds_for_preset_b():
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.selectbox(key="preset_A").set_value("mateo_actions_canadiennes").run()
    text = " ".join(m.value for m in at.markdown)
    assert text.count(f"[Consulter la source officielle]({NBIM_URL})") >= 3                 # CNQ, TD et le périmètre de recherche
    assert "**Source :** NBIM (Banque de Norvège) — liste d'exclusion et d'observation des entreprises · **Type de décision :** Exclusion · **Date de la décision :** 13 mai 2020" in text
    assert "**Type de décision :** Mise sous observation · **Date de la décision :** 11 juin 2025" in text
    assert "Titres cherchés et non trouvés : périmètre de la recherche" in text and "n'est pas une preuve de conformité ESG" in text
    assert "Aucune vérification complète des entreprises sous-jacentes" in text
    assert any("pas à une page dédiée à cette décision" in c.value for c in at.caption)
    assert {u.rstrip(".,;") for u in URL_RE.findall(text)} <= registered_urls()
    exp = [e for e in at.expander if e.label == "Détails techniques ESG (sources, dates, règles appliquées)"][0]
    inside = " ".join(m.value for m in exp.markdown)
    assert "Type de lien : `list_page` · statut : `verified` (vérifié le 2026-11-14)" in inside and "Méthode de consultation" in inside


def test_page_for_portfolio_a_shows_reference_a_verifier_for_the_unverified_fund_document():
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.selectbox(key="preset_A").set_value("mateo_croissance_equilibree").run()
    text = " ".join(m.value for m in at.markdown)
    assert "Aucune vérification complète des entreprises sous-jacentes" in text and "F4393" not in text


# ------------------------------------------------------------------ réponse de l'assistant
ESG_TOOL = "check_esg_preferences"


def test_assistant_references_come_from_the_tool_result_not_from_the_model_text(real_service):
    ctx = SessionContext(MATEO_B, "mateo")
    fake_url = "https://evil.example/fake-decision"
    model = StepModel([("tools", [ESG_TOOL]), ("text", f"CNQ.TO est exclue, voir {fake_url} et [source](https://nbim.invalid/x).")])
    ag = GuardianAgent(real_service, ctx, Tracer(), model_factory=lambda: model)
    tr = ag.ask("Mateo veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?")
    rec = next(r for r in tr.tool_records if r.tool == ESG_TOOL)
    refs = build_references_from_tool_result(rec.result)
    assert {f["ticker"] for f in refs["findings"]} == {"CNQ.TO", "TD.TO"}
    urls = {f["url"] for f in refs["findings"]} | {s["reference"]["url"] for s in refs["search_scope"]}
    assert urls == {NBIM_URL} and fake_url not in repr(refs) and "nbim.invalid" not in repr(refs)
    f = {x["ticker"]: x for x in refs["findings"]}
    assert f["CNQ.TO"]["decision_label"] == "Exclusion" and f["CNQ.TO"]["published_fr"] == "13 mai 2020" and f["CNQ.TO"]["kind"] == "documented"
    assert f["TD.TO"]["decision_label"] == "Mise sous observation" and f["TD.TO"]["kind"] == "complementary"


def test_assistant_reply_page_renders_clickable_references_after_the_text(monkeypatch):
    model = patch_model(monkeypatch, [("tools", [ESG_TOOL]), ("text", "Réponse du modèle sans aucun lien.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.selectbox(key="preset_A").set_value("mateo_actions_canadiennes").run()
    at.text_area(key="q_text").set_value("Mateo veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Références ESG utilisées dans cette réponse" in text and "pas par le modèle" in text
    assert "décision : Exclusion · date de la décision : 13 mai 2020" in text and "décision : Mise sous observation · date de la décision : 11 juin 2025" in text
    assert f"[Consulter la source officielle]({NBIM_URL})" in text
    assert "Cherchés et non trouvés dans NBIM" in text
    assert model is not None


def test_no_references_block_when_the_esg_tool_was_not_used(monkeypatch):
    patch_model(monkeypatch, [("tools", ["evaluate_portfolio"]), ("text", "Réponse financière.")])
    at = run_app()
    at.selectbox(key="profile_id").set_value("mateo").run()
    at.text_area(key="q_text").set_value("Quelle est la volatilité de mon portefeuille ?")
    [b for b in at.button if "Poser la question" in b.label][0].click()
    at.run()
    assert "Références ESG utilisées dans cette réponse" not in " ".join(m.value for m in at.markdown)


def test_references_are_none_when_tool_failed_or_profile_not_concerned(real_service):
    assert build_references_from_tool_result({"status": "error"}) is None
    assert build_references_from_tool_result({"status": "ok", "applicable": False}) is None
    ctx = SessionContext(MATEO_B, "robert")
    out = {t.tool_spec["name"]: t for t in build_tools(real_service, ctx, Tracer())}[ESG_TOOL]()
    assert build_references_from_tool_result(out) is None
