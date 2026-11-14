"""Présentation en français simple de la cohérence ESG. Ne contient aucune donnée : tout vient de `EsgReport` (module déterministe)."""
from __future__ import annotations

import datetime as dt

from guardian.esg.engine import (category_label, COMPLEMENTARY, DOCUMENTED, INSUFFICIENT, NONE_FOUND, NOT_APPLICABLE, PROFILE_NOT_CONCERNED, STATE_LABELS, EsgReport)
from guardian.esg.references import build_reference
from guardian.explain.format import fr_date, pct, pct_value

STATE_ICONS = {DOCUMENTED: ("🟠", "orange"), COMPLEMENTARY: ("🟡", "orange"), NONE_FOUND: ("🔵", "blue"), INSUFFICIENT: ("⚪", "gray"),
               NOT_APPLICABLE: ("⚪", "gray")}
DIMENSIONS = {"E": "environnementale", "S": "sociale", "G": "de gouvernance"}
DECISION_NAMES = {"exclusion": "Exclusion", "observation": "Mise sous observation"}
DECISIONS_FR = {"exclusion": "a exclu {company} de son fonds", "observation": "a placé {company} sous observation"}

INTRO = {
    INSUFFICIENT: ("Nous pouvons analyser les risques financiers de votre portefeuille. Toutefois, les données disponibles ne permettent pas encore "
                   "de vérifier l'ensemble de vos préférences ESG."),
    DOCUMENTED: ("Au moins une entreprise de votre portefeuille figure dans une source consultée pour un critère directement lié à la préférence déclarée. "
                 "C'est une information à examiner, pas un verdict. Les autres lignes ne sont pas pour autant validées."),
    NONE_FOUND: ("Toutes les lignes évaluables ont été cherchées dans nos sources et n'y figurent pas. Cela ne prouve pas l'absence de controverse : "
                 "nos sources sont peu nombreuses."),
    NOT_APPLICABLE: "Le critère « entreprises liées à des controverses » ne s'applique à aucune ligne de ce portefeuille.",
}

DISTINCTIONS = (
    ("Une exclusion documentée liée à la préférence", "une source a exclu une entreprise du portefeuille pour un critère directement lié à la préférence déclarée (par exemple environnemental). À examiner, sans conclure à elle seule."),
    ("Une mise sous observation de gouvernance", "information complémentaire : une source suit une entreprise du portefeuille pour un critère de gouvernance ou de crime financier. Ce n'est ni une exclusion, ni un conflit environnemental ou social."),
    ("Une information manquante", "nous n'avons pas les données pour vérifier la ligne (par exemple un fonds dont la composition est inconnue). Ce n'est ni un conflit, ni une validation."),
    ("Une absence de controverse identifiée", "l'entreprise a été cherchée dans nos sources et n'y figure pas. Cela ne vaut pas preuve : nos sources ne couvrent pas tout."),
)

HOW_TO_VERIFY = (
    "Consulter la composition réelle de chaque FNB sur le site de son émetteur.",
    "Lire les méthodologies ESG publiées par les émetteurs de FNB (critères d'exclusion, fournisseur de données).",
    "Lire les rapports de durabilité et les documents d'information continue des entreprises, par exemple sur SEDAR+ (Canada) ou SEC EDGAR (États-Unis).",
    "Comparer avec d'autres sources de controverses reconnues, en vérifiant leurs conditions d'utilisation.",
)


def _controversy_text(rec: dict, source: dict, profile_name: str, company: str) -> dict:
    who = "la Banque de Norvège (NBIM)" if rec["source"] == "nbim_exclusion_list" else source["publisher"]
    decision = DECISIONS_FR[rec["decision"]]
    head = (f"{who[0].upper() + who[1:]} {decision.format(company=company)}, décision publiée le {fr_date(dt.date.fromisoformat(rec['published']))}. "
            f"Critère invoqué : {rec['criterion_fr'].lower()} ({rec['category'].lower()}).")
    if rec["relevance"] == "direct":
        link = f"Ce critère relève de la dimension {DIMENSIONS[rec['dimension']]}, visée par la préférence de {profile_name}."
    else:
        link = (f"Ce critère relève de la gouvernance : il ne correspond pas à la formulation stricte de la préférence de {profile_name} "
                "(controverses environnementales ou sociales), mais peut compter pour son intérêt général pour l'ESG.")
    caution = ("Ce n'est ni un jugement de culpabilité ni une note ESG : c'est la décision d'un investisseur selon ses propres lignes directrices."
               + (" Une mise sous observation est moins forte qu'une exclusion." if rec["decision"] == "observation" else ""))
    return {"headline": head, "link": link, "caution": caution, "source_id": rec["source"], "source_url": source["url"],
            "reference": {**build_reference(source, rec), "decision_label": DECISION_NAMES[rec["decision"]],
                          "published_fr": fr_date(dt.date.fromisoformat(rec["published"]))},
            "category_label": category_label(rec), "kind": "documented" if rec["relevance"] == "direct" else "complementary",
            "decision": rec["decision"], "dimension": rec["dimension"], "published": rec["published"]}


def build_esg_view(report: EsgReport, universe) -> dict:
    if not report.applicable:
        return {"applicable": False, "message": PROFILE_NOT_CONCERNED}
    name = report.profile_name
    src = {s["id"]: s for s in report.sources}
    w = report.weights_by_state
    total = sum(w.values())
    rows = []
    for a in report.lines:
        rows.append({"Actif": a.name if len(a.name) <= 28 else a.ticker, "Symbole": a.ticker, "Part": pct(a.weight, 0 if abs(a.weight * 100 - round(a.weight * 100)) < 0.05 else 1),
                     "Type": a.line_type, "Constat": a.state_label, "Pourquoi": a.reason + (f" Information du fonds (déclarée par l'émetteur) : {a.fund_note}" if a.fund_note else "")})
    cards = []
    for a in report.lines:
        for rec in a.records:
            company = a.name if len(a.name) <= 28 else rec["company_name_in_source"]
            cards.append({"ticker": a.ticker, "weight": a.weight, **_controversy_text(rec, src[rec["source"]], name, company)})
    checked = report.coverage_checked
    unknown = w.get(INSUFFICIENT, 0.0)
    na = w.get(NOT_APPLICABLE, 0.0)
    coverage = [
        {"label": "Cherché dans nos sources", "value": checked, "help": "Part du portefeuille dont les entreprises ont été cherchées dans au moins une source consultée."},
        {"label": "Non évaluable faute de données", "value": unknown, "help": "Part du portefeuille que nous ne pouvons pas vérifier. Elle n'est pas présentée comme conforme."},
        {"label": "Sans objet pour ce critère", "value": na, "help": "Part du portefeuille sans entreprise émettrice (par exemple l'or ou une cryptomonnaie)."},
    ]
    summary = (f"{pct_value(100 * checked)} de votre portefeuille a pu être cherché dans nos sources ; "
               f"{pct_value(100 * unknown)} ne peut pas être évalué faute de données"
               + (f" et {pct_value(100 * na)} est sans objet pour ce critère" if na > 1e-12 else "")
               + ". Ces parts ne sont pas présentées comme conformes.")
    cat_lines = []
    for c in report.categories:
        kind = ("à examiner : critère directement lié à la préférence déclarée" if c["relevance"] == "direct"
                else "information complémentaire, hors critère déclaré (ce n'est pas un conflit environnemental ou social)")
        cat_lines.append(f"{c['label']} : {pct_value(100 * c['weight'])} du portefeuille ({', '.join(c['tickers'])}) — {kind}.")
    if cat_lines:
        summary += " Catégories documentées, présentées séparément et jamais additionnées : " + " ".join(cat_lines)
    etf = report.underlying
    line_vs_underlying = {
        "line": (f"Exposition par ligne : {pct_value(etf['direct_company_weight_pct'])} du portefeuille est investi directement dans des actions d'entreprises, "
                 f"vérifiables une à une ; {pct_value(etf['etf_weight_pct'])} est détenu via des FNB."),
        "underlying": etf["explanation"],
    }
    has_comp = w.get(COMPLEMENTARY, 0.0) > 1e-12
    state_label = report.overall_label
    intro = INTRO[report.overall_state]
    if has_comp and report.overall_state != DOCUMENTED:
        state_label = f"{state_label} pour le critère déclaré ; information complémentaire documentée"
        intro += (" Une information complémentaire (hors critère déclaré, par exemple de gouvernance) est toutefois documentée : "
                  "elle est présentée à part et n'est pas un conflit environnemental ou social.")
    elif has_comp:
        intro += " Une information complémentaire (hors critère déclaré) est présentée séparément."
    scope = [{**sc, "reference": {**sc["reference"]}} for sc in report.search_scope()]
    return {
        "search_scope": scope, "fund_verification": report.fund_verification(),
        "applicable": True, "state": report.overall_state, "state_label": state_label, "state_icon": STATE_ICONS[report.overall_state],
        "intro": intro, "preferences": list(report.preferences), "coverage": coverage, "coverage_summary": summary,
        "rows": rows, "controversies": [c for c in cards if c["kind"] == "documented"],
        "complementary": [c for c in cards if c["kind"] == "complementary"],
        "categories": [{"id": c["id"], "label": c["label"], "decision": c["decision"], "dimension": c["dimension"], "relevance": c["relevance"],
                        "weight": c["weight"], "tickers": list(c["tickers"])} for c in report.categories], "distinctions": DISTINCTIONS, "line_vs_underlying": line_vs_underlying,
        "how_to_verify": HOW_TO_VERIFY, "no_score_notice": "Aucun score ESG n'est calculé, et le risque financier et l'ESG ne sont jamais combinés en une note unique.",
        "sources": report.sources, "uncertainties": report.uncertainties, "rules_applied": report.rules_applied, "data_version": report.data_version,
    }


def build_references_from_tool_result(result: dict) -> dict | None:
    """Références ESG d'une réponse de l'assistant, construites UNIQUEMENT depuis le résultat structuré de `check_esg_preferences` (jamais depuis le texte du modèle)."""
    if not isinstance(result, dict) or result.get("status") != "ok" or not result.get("applicable"):
        return None
    findings = []
    for cat in [*result.get("documented_categories", []), *result.get("complementary_information", [])]:
        for r in cat["records"]:
            ref = dict(r["reference"])
            ref.update({"category_label": cat["label"], "kind": "documented" if cat["relevance"] == "direct" else "complementary",
                        "decision_label": cat["decision_label"], "ticker": r["ticker"], "company": r["name"],
                        "published_fr": fr_date(dt.date.fromisoformat(r["published"])), "weight_pct": None})
            findings.append(ref)
    return {"findings": findings, "search_scope": result.get("search_scope", []), "fund_verification": result.get("fund_verification")}
