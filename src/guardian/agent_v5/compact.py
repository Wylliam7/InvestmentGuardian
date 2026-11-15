"""Présentation compacte des résultats d'outils transmis à Nova (expérience V5).

Appliquée APRÈS l'exécution réelle de l'outil choisi par Nova. Le résultat complet reste dans la trace (`ToolCall.result`) ;
seule la vue envoyée au modèle change (`ToolCall.model_view`).

Principes :
- sélection et réorganisation uniquement : chaque valeur vient du résultat d'origine (chaînes reprises telles quelles, nombres inchangés) ;
  seules exceptions, documentées et testées : les libellés de type de ligne (`LINE_TYPES`, déjà utilisés par les outils V3.3) et le
  nombre de lignes (comptage des poids) ;
- une seule représentation par valeur : par exemple le statut d'un critère n'apparaît qu'une fois, avec sa mesure affichée par le moteur ;
- rien n'est retiré parce qu'il serait « secondaire » pour une question : seuls disparaissent les doublons et les champs techniques
  (empreintes de fichiers, chemins, versions, drapeaux d'affichage, métadonnées de liens) ;
- les erreurs d'outils sont transmises sans modification.
"""
from __future__ import annotations

from guardian.agent.tools import LINE_TYPES

PROFILE_TECHNICAL = ("persona_test", "source", "show_sector_context")


def _profile(p: dict | None) -> dict | None:
    return None if p is None else {k: v for k, v in p.items() if k not in PROFILE_TECHNICAL}


def _window(w: dict | None) -> dict | None:
    if not w:
        return None
    return {k: w[k] for k in ("start", "end", "n_observations", "years") if k in w}


def _metrics(m: dict | None, drop: tuple = ()) -> dict | None:
    """Métriques du moteur, mêmes noms et mêmes valeurs ; `drop` retire celles déjà présentes ailleurs dans la vue."""
    if not m:
        return None
    return {k: v for k, v in m.items() if k not in drop}


def _types_from_classes(key_facts: dict | None) -> dict:
    """Type de chaque ligne d'après la répartition par classe du moteur (une ligne n'appartient qu'à une classe)."""
    out = {}
    for c in ((key_facts or {}).get("répartition_par_classe") or {}).get("classes", []):
        for t in c.get("titres", []):
            out[t] = c["classe"]
    return out


def _lines(weights: dict | None, assets: list | None, key_facts: dict | None) -> list:
    by_asset = {a["ticker"]: a for a in assets or []}
    types = _types_from_classes(key_facts)
    out = []
    for t, w in sorted((weights or {}).items(), key=lambda kv: (-kv[1], kv[0])):
        a = by_asset.get(t)
        line = {"ticker": t, "weight_pct": w}
        if a:
            line.update({"name": a.get("name"), "type": LINE_TYPES.get(a.get("asset_class"), a.get("asset_class")), "sector": a.get("sector"),
                         "annualized_volatility_pct": a.get("annualized_volatility_pct"), "cumulative_return_pct": a.get("cumulative_return_pct"),
                         "max_drawdown_pct": a.get("max_drawdown_pct")})
        elif t in types:
            line["classe"] = types[t]
        out.append(line)
    return out


def _funds(fx: dict | None) -> dict | None:
    if not fx or not fx.get("has_funds"):
        return None if not fx else {"has_funds": False}
    return {"fund_lines": [{k: x[k] for k in ("ticker", "name", "weight_pct") if k in x} for x in fx.get("fund_lines", [])],
            "fund_weight_pct": fx.get("fund_weight_pct"), "largest_position_is_fund": fx.get("largest_position_is_fund"),
            "underlying_diversification_measured": fx.get("underlying_diversification_measured"), "note": fx.get("pedagogical_note")}


def _key_facts_extra(kf: dict | None) -> dict:
    """Faits des `key_facts` V3.3 qui ne sont pas déjà ailleurs : égalités dans le top 3, part technologique, repères du profil actif."""
    out = {}
    if not kf:
        return out
    if kf.get("top3_ties"):
        out["top3_ties"] = kf["top3_ties"]
    if kf.get("technology"):
        out["technology"] = kf["technology"]
    if kf.get("profil_actif"):
        out["profil_actif"] = kf["profil_actif"]
    return out


def _criteria(findings: list | None, with_details: bool = True) -> list:
    """Un élément par critère : statut (libellé du moteur), mesure affichée, repères, et pour les détails la justification,
    la méthode, les limites et les éléments probants utiles. Le statut INFO (R10) est conservé."""
    out = []
    for f in findings or []:
        d = f.get("display") or {}
        item = {"rule_id": f["rule_id"], "title": f["title"], "status": f["status_label"], "measured": d.get("measured") or None,
                "attention": d.get("attention") or None, "conflict": d.get("conflict") or None}
        if with_details:
            item["phrase"] = d.get("phrase") or f.get("summary")
            item["justification"] = f.get("justification")
            item["limitations"] = list(f.get("limitations") or [])
            ev = dict(f.get("evidence") or {})
            ev.pop("weights_pct", None)                  # déjà dans les lignes
            ev.pop("factor", None)                       # facteur d'annualisation : technique
            if ev:
                item["evidence"] = ev
        out.append({k: v for k, v in item.items() if v not in (None, "", [])})
    return out


def _portfolio_block(res: dict, window: dict | None = None) -> dict:
    """Bloc portefeuille commun à evaluate_portfolio et aux portefeuilles A/B de compare_scenarios."""
    c = res.get("concentration") or {}
    return {k: v for k, v in {
        "window": _window(window or res.get("window")),
        "n_lines": len(res.get("weights_pct") or {}),
        "lines": _lines(res.get("weights_pct"), res.get("assets"), res.get("key_facts")),
        "metrics": _metrics(res.get("metrics")),
        "concentration": {k: c[k] for k in ("largest_position", "largest_position_weight_pct", "top3_weight_pct", "hhi", "effective_number_of_positions") if k in c},
        "asset_class_exposure_pct": res.get("asset_class_exposure_pct"),
        "currency_exposure_pct": res.get("currency_exposure_pct"),
        "funds": _funds(res.get("fund_exposure")),
        **_key_facts_extra(res.get("key_facts")),
    }.items() if v not in (None, {}, [])}


def _provenance(prov: dict | None) -> dict | None:
    if not prov:
        return None
    keep = ("price_field", "reference_currency", "calendar_policy", "fx_policy", "rebalancing", "assumptions", "limitations")
    return {k: prov[k] for k in keep if prov.get(k) not in (None, [], "")}


def compact_evaluate(res: dict) -> dict:
    return {"status": "ok", "portfolio": res.get("portfolio"), **_portfolio_block(res), "provenance": _provenance(res.get("provenance"))}


def compact_check(res: dict) -> dict:
    m = res.get("metrics") or {}
    c = res.get("concentration") or {}
    return {k: v for k, v in {
        "status": "ok", "profile_id": res.get("profile_id"), "profile_name": res.get("profile_name"), "portfolio": res.get("portfolio"),
        "window": _window(res.get("window")), "wording": res.get("wording"), "counts": res.get("counts"),
        "criteria": _criteria(res.get("findings")),
        # métriques non reprises par un critère (la volatilité, la plus forte baisse et ses dates sont dans R4 et R5)
        "other_metrics": {k: m[k] for k in ("cumulative_return_pct", "annualized_return_pct") if k in m},
        "concentration": {k: c[k] for k in ("largest_position_weight_pct", "top3_weight_pct", "effective_number_of_positions") if k in c},
        "n_lines": len(res.get("weights_pct") or {}),
        "lines": _lines(res.get("weights_pct"), None, res.get("key_facts")),
        "funds": _funds(res.get("fund_exposure")),
        **{k: v for k, v in _key_facts_extra(res.get("key_facts")).items() if k != "profil_actif"},
        "profile": _profile(res.get("profile")),
        "general_limitations": res.get("general_limitations"), "missing_information": res.get("missing_information"),
    }.items() if v not in (None, {}, [])}


def compact_compare(res: dict) -> dict:
    """Les repères sont identiques pour A et B (même profil) : ils ne sont donnés qu'une fois, avec la justification de chaque critère."""
    ga, gb = (res.get("guardian_A") or {}), (res.get("guardian_B") or {})
    refs = _criteria(ga.get("findings"))
    criteria_refs = [{k: x[k] for k in ("rule_id", "title", "attention", "conflict", "justification", "limitations") if k in x} for x in refs]
    status_only = lambda g: [{k: x[k] for k in ("rule_id", "status", "measured", "evidence") if k in x} for x in _criteria(g.get("findings"))]  # noqa: E731
    return {k: v for k, v in {
        "status": "ok", "profile_id": res.get("profile_id"), "profile_name": res.get("profile_name"),
        "window": _window(res.get("window")), "conventions": {k: v for k, v in (res.get("conventions") or {}).items() if k != "annualization_factor"},
        "portfolio_A": _portfolio_block(res.get("portfolio_A") or {}, res.get("window")),
        "portfolio_B": _portfolio_block(res.get("portfolio_B") or {}, res.get("window")),
        "guardian_A": {"counts": ga.get("counts"), "criteria": status_only(ga)},
        "guardian_B": {"counts": gb.get("counts"), "criteria": status_only(gb)},
        "criteria_references": criteria_refs,
        "differences_B_minus_A": res.get("differences_B_minus_A"), "historical_tradeoffs": res.get("historical_tradeoffs"),
        "no_winner_notice": res.get("no_winner_notice"), "profile": _profile(res.get("profile")),
        "provenance": _provenance(res.get("provenance")),
    }.items() if v not in (None, {}, [])}


def _esg_decisions(cats: list | None) -> list:
    out = []
    for c in cats or []:
        out.append({"label": c.get("label"), "decision": c.get("decision_label"), "dimension": c.get("dimension_label"),
                    "relevance": c.get("relevance_label"), "weight_pct": c.get("weight_pct"), "tickers": c.get("tickers"),
                    "records": [{"ticker": r["ticker"], "name": r.get("name"), "company_name_in_source": r.get("company_name_in_source"),
                                 "criterion": r.get("criterion_fr"), "published": r.get("published"),
                                 "source": (r.get("reference") or {}).get("source_name") or r.get("source")} for r in c.get("records") or []],
                    "strength_note": c.get("strength_note")})
    return out


def compact_esg(res: dict) -> dict:
    if not res.get("applicable"):
        return {k: v for k, v in {"status": "ok", "applicable": False, "profile_id": res.get("profile_id"), "profile_name": res.get("profile_name"),
                                  "uncertainties": res.get("uncertainties"), "wording": res.get("wording"),
                                  "no_score_notice": res.get("no_score_notice"),
                                  "no_threshold_notice": res.get("no_threshold_notice")}.items() if v not in (None, "", [])}
    reasons = {}
    lines = []
    for x in res.get("lines") or []:
        lines.append({k: v for k, v in {"ticker": x["ticker"], "name": x.get("name"), "weight_pct": x.get("weight_pct"), "line_type": x.get("line_type"),
                                        "state": x.get("state_label"), "fund_level_note": x.get("fund_level_note")}.items() if v is not None})
        if not x.get("documented_records"):
            reasons.setdefault(x.get("state_label"), x.get("reason"))   # la raison est la même pour toutes les lignes d'un même état
    ue = res.get("underlying_exposure") or {}
    fv = res.get("fund_verification") or {}
    return {k: v for k, v in {
        "status": "ok", "applicable": True, "profile_id": res.get("profile_id"), "profile_name": res.get("profile_name"), "portfolio": res.get("portfolio"),
        "declared_esg_preferences": res.get("declared_esg_preferences"), "overall_state": res.get("overall_label"),
        "coverage": res.get("coverage"),
        "documented_categories": _esg_decisions(res.get("documented_categories")),
        "complementary_information": _esg_decisions(res.get("complementary_information")),
        "categories_summary": res.get("categories_summary") or None,
        "lines": lines, "reasons_by_state": reasons,
        "underlying_exposure": {k: ue[k] for k in ("explanation", "etf_weight_pct", "direct_company_weight_pct") if k in ue} or None,
        "fund_verification": {k: fv[k] for k in ("tickers", "weight_pct", "statement") if k in fv} or None,
        "sources": [{k: s[k] for k in ("short_name", "publisher", "consulted_on", "url", "nature", "scope", "retrieval_method", "limits") if k in s}
                    for s in res.get("sources") or []],
        "uncertainties": res.get("uncertainties"), "rules_applied": res.get("rules_applied"), "wording_rules": res.get("wording_rules"),
        "wording": res.get("wording"), "no_score_notice": res.get("no_score_notice"), "no_threshold_notice": res.get("no_threshold_notice"),
        "data_nature": res.get("data_nature"),
    }.items() if v not in (None, {}, [])}


def compact_profile(res: dict) -> dict:
    return {"status": "ok", "profile_id": res.get("profile_id"), "is_active_profile": res.get("is_active_profile"),
            "profile": _profile(res.get("profile")), "heuristic_thresholds": res.get("heuristic_thresholds"),
            "thresholds_are_heuristics": res.get("thresholds_are_heuristics"), "available_profiles": res.get("available_profiles")}


COMPACTERS = {"evaluate_portfolio": compact_evaluate, "check_profile_constraints": compact_check, "compare_scenarios": compact_compare,
              "check_esg_preferences": compact_esg, "get_profile": compact_profile}


def compact(tool: str, result: dict) -> dict:
    """Vue transmise au modèle. Erreurs et résultats inattendus : transmis tels quels."""
    if not isinstance(result, dict) or result.get("status") != "ok" or tool not in COMPACTERS:
        return result
    return COMPACTERS[tool](result)
