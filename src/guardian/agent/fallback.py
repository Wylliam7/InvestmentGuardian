"""Réponse de repli DÉTERMINISTE : faits issus des sorties d'outils de la requête, sans texte du modèle.

Affichée à la place d'un texte IA dont une affirmation essentielle n'a pas pu être vérifiée (voir claims.py). Aucune interprétation, aucun conseil.
"""
from __future__ import annotations

from guardian.explain.format import fr, pct_value

FALLBACK_INTRO = ("**Faits vérifiés, issus directement des calculs Python.** Le texte généré par l'IA n'est pas affiché parce qu'au moins une de ses affirmations "
                  "essentielles n'a pas pu être confirmée par les outils. Voici ce que les outils ont réellement retourné.")


def _last(records: list, tool: str) -> dict | None:
    for r in reversed(records):
        if r.tool == tool and r.status == "ok" and isinstance(r.result, dict):
            return r.result
    return None


def _financial_lines(res: dict, label: str = "") -> list:
    out = []
    m, c, w = res.get("metrics") or {}, res.get("concentration") or {}, res.get("window") or {}
    head = f"**Portefeuille {label}** " if label else ""
    if m:
        out.append(f"- {head}période du {w.get('start')} au {w.get('end')} (CAD) : rendement annualisé {fr(m['annualized_return_pct'])} %, "
                   f"volatilité annualisée {fr(m['annualized_volatility_pct'])} %, plus forte baisse historique {fr(m['max_drawdown_pct'])} % "
                   f"(du {m.get('max_drawdown_peak_date')} au {m.get('max_drawdown_trough_date')}). Rendements passés : ils ne prédisent pas l'avenir.")
    kf = res.get("key_facts") or {}
    top = kf.get("top_positions") or []
    if top:
        listing = ", ".join(f"{p['ticker']} {pct_value(p['weight_pct'])} ({p['line_type']})" for p in top)
        out.append(f"- {head}trois plus grandes positions : {listing} ; total : {pct_value(kf['top3_total_pct'])} du portefeuille.")
        if kf.get("top3_ties"):
            out.append(f"- {head}{kf['top3_ties']}")
    if c:
        out.append(f"- {head}plus grande position : {c['largest_position']} ({pct_value(c['largest_position_weight_pct'])})"
                   + ("" if top else f" ; trois plus grandes : {pct_value(c['top3_weight_pct'])}")
                   + f" ; nombre effectif de positions : {fr(c['effective_number_of_positions'], 2)} "
                   "(concentration des poids entre les lignes, pas nombre d'entreprises sous-jacentes).")
        out.append(f"- {head}Ce que cela signifie : plus les premières lignes pèsent lourd, plus le résultat dépend de peu d'investissements. "
                   "Ces mesures portent sur les lignes du portefeuille ; elles ne disent pas, à elles seules, si un niveau de concentration convient au profil "
                   "(voir les repères du Guardian Check).")
    prof = kf.get("profil_actif")
    if prof:
        r1 = prof["repères_concentration_plus_grande_position"]
        out.append(f"- {head}repères du prototype pour {prof['persona']} (risque {str(prof['niveau_de_risque']).lower()}, horizon {prof['horizon']}) : "
                   f"plus grande position, attention {r1['attention']}, conflit {r1['conflit']}.")
    fx = res.get("fund_exposure")
    if fx and fx.get("has_funds"):
        out.append(f"- {head}{fx['pedagogical_note']}")
    return out


def build_fallback(records: list, question: str | None = None) -> str | None:
    ck = _last(records, "check_profile_constraints")
    ev = _last(records, "evaluate_portfolio")
    cmp_ = _last(records, "compare_scenarios")
    esg = _last(records, "check_esg_preferences")
    if not any((ck, ev, cmp_, esg)):
        return None
    lines = [FALLBACK_INTRO, ""]
    cited = cited_assets(question, records)
    if cited:
        lines += ["**Actifs cités dans votre question (expositions actuelles, aucun scénario calculé)**", *[f"- {x}" for x in cited], ""]
    base = ck or ev
    prof = (ck or {}).get("profile") or (esg or {}).get("profile") or (cmp_ or {}).get("profile")
    if prof:
        lines += ["**Profil officiel (cas AlphaForge AI 2026)**",
                  f"- {prof['display_name']} : {prof.get('age')} ans, {prof.get('occupation')}, risque {str(prof.get('risk_profile_label', '')).lower()}, "
                  f"horizon {prof.get('horizon_years_min')} à {prof.get('horizon_years_max')} ans." if prof.get("horizon_years_max") else
                  f"- {prof['display_name']} : {prof.get('age')} ans, {prof.get('occupation')}, risque {str(prof.get('risk_profile_label', '')).lower()}, "
                  f"horizon {prof.get('horizon_years_min')} ans ou plus.",
                  f"- Objectif : {prof.get('objective')}", ""]
    if base:
        lines += ["**Faits financiers (calculés par Python, historiques)**", *_financial_lines(base), ""]
    if ck:
        lines.append("**Guardian Check (seuils heuristiques du prototype, pas des normes)**")
        for f in ck.get("findings", []):
            if f.get("status") == "INFO":
                continue
            d = f.get("display") or {}
            lines.append(f"- {f['title']} : {f['status_label']} (mesuré {d.get('measured')}, attention {d.get('attention')}, conflit {d.get('conflict')}).")
        r10 = next((f for f in ck.get("findings", []) if f.get("rule_id") == "R10"), None)
        ev10 = (r10 or {}).get("evidence") or {}
        if ev10.get("tech_share_pct") is not None:
            lines.append(f"- Part des positions étiquetées technologie ou communication : {pct_value(ev10['tech_share_pct'])} ({', '.join(ev10.get('tech_positions', [])) or 'aucune'})"
                         + (f", plus {pct_value(ev10['qqq_weight_pct'])} dans QQQ, fonds fortement technologique non décomposé" if ev10.get("qqq_weight_pct") else "")
                         + ". Mesure PARTIELLE : l'exposition technologique des autres FNB n'est pas mesurée ; aucun seuil n'est appliqué à cette part.")
        lines.append("")
    if cmp_:
        lines.append("**Comparaison A/B (mêmes données et même période)**")
        for key, name in (("portfolio_A", "A"), ("portfolio_B", "B")):
            lines += _financial_lines(cmp_.get(key) or {}, name)
        lines += [f"- {t}" for t in cmp_.get("historical_tradeoffs", [])]
        lines += [f"- {cmp_.get('no_winner_notice', '')}", ""]
    if esg and esg.get("applicable"):
        lines.append("**Préférences ESG (module distinct, aucun score, aucun seuil)**")
        lines.append(f"- État global : {esg['overall_label']}.")
        cov = esg["coverage"]
        if cov.get("checked_in_sources_pct") is not None:
            lines.append(f"- Part du portefeuille cherchée dans les sources consultées (couverture) : {pct_value(cov['checked_in_sources_pct'])}.")
        lines.append("- Répartition par état : " + " ; ".join(f"{k} {pct_value(v)}" for k, v in cov["weights_by_state_pct"].items() if v) + ".")
        if esg.get("categories_summary"):
            lines.append(f"- Catégories documentées : {esg['categories_summary']}")
        for sc in esg.get("search_scope", []):
            lines.append(f"- Cherchés et non trouvés ({', '.join(x['ticker'] for x in sc['not_found'])}) dans {sc['reference']['source_name']} : {sc['notice']}")
        if esg.get("fund_verification"):
            lines.append(f"- {esg['fund_verification']['statement']}")
        lines.append(f"- {esg['no_score_notice']}")
        if esg.get("data_nature"):
            lines.append(f"- {esg['data_nature']}")
        lines.append("")
    gl = (ck or {}).get("general_limitations") or []
    if gl:
        lines += ["**Limites générales**", *[f"- {x}" for x in gl[:4]]]
    return "\n".join(lines).strip()


# ----------------------------------------------------------------------------- section « Faits et contrôles vérifiés » (V3.3)
TOOL_LABELS = {"get_profile": "profil officiel", "evaluate_portfolio": "métriques du portefeuille", "check_profile_constraints": "Guardian Check",
               "compare_scenarios": "comparaison A/B", "check_esg_preferences": "préférences ESG"}


def _profile_line(prof: dict) -> str:
    hz = (f"{prof.get('horizon_years_min')} à {prof.get('horizon_years_max')} ans" if prof.get("horizon_years_max")
          else f"{prof.get('horizon_years_min')} ans ou plus")
    return f"{prof['display_name']}, {prof.get('age')} ans · risque {str(prof.get('risk_profile_label', '')).lower()} · horizon {hz}"


def _metrics_lines(res: dict) -> list:
    """Mêmes libellés que la section historique « Faits historiques utilisés » (V2)."""
    m, c, w = res.get("metrics") or {}, res.get("concentration") or {}, res.get("window") or {}
    if not m:
        return []
    out = [f"Période : du {w.get('start')} au {w.get('end')} · devise : dollar canadien (CAD)",
           f"Rendement historique cumulé : {fr(m['cumulative_return_pct'])} %",
           f"Fluctuations annualisées : {fr(m['annualized_volatility_pct'])} %",
           f"Plus forte baisse historique : {fr(m['max_drawdown_pct'])} %"]
    if c:
        out.append(f"Plus grande position : {c['largest_position']} ({pct_value(c['largest_position_weight_pct'])}) · "
                   f"environ {fr(c['effective_number_of_positions'])} positions de poids égal (lignes, pas entreprises)")
    kf = res.get("key_facts") or {}
    if kf.get("top_positions"):
        out.append("Trois plus grandes positions : " + ", ".join(f"{p['ticker']} {pct_value(p['weight_pct'])}" for p in kf["top_positions"])
                   + f" · total {pct_value(kf['top3_total_pct'])}" + (" (égalité de poids : choix des dernières positions arbitraire)" if kf.get("top3_ties") else ""))
    return out


def _findings_lines(findings: list) -> list:
    out = []
    for f in findings:
        if f.get("status") == "INFO":
            continue
        d = f.get("display") or {}
        out.append(f"{f['rule_id']} · {f['title']} : **{f['status_label']}** (mesuré {str(d.get('measured', '')).replace('.', ',')} ; "
                   f"repères : attention {d.get('attention')}, conflit {d.get('conflict')})")
    return out


def verified_facts(records: list, question: str | None = None) -> list:
    """Sections (titre, lignes) construites UNIQUEMENT à partir des résultats des outils réussis de la requête. Aucun statut n'est déduit ni fabriqué."""
    ok = [r for r in sorted(records, key=lambda r: getattr(r, "id", 0)) if r.status == "ok" and isinstance(r.result, dict)]
    if not ok:
        return []
    by = {}
    for r in ok:
        by.setdefault(r.tool, r.result)                      # premier résultat de chaque outil dans la requête
    secs = []
    ran = ", ".join(f"{r.tool} ({TOOL_LABELS.get(r.tool, r.tool)})" for r in ok)
    failed = [r.tool for r in records if r.status != "ok"]
    secs.append(("Outils exécutés pendant cette requête", [ran] + ([f"En échec : {', '.join(failed)} (aucun résultat utilisé)"] if failed else [])))
    prof = next((by[t].get("profile") for t in ("check_profile_constraints", "get_profile", "compare_scenarios", "check_esg_preferences") if t in by and by[t].get("profile")), None)
    pa = (by.get("evaluate_portfolio") or {}).get("key_facts", {}).get("profil_actif")
    if prof:
        secs.append(("Profil officiel", [_profile_line(prof)]))
    elif pa:
        secs.append(("Profil officiel", [f"{pa['persona']}, {pa['âge']} ans · risque {str(pa['niveau_de_risque']).lower()} · horizon {pa['horizon']}"]))
    if "compare_scenarios" in by:
        c = by["compare_scenarios"]
        for key in ("portfolio_A", "portfolio_B"):
            secs.append((f"Faits historiques utilisés (valeurs calculées par le moteur) — portefeuille {key[-1]}", _metrics_lines({**c[key], "window": c.get("window")})))
    else:
        base = by.get("evaluate_portfolio") or by.get("check_profile_constraints")
        if base:
            secs.append(("Faits historiques utilisés (valeurs calculées par le moteur)", _metrics_lines(base)))
    if "check_profile_constraints" in by:
        ck = by["check_profile_constraints"]
        secs.append((f"Statuts évalués par le Guardian Check (portefeuille {ck.get('portfolio', 'A')}, repères heuristiques du prototype)", _findings_lines(ck.get("findings") or [])))
    if "compare_scenarios" in by:
        c = by["compare_scenarios"]
        for pf in ("A", "B"):
            secs.append((f"Statuts évalués par le Guardian Check — portefeuille {pf}", _findings_lines((c.get(f"guardian_{pf}") or {}).get("findings") or [])))
    if pa and "check_profile_constraints" not in by and "compare_scenarios" not in by:
        r1, r7 = pa["repères_concentration_plus_grande_position"], pa["repères_nombre_effectif_de_positions"]
        secs.append(("Repères configurés pour ce profil (aucun statut évalué : le Guardian Check n'a pas été exécuté pendant cette requête)",
                     [f"Plus grande position : attention {r1['attention']}, conflit {r1['conflit']}",
                      f"Nombre effectif de positions : attention {r7['attention']}, conflit {r7['conflit']}"]))
    esg = by.get("check_esg_preferences")
    if esg and esg.get("applicable"):
        cov = esg["coverage"]
        lines = [f"État global : {esg['overall_label']} · couverture (part cherchée dans les sources) : {pct_value(cov['checked_in_sources_pct'])}"]
        if esg.get("categories_summary"):
            lines.append(f"Catégories documentées : {esg['categories_summary']}")
        kf = esg.get("key_facts") or {}
        ins = kf.get("non_évaluables") or []
        na = kf.get("sans_objet (non vérifiés, sans entreprise émettrice)") or []
        if ins or na:
            lines.append("Non vérifiés : " + "; ".join(x for x in (f"FNB sans composition ({', '.join(ins)})" if ins else "", f"sans objet ({', '.join(na)})" if na else "") if x))
        lines.append("Aucun seuil ni score ESG. Une absence de correspondance n'est pas une preuve de conformité.")
        secs.append(("Préférences ESG (module ESG)", lines))
    cited = cited_assets(question, records)
    if cited:
        secs.insert(2, ("Actifs cités dans la question (expositions actuelles, aucun scénario calculé)", cited))
    return [(t, l) for t, l in secs if l]


# ----------------------------------------------------------------------------- question conditionnelle (« si tel actif baissait… »)
import re as _re
import unicodedata as _ud

_COND = _re.compile(r"\b(?:si|et si)\b[^?]*\b(?:baiss|chut|recul|perd|effondr|plong|tomb|mont|hauss|grimp|remont|s'envol)|scenario|hypothe")
CLASS_FR = {"equity": "action individuelle", "etf_equity": "FNB d'actions", "etf_bond": "FNB d'obligations", "etf_commodity": "fonds adossé à l'or",
            "crypto": "cryptoactif"}
SCENARIO_LIMIT = ("Ce que l'on ne peut pas conclure : le prototype ne calcule ni scénario de baisse, ni probabilité, ni corrélation entre ces actifs, "
                  "ni perte future. Leurs plus fortes baisses historiques ne sont pas forcément survenues en même temps et ne bornent pas une baisse future.")


def _fold(s: str) -> str:
    return "".join(c for c in _ud.normalize("NFD", (s or "").lower()) if _ud.category(c) != "Mn").replace("’", "'")


def cited_assets(question: str | None, records: list) -> list:
    """Lignes « actifs cités dans une question conditionnelle » : poids et mesures historiques retournés par les outils ; aucun scénario."""
    q = _fold(question or "")
    if not q or not _COND.search(q):
        return []
    ok = [r for r in records if r.status == "ok" and isinstance(r.result, dict)]
    ev = next((r.result for r in ok if r.tool == "evaluate_portfolio"), None)
    base = ev or next((r.result for r in ok if r.tool == "check_profile_constraints"), None)
    if not base:
        return []
    assets = {a["ticker"]: a for a in (ev or {}).get("assets", [])}
    weights = base.get("weights_pct") or {}
    hits = []
    for t, w in weights.items():
        a = assets.get(t, {})
        codes = {_fold(t), _fold(_re.split(r"[-.]", t)[0])}                # code complet ou racine (TD.TO -> td, BTC-USD -> btc)
        name = _fold(a.get("name", ""))
        names = {name, name.split()[0]} if name else set()
        if any(len(n) >= 2 and _re.search(rf"(?<![a-z0-9]){_re.escape(n)}(?![a-z0-9])", q) for n in codes) or \
                any(len(n) >= 4 and _re.search(rf"(?<![a-z0-9]){_re.escape(n)}(?![a-z0-9])", q) for n in names):
            hits.append((t, w, a))
    if not hits:
        return []
    out = []
    for t, w, a in hits:
        extra = (f" · volatilité annualisée historique {fr(a['annualized_volatility_pct'])} % · plus forte baisse historique {fr(a['max_drawdown_pct'])} %"
                 if a else "")
        out.append(f"{t}{' (' + a['name'] + ', ' + CLASS_FR.get(a.get('asset_class'), a.get('asset_class', '')) + ')' if a else ''} : "
                   f"{pct_value(w)} du portefeuille{extra}")
    if len(hits) > 1:
        out.append(f"Poids combiné des actifs cités : {pct_value(sum(w for _, w, _ in hits))} du portefeuille (somme de leurs poids actuels, pas une perte).")
    out.append(SCENARIO_LIMIT)
    return out
