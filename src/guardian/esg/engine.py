"""Cohérence ESG d'un portefeuille avec les préférences ESG DÉCLARÉES d'un profil. Déterministe ; aucun score ; aucune controverse inventée.

États par ligne :
- DOCUMENTED     « Controverse documentée à examiner » : l'actif figure dans une source consultée (exclusion ou observation) ;
- NONE_FOUND     « Aucune controverse identifiée dans les sources consultées » : actif cherché dans au moins une source, non trouvé ;
- INSUFFICIENT   « Information insuffisante » : aucune vérification possible avec les données disponibles (FNB sans composition, etc.) ;
- NOT_APPLICABLE « Non applicable » : critère sans objet pour cet actif, avec justification écrite.

Une absence de résultat n'est JAMAIS convertie en « conforme ». La couverture est exprimée en poids du portefeuille.
Aucun score global ne combine risque financier et ESG.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guardian.esg.data import EsgData
from guardian.esg.references import build_reference

DOCUMENTED, NONE_FOUND, INSUFFICIENT, NOT_APPLICABLE = "DOCUMENTED", "NONE_FOUND", "INSUFFICIENT", "NOT_APPLICABLE"
COMPLEMENTARY = "COMPLEMENTARY"   # information documentée MAIS hors du critère déclaré (relevance == "indirect") : jamais un « conflit » avec la préférence
STATE_LABELS = {
    DOCUMENTED: "Controverse documentée à examiner",
    COMPLEMENTARY: "Information complémentaire documentée (hors critère déclaré)",
    NONE_FOUND: "Aucune controverse identifiée dans les sources consultées",
    INSUFFICIENT: "Information insuffisante",
    NOT_APPLICABLE: "Non applicable",
}
NOT_APPLICABLE_PROFILE = "NOT_APPLICABLE_PROFILE"
PROFILE_NOT_CONCERNED = "Ce profil n'a pas déclaré de préférences ESG : aucune vérification ESG n'est appliquée."
NO_SCORE_NOTICE = ("Aucun score ESG n'est calculé et aucun score global ne combine risque financier et ESG. "
                   "Un portefeuille peut avoir peu d'alertes financières tout en ayant une cohérence ESG inconnue.")
ABSENCE_NOTICE = ("L'absence de résultat n'est pas une preuve d'absence de controverse : « aucune controverse identifiée » signifie seulement "
                  "« non trouvée dans les sources consultées », qui sont peu nombreuses.")


DECISION_LABELS = {"exclusion": "Exclusion", "observation": "Mise sous observation"}
DIMENSION_LABELS = {"E": "environnementale", "S": "sociale", "G": "de gouvernance"}
RELEVANCE_LABELS = {"direct": "Directement liée à la préférence déclarée (controverses environnementales ou sociales)",
                    "indirect": "Hors de la formulation stricte de la préférence déclarée (information complémentaire)"}
DECISION_STRENGTH = {"exclusion": "Une exclusion est une décision plus forte qu'une mise sous observation.",
                     "observation": "Une mise sous observation est une décision moins forte qu'une exclusion : elle n'est pas une exclusion."}
WORDING_RULES = (
    "Ne jamais additionner l'exclusion environnementale et la mise sous observation de gouvernance en un seul pourcentage « en conflit avec les préférences ESG ».",
    "Toujours nommer séparément : la décision de la source (exclusion ou observation), la dimension (environnementale, sociale ou de gouvernance) et le poids concerné.",
    "Une information de gouvernance (relevance « indirect ») n'est pas un conflit environnemental ou social : la présenter comme information complémentaire.",
    "Une mise sous observation n'est pas une exclusion. Aucune affirmation sans source et date de publication de la décision.",
)


def category_id(rec: dict) -> str:
    return f"{rec['relevance']}_{rec['decision']}_{rec['dimension']}"


def category_label(rec: dict) -> str:
    return f"{DECISION_LABELS[rec['decision']]} {DIMENSION_LABELS[rec['dimension']]}"


@dataclass(frozen=True)
class AssetEsg:
    ticker: str
    name: str
    weight: float
    line_type: str                  # action individuelle | FNB | matière première | cryptoactif
    state: str
    reason: str                     # pourquoi cet état (français simple)
    records: tuple = ()             # constats documentés (dicts)
    source_ids: tuple = ()
    fund_note: str | None = None    # information de niveau fonds (FNB), jamais une vérification des positions

    @property
    def state_label(self) -> str:
        return STATE_LABELS[self.state]


@dataclass(frozen=True)
class EsgReport:
    applicable: bool
    profile_id: str
    profile_name: str
    preferences: tuple              # préférences déclarées (formulations officielles)
    overall_state: str | None
    lines: tuple
    weights_by_state: dict          # fractions du portefeuille par état
    coverage_checked: float         # part du portefeuille effectivement cherchée dans au moins une source (DOCUMENTED + NONE_FOUND)
    coverage_of_applicable: float | None   # idem, rapportée aux seules lignes applicables
    underlying: dict
    sources: tuple
    uncertainties: tuple
    rules_applied: tuple
    data_version: str
    categories: tuple = ()          # catégories distinctes (décision × dimension × pertinence), chacune avec son poids propre
    summary: str = ""               # phrase déterministe qui nomme chaque catégorie séparément

    def search_scope(self) -> list:
        """Périmètre de la recherche, par source : titres cherchés et non trouvés. Une absence de correspondance n'est pas une preuve de conformité."""
        smap = {x["id"]: x for x in self.sources}
        by_src: dict = {}
        for a in self.lines:
            if a.state == NONE_FOUND:
                for sid in a.source_ids:
                    by_src.setdefault(sid, []).append(a)
        out = []
        for sid, lines in by_src.items():
            src = smap.get(sid, {"id": sid})
            out.append({"source_id": sid, "reference": build_reference(src), "consulted_on": src.get("consulted_on"), "scope": src.get("scope"),
                        "not_found": [{"ticker": a.ticker, "name": a.name, "weight_pct": round(100 * a.weight, 2)} for a in lines],
                        "weight_pct": round(100 * sum(a.weight for a in lines), 2),
                        "notice": ("Ces titres ont été cherchés dans cette source et n'y ont pas été trouvés. Une absence de correspondance n'est pas une preuve "
                                   "de conformité ESG : la source ne couvre pas toutes les controverses.")})
        return out

    def fund_verification(self) -> dict | None:
        """FNB non évaluables : aucune vérification complète des entreprises sous-jacentes n'a été effectuée."""
        funds = [a for a in self.lines if a.line_type == "FNB" and a.state == INSUFFICIENT]
        if not funds:
            return None
        return {"tickers": [a.ticker for a in funds], "weight_pct": round(100 * sum(a.weight for a in funds), 2),
                "statement": ("Aucune vérification complète des entreprises sous-jacentes de ces FNB n'a été effectuée : leur composition n'est pas disponible "
                              "dans nos données. Ils ne sont pas présentés comme conformes."),
                "fund_level_notes": [{"ticker": a.ticker, "note": a.fund_note, "reference": build_reference({x["id"]: x for x in self.sources}.get(a.source_ids[0]))}
                                     for a in funds if a.fund_note and a.source_ids]}

    @property
    def overall_label(self) -> str | None:
        return None if self.overall_state is None else STATE_LABELS[self.overall_state]

    def to_dict(self) -> dict:
        pct = lambda x: None if x is None else round(100 * x, 2)  # noqa: E731
        smap = {x["id"]: x for x in self.sources}
        return {
            "status": "ok", "applicable": self.applicable, "profile_id": self.profile_id, "profile_name": self.profile_name,
            "declared_esg_preferences": list(self.preferences),
            "overall_state": self.overall_state, "overall_label": self.overall_label,
            "coverage": {"checked_in_sources_pct": pct(self.coverage_checked), "checked_of_applicable_pct": pct(self.coverage_of_applicable),
                         "weights_by_state_pct": {STATE_LABELS[k]: pct(v) for k, v in self.weights_by_state.items()}},
            "documented_categories": [_category_dict(c, smap) for c in self.categories if c["relevance"] == "direct"],
            "complementary_information": [_category_dict(c, smap) for c in self.categories if c["relevance"] != "direct"],
            "categories_summary": self.summary,
            "wording_rules": list(WORDING_RULES),
            "lines": [{"ticker": a.ticker, "name": a.name, "weight_pct": pct(a.weight), "line_type": a.line_type, "state": a.state,
                       "state_label": a.state_label, "reason": a.reason,
                       "documented_records": [{**r, "reference": build_reference(smap.get(r["source"]), r), "decision_label": DECISION_LABELS[r["decision"]], "dimension_label": DIMENSION_LABELS[r["dimension"]],
                                               "relevance_label": RELEVANCE_LABELS[r["relevance"]], "category_id": category_id(r),
                                               "strength_note": DECISION_STRENGTH[r["decision"]]} for r in a.records],
                       "source_ids": list(a.source_ids), "fund_level_note": a.fund_note} for a in self.lines],
            "underlying_exposure": self.underlying,
            "search_scope": self.search_scope(), "fund_verification": self.fund_verification(),
            "sources": list(self.sources), "uncertainties": list(self.uncertainties), "rules_applied": list(self.rules_applied),
            "wording": ABSENCE_NOTICE, "no_score_notice": NO_SCORE_NOTICE,
            "provenance": {"esg_data_version": self.data_version,
                           "esg_sources": [{"id": s["id"], "consulted_on": s["consulted_on"], "url": s["url"], "url_status": s["url_status"]} for s in self.sources]},
        }


def _category_dict(c: dict, smap: dict) -> dict:
    recs = [{**r, "reference": build_reference(smap.get(r["source"]), r)} for r in c["records"]]
    return {"category_id": c["id"], "label": c["label"], "decision": c["decision"], "decision_label": DECISION_LABELS[c["decision"]],
            "dimension": c["dimension"], "dimension_label": DIMENSION_LABELS[c["dimension"]], "relevance": c["relevance"],
            "relevance_label": RELEVANCE_LABELS[c["relevance"]], "weight_pct": round(100 * c["weight"], 2), "tickers": list(c["tickers"]),
            "records": recs, "strength_note": DECISION_STRENGTH[c["decision"]]}


def _build_categories(lines) -> tuple:
    cats: dict = {}
    for a in lines:
        for r in a.records:
            cid = category_id(r)
            c = cats.setdefault(cid, {"id": cid, "label": category_label(r), "decision": r["decision"], "dimension": r["dimension"],
                                      "relevance": r["relevance"], "weight": 0.0, "tickers": [], "records": []})
            c["weight"] += a.weight
            c["tickers"].append(a.ticker)
            c["records"].append({"ticker": a.ticker, "name": a.name, "source": r["source"], "criterion_fr": r["criterion_fr"], "published": r["published"],
                                 "decision": r["decision"], "company_name_in_source": r["company_name_in_source"],
                                 "decision_url": r.get("decision_url"), "decision_url_verified_on": r.get("decision_url_verified_on")})
    order = sorted(cats.values(), key=lambda c: (c["relevance"] != "direct", c["decision"] != "exclusion", c["id"]))
    return tuple(order)


def _summary(cats: tuple) -> str:
    if not cats:
        return "Aucune information documentée dans les sources consultées pour les lignes de ce portefeuille."
    parts = []
    for c in cats:
        pct_txt = f"{100 * c['weight']:.0f} %" if abs(100 * c["weight"] - round(100 * c["weight"])) < 0.05 else f"{100 * c['weight']:.1f} %".replace(".", ",")
        kind = "à examiner (directement liée à la préférence déclarée)" if c["relevance"] == "direct" else "information complémentaire, hors critère déclaré"
        parts.append(f"{c['label'].lower()} : {pct_txt} du portefeuille ({', '.join(c['tickers'])}), {kind}")
    return "; ".join(parts) + ". Ces catégories ne sont pas additionnées."


RULES_APPLIED = (
    "Une entreprise qui figure dans une source consultée avec un critère directement lié à la préférence déclarée (relevance « direct », ex. exclusion environnementale) est « controverse documentée à examiner ».",
    "Une entreprise documentée avec un critère hors de la formulation de la préférence (relevance « indirect », ex. observation de gouvernance) est « information complémentaire » : elle n'est pas comptée comme un conflit avec la préférence.",
    "Exclusion et observation sont deux décisions différentes ; environnement/social et gouvernance sont deux dimensions différentes ; chaque catégorie a son propre poids, sans addition.",
    "Une entreprise cherchée dans au moins une source et non trouvée est « aucune controverse identifiée dans les sources consultées » (jamais « conforme »).",
    "Un actif qui n'a pas pu être cherché (par exemple un FNB dont la composition n'est pas disponible) est « information insuffisante ».",
    "Un actif sans entreprise émettrice est « non applicable » seulement si une justification écrite existe.",
    "L'état global est « controverse documentée » dès qu'une ligne l'est (information complémentaire exclue) ; sinon « information insuffisante » dès qu'une ligne applicable ne peut pas être vérifiée ; "
    "« aucune controverse identifiée » seulement si toutes les lignes applicables ont été cherchées.",
)


def _line_type(asset_class: str) -> str:
    return {"equity": "action individuelle", "crypto": "cryptoactif", "etf_commodity": "matière première (fonds)"}.get(asset_class, "FNB")


def _source_entry(esg: EsgData, sid: str) -> dict:
    s = esg.sources[sid]
    return {"id": sid, "publisher": s["publisher"], "title": s["title"], "url": s["url"], "consulted_on": str(s["consulted_on"]),
            "short_name": s.get("short_name") or s["title"], "url_kind": s.get("url_kind", "list_page"), "url_status": s.get("url_status", "to_verify"),
            "url_verified_on": str(s["url_verified_on"]) if s.get("url_verified_on") else None,
            "nature": " ".join(str(s["nature"]).split()), "scope": " ".join(str(s["scope"]).split()),
            "retrieval_method": " ".join(str(s.get("retrieval_method", "")).split()), "limits": list(s["limits"]),
            "terms": " ".join(str(s["terms"]).split())}


def evaluate_esg(weights: dict, universe, profile_id: str, profile: dict, esg: EsgData) -> EsgReport:
    """`weights` : fractions (déjà validées). `universe` : DataFrame indexé par ticker. `profile` : dict du profil."""
    prefs = (profile.get("esg_preferences") or {})
    pid, pname = profile_id, profile["display_name"]
    if not prefs:
        return EsgReport(applicable=False, profile_id=pid, profile_name=pname, preferences=(), overall_state=None, lines=(), weights_by_state={},
                         coverage_checked=0.0, coverage_of_applicable=None, underlying={}, sources=(), uncertainties=(PROFILE_NOT_CONCERNED,),
                         rules_applied=(), data_version=esg.version)
    preferences = tuple([prefs["importance"]] + [c["official_wording"] for c in prefs.get("criteria", [])])
    lines, used_sources = [], []
    for t, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        row = universe.loc[t]
        name, lt = str(row["name"]), _line_type(str(row["asset_class"]))
        recs = esg.records_for(t)
        if t in esg.not_applicable:
            lines.append(AssetEsg(t, name, w, lt, NOT_APPLICABLE, esg.not_applicable[t]))
        elif recs:
            sids = tuple(sorted({r["source"] for r in recs}))
            used_sources += list(sids)
            if any(r["relevance"] == "direct" for r in recs):
                lines.append(AssetEsg(t, name, w, lt, DOCUMENTED,
                                      "Cette entreprise figure dans une source consultée avec un critère directement lié à la préférence déclarée (voir le détail). "
                                      "C'est une décision de la source, pas une conclusion du prototype.", tuple(recs), sids))
            else:
                lines.append(AssetEsg(t, name, w, lt, COMPLEMENTARY,
                                      "Cette entreprise figure dans une source consultée, mais pour un critère hors de la formulation de la préférence déclarée "
                                      "(par exemple la gouvernance). C'est une information complémentaire, pas un conflit avec la préférence ; "
                                      "c'est une décision de la source, pas une conclusion du prototype.", tuple(recs), sids))
        elif t in esg.checked:
            sids = tuple(sorted(set(esg.checked[t])))
            used_sources += list(sids)
            lines.append(AssetEsg(t, name, w, lt, NONE_FOUND,
                                  "Cherchée dans les sources consultées et non trouvée. Cela ne prouve pas l'absence de controverse.", (), sids))
        else:
            fl = esg.fund_level.get(t)
            if fl:
                used_sources.append(fl["source"])
            why = ("Fonds dont la composition n'est pas disponible dans nos données : impossible de vérifier les entreprises qu'il détient."
                   if lt == "FNB" else "Aucune donnée ESG disponible pour cet actif.")
            lines.append(AssetEsg(t, name, w, lt, INSUFFICIENT, why, (), (fl["source"],) if fl else (), " ".join(fl["statement"].split()) if fl else None))

    by_state = {s: 0.0 for s in (DOCUMENTED, COMPLEMENTARY, NONE_FOUND, INSUFFICIENT, NOT_APPLICABLE)}
    for a in lines:
        by_state[a.state] += a.weight
    total = sum(by_state.values())
    checked = by_state[DOCUMENTED] + by_state[COMPLEMENTARY] + by_state[NONE_FOUND]
    categories = _build_categories(lines)
    applicable_w = total - by_state[NOT_APPLICABLE]
    coverage_of_app = (checked / applicable_w) if applicable_w > 1e-12 else None

    if by_state[DOCUMENTED] > 0:
        overall = DOCUMENTED
    elif by_state[INSUFFICIENT] > 1e-12:
        overall = INSUFFICIENT
    elif by_state[NONE_FOUND] > 0 or by_state[COMPLEMENTARY] > 0:
        overall = NONE_FOUND   # aucune controverse liée au critère déclaré ; l'information complémentaire est présentée à part
    else:
        overall = NOT_APPLICABLE

    etf_lines = [a for a in lines if a.line_type == "FNB"]
    underlying = {
        "status": "composition_non_disponible" if etf_lines else "aucun_fnb",
        "explanation": ("Les FNB détiennent plusieurs entreprises. Leur composition n'est pas dans les données : l'exposition aux entreprises sous-jacentes "
                        "n'est donc pas connue et n'est pas estimée. Seule l'exposition par ligne (ce que vous détenez directement) est vérifiable."
                        if etf_lines else "Aucun FNB dans ce portefeuille : l'exposition par ligne correspond aux entreprises détenues directement."),
        "etf_weight_pct": round(100 * sum(a.weight for a in etf_lines), 2),
        "etf_lines": [{"ticker": a.ticker, "name": a.name, "weight_pct": round(100 * a.weight, 2),
                       "fund_level_note": a.fund_note} for a in etf_lines],
        "direct_company_weight_pct": round(100 * sum(a.weight for a in lines if a.line_type == "action individuelle"), 2),
    }
    sids = sorted(set(used_sources))
    uncertainties = [
        ABSENCE_NOTICE,
        ((f"Seule 1 source a été utilisée pour ce portefeuille ({sids[0]}) ; elle ne couvre pas toutes les controverses possibles."
          if len(sids) == 1 else
          f"{len(sids)} sources ont été utilisées pour ce portefeuille ({', '.join(sids)}) ; elles ne couvrent pas toutes les controverses possibles.")
         if sids else "Aucune source n'a été utilisée pour ce portefeuille : aucune donnée ESG n'est disponible pour ces actifs."),
        "Les controverses environnementales et sociales évoluent : les données sont un état à la date de consultation.",
    ]
    if by_state[INSUFFICIENT] > 1e-12:
        uncertainties.append(f"{100 * by_state[INSUFFICIENT]:.0f} % du portefeuille ne peut pas être évalué faute de données : il n'est pas présenté comme conforme.")
    if etf_lines:
        uncertainties.append("La composition des FNB n'est pas disponible : leur exposition économique sous-jacente est inconnue.")
    return EsgReport(
        applicable=True, profile_id=pid, profile_name=pname, preferences=preferences, overall_state=overall, lines=tuple(lines),
        weights_by_state=by_state, coverage_checked=checked, coverage_of_applicable=coverage_of_app, underlying=underlying,
        sources=tuple(_source_entry(esg, s) for s in sids), uncertainties=tuple(uncertainties), rules_applied=RULES_APPLIED, data_version=esg.version,
        categories=categories, summary=_summary(categories))
