"""Outils Strands exposés à l'agent (V1 : quatre outils financiers réels).

Les portefeuilles A/B et le profil actif viennent du contexte de session (côté serveur, mis à jour par l'interface) :
le modèle ne retranscrit jamais de poids. Chaque appel est enregistré dans le Tracer, succès ou échec.
Aucun décorateur ne masque la signature des outils (leçon de la phase 0).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from strands import tool

from guardian.agent.service import GuardianService
from guardian.agent.tracer import Tracer, digest, sanitize
from guardian.explain.funds import fund_exposure
from guardian.rules.engine import tech_share

ERROR_INSTRUCTION = ("L'outil a échoué. N'avance aucun chiffre ni conclusion financière ; "
                     "indique seulement que l'analyse n'a pas pu être réalisée et rapporte le message d'erreur.")


@dataclass
class SessionContext:
    weights: dict                      # portefeuille A : poids cibles (fractions)
    profile_id: str
    weights_b: dict | None = None      # portefeuille B (comparaison), s'il est défini
    fail_tools: set = field(default_factory=set)   # injection de pannes (tests uniquement)
    allowed_profiles: set | None = None            # profils utilisables pour la requête en cours (None = tous : appels directs/tests)

    def snapshot(self) -> dict:
        pct = lambda w: None if w is None else {t: round(100 * v, 4) for t, v in w.items()}  # noqa: E731
        return {"profile_id": self.profile_id, "weights_a_pct": pct(self.weights), "weights_b_pct": pct(self.weights_b)}


def _data_refs(result: dict) -> dict:
    prov = result.get("provenance") or {}
    files = prov.get("data_files") or {}
    refs = {"files_sha256_prefix": {n: f["sha256"][:12] for n, f in files.items()},
            "window": prov.get("window"), "price_field": prov.get("price_field"),
            "reference_currency": prov.get("reference_currency"),
            "rules_config_version": result.get("config_version") or result.get("rules_config_version")}
    if result.get("profile", {}).get("source"):
        refs["profile_source"] = result["profile"]["source"]
    if prov.get("esg_sources") is not None:
        refs["esg_sources"] = prov["esg_sources"]
        refs["esg_data_version"] = prov.get("esg_data_version")
    return refs


def _run(tracer: Tracer, ctx: SessionContext, name: str, arguments: dict, fn) -> dict:
    t0 = time.perf_counter()
    try:
        if name in ctx.fail_tools:
            raise RuntimeError("Panne simulée de l'outil (test de robustesse).")
        result = fn()
        tracer.add(tool=name, arguments=arguments, status="ok",
                   duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                   result=result, result_digest=digest(result), data_refs=_data_refs(result))
        return result
    except Exception as e:  # noqa: BLE001 - toute erreur est enregistrée puis renvoyée au modèle comme erreur
        msg = sanitize(f"{type(e).__name__}: {e}")
        tracer.add(tool=name, arguments=arguments, status="error",
                   duration_ms=round((time.perf_counter() - t0) * 1000, 2), error=msg)
        return {"status": "error", "tool": name, "message": msg, "instruction": ERROR_INSTRUCTION}


def _funds(service: GuardianService, res) -> dict:
    """Contexte FNB (texte et indicateurs) : n'altère ni les poids, ni le HHI, ni les statuts."""
    return fund_exposure(res.weights, service.bundle.universe, res.concentration.max_ticker, res.concentration.max_weight)


LINE_TYPES = {"equity": "action individuelle", "etf_equity": "FNB d'actions", "etf_bond": "FNB d'obligations", "etf_commodity": "fonds adossé à l'or",
              "crypto": "cryptoactif"}
FACTS_RULE = ("Faits déjà calculés par Python : recopie-les tels quels. N'additionne pas et ne recalcule pas d'autres pourcentages ; "
              "si une mesure n'apparaît pas ici ni ailleurs dans le résultat, dis qu'elle n'est pas mesurée.")


CLASS_LABELS = {"equity": "actions individuelles", "etf_equity": "FNB d'actions", "etf_bond": "FNB d'obligations", "etf_commodity": "fonds adossé à l'or",
                "crypto": "cryptoactifs"}


def _class_breakdown(out: dict, universe) -> dict:
    """Répartition par classe d'actifs du moteur (asset_class_exposure_pct) avec les titres de chaque classe ; aucune nouvelle mesure."""
    w = out.get("weights_pct") or {}
    members: dict = {}
    for t in w:
        members.setdefault(str(universe.loc[t, "asset_class"]), []).append(t)
    exp = out.get("asset_class_exposure_pct") or {c: round(sum(w[t] for t in ts), 2) for c, ts in members.items()}
    return {"classes": [{"classe": CLASS_LABELS.get(c, c), "pct": v, "titres": members.get(c, [])} for c, v in sorted(exp.items(), key=lambda kv: -kv[1])],
            "note": "Chaque titre n'appartient qu'à une classe : les FNB d'actions (par exemple QQQ) ne sont pas inclus dans les actions individuelles."}


def portfolio_key_facts(out: dict, universe, findings: list | None = None) -> dict:
    """Faits structurés d'un portefeuille, repris des résultats du moteur (aucun nouveau calcul financier : tri des poids et égalités seulement)."""
    w = out.get("weights_pct") or {}
    ranked = sorted(w.items(), key=lambda kv: (-kv[1], kv[0]))
    third = ranked[min(2, len(ranked) - 1)][1] if ranked else None
    tied = [t for t, v in ranked if v == third]
    above = [t for t, v in ranked if third is not None and v > third]
    c, m, win = out.get("concentration") or {}, out.get("metrics") or {}, out.get("window") or {}
    top = [{"rank": i + 1, "ticker": t, "name": str(universe.loc[t, "name"]), "weight_pct": v,
            "line_type": LINE_TYPES.get(str(universe.loc[t, "asset_class"]), str(universe.loc[t, "asset_class"]))} for i, (t, v) in enumerate(ranked[:3])]
    facts = {
        "rule": FACTS_RULE,
        "top_positions": top, "top3_total_pct": c.get("top3_weight_pct"),
        "top3_ties": (None if len(above) + len(tied) <= 3 else
                      f"Égalité : {', '.join(tied)} pèsent chacun {third} % ; seules {3 - len(above)} d'entre elles entrent dans les trois plus grandes "
                      f"positions, le choix est arbitraire. Le total des trois plus grandes positions reste {c.get('top3_weight_pct')} %."),
        "répartition_par_classe": _class_breakdown(out, universe),
        "indicators": {"période": f"{win.get('start')} au {win.get('end')} (CAD, historique)",
                       "rendement cumulé (%)": m.get("cumulative_return_pct"), "rendement annualisé (%)": m.get("annualized_return_pct"),
                       "volatilité annualisée du portefeuille (%)": m.get("annualized_volatility_pct"),
                       "plus forte baisse historique du portefeuille (%)": m.get("max_drawdown_pct"),
                       "plus grande position (%)": c.get("largest_position_weight_pct"),
                       "nombre effectif de positions (lignes, pas entreprises)": c.get("effective_number_of_positions")},
    }
    if findings is not None:
        facts["guardian_findings"] = [{"règle": f["rule_id"], "critère": f["title"], "statut": f["status_label"], "mesuré": (f.get("display") or {}).get("measured"),
                                       "repère d'attention": (f.get("display") or {}).get("attention"), "repère de conflit": (f.get("display") or {}).get("conflict")}
                                      for f in findings if f.get("status") != "INFO"]
        ev10 = next((f.get("evidence") or {} for f in findings if f.get("rule_id") == "R10"), {})
        if ev10.get("tech_share_pct") is not None:
            facts["technology"] = technology_facts(ev10["tech_share_pct"], ev10.get("tech_positions", []), ev10.get("qqq_weight_pct") or 0.0)
    return facts


def active_profile_facts(service: GuardianService, pid: str) -> dict:
    """Profil officiel actif et repères de concentration de la configuration (aucun calcul ; les statuts restent dans check_profile_constraints)."""
    p = service.profiles[pid]
    rules = service.rules_cfg["rules"]
    pct = lambda x: f"{100 * x:g} %"  # noqa: E731
    r1, r7 = rules["R1"]["thresholds"][pid], rules["R7"]["thresholds"][pid]
    return {
        "persona": p["display_name"], "âge": p.get("age"), "niveau_de_risque": p["risk_profile_label"],
        "horizon": (f"{p['horizon_years_min']} à {p['horizon_years_max']} ans" if p.get("horizon_years_max") else f"{p['horizon_years_min']} ans ou plus"),
        "repères_concentration_plus_grande_position": {"attention": f"> {pct(r1['attention'])}", "conflit": f"> {pct(r1['conflict'])}"},
        "repères_nombre_effectif_de_positions": {"attention": f"< {r7['attention']:g}", "conflit": f"< {r7['conflict']:g}"},
        "note": "Repères heuristiques du prototype pour ce profil. Les statuts (vigilance, conflit) sont donnés par check_profile_constraints.",
    }


def technology_facts(share_pct: float, tickers: list, qqq_pct: float) -> dict:
    """Part technologique telle que mesurée par le moteur (R10 / rules.engine.tech_share), avec ce qu'elle ne mesure pas."""
    return {
        "part_directe_mesurée_pct": share_pct, "titres_comptés": list(tickers), "QQQ_pct_non_décomposé": qqq_pct,
        "exposition_technologique_totale_mesurée": False,
        "à_dire": ("La part directement mesurée est celle des titres étiquetés technologie ou communication. QQQ est un FNB fortement technologique "
                   "mais pas entièrement : ces deux nombres ne s'additionnent pas. L'exposition technologique totale n'est pas mesurée, et aucun seuil "
                   "n'est appliqué à la part technologique."),
    }


def esg_key_facts(out: dict) -> dict | None:
    """Faits ESG structurés repris du module ESG (aucune nouvelle donnée)."""
    if not out.get("applicable"):
        return None
    cov = out["coverage"]
    lines = out.get("lines") or []
    by_state = lambda s: [x["ticker"] for x in lines if x["state"] == s]  # noqa: E731
    na, ins = by_state("NOT_APPLICABLE"), by_state("INSUFFICIENT")
    cats = [{"catégorie": c["label"], "décision": c["decision_label"], "dimension": c["dimension_label"], "titres": c["tickers"], "poids_pct": c["weight_pct"],
             "dates_de_décision": sorted({r["published"] for r in c["records"]}), "lien_avec_la_préférence_déclarée": c["relevance"] == "direct"}
            for c in [*out.get("documented_categories", []), *out.get("complementary_information", [])]]
    return {
        "rule": FACTS_RULE,
        "couverture_pct (part cherchée dans au moins une source)": cov.get("checked_in_sources_pct"),
        "cherché_sans_correspondance_pct (ce n'est ni la couverture ni une conformité)": cov["weights_by_state_pct"].get("Aucune controverse identifiée dans les sources consultées", 0.0),
        "non_évaluable_pct (FNB sans composition, non vérifiés)": (out.get("fund_verification") or {}).get("weight_pct", 0.0), "non_évaluables": ins,
        "sans_objet (non vérifiés, sans entreprise émettrice)": na,
        "catégories_documentées (ne s'additionnent pas)": cats,
        "seuils_ESG": "aucun : le module ESG n'utilise ni seuil ni score",
    }


def _profile(service: GuardianService, ctx: SessionContext, profile_id: str) -> str:
    pid = (profile_id or "").strip().lower() or ctx.profile_id
    if pid not in service.profiles:
        raise ValueError(f"Profil inconnu : {pid!r}. Profils disponibles : {sorted(service.profiles)}.")
    if ctx.allowed_profiles is not None and pid not in ctx.allowed_profiles:
        raise ValueError(f"Le profil {pid!r} n'est pas autorisé pour cette requête : l'utilisateur ne l'a pas nommé et le profil actif est "
                         f"{ctx.profile_id!r}. Demandez à l'utilisateur de sélectionner ce profil dans l'interface.")
    return pid


def _portfolio(ctx: SessionContext, portfolio: str) -> tuple[str, dict]:
    p = (portfolio or "A").strip().upper()
    if p == "A":
        return "A", ctx.weights
    if p == "B":
        if not ctx.weights_b:
            raise ValueError("Aucun portefeuille B n'est sélectionné dans l'interface.")
        return "B", ctx.weights_b
    raise ValueError("Le paramètre portfolio doit valoir 'A' ou 'B'.")


def build_tools(service: GuardianService, ctx: SessionContext, tracer: Tracer) -> list:
    @tool
    def get_profile(profile_id: str = "") -> dict:
        """Retourne le profil officiel d'un investisseur fictif et les seuils heuristiques du Guardian Check qui lui sont appliqués.

        À utiliser pour connaître l'objectif, l'horizon, la tolérance au risque et les préférences d'un persona
        (robert ou amira). Les seuils sont des heuristiques pédagogiques du prototype, pas des normes.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
        """
        args = {"profile_id": profile_id}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            thresholds = {rid: {"title": r["title"], "direction": r["direction"], **r["thresholds"][pid]}
                          for rid, r in service.rules_cfg["rules"].items() if pid in r["thresholds"]}
            return {"status": "ok", "profile_id": pid, "is_active_profile": pid == ctx.profile_id,
                    "profile": service.profiles[pid], "heuristic_thresholds": thresholds,
                    "thresholds_are_heuristics": True, "rules_config_version": service.rules_cfg["version"],
                    "available_profiles": sorted(service.profiles)}

        return _run(tracer, ctx, "get_profile", args, run)

    @tool
    def evaluate_portfolio(portfolio: str = "A", start_date: str = "", end_date: str = "") -> dict:
        """Calcule les métriques historiques d'un portefeuille fictif sélectionné dans l'interface, en dollars canadiens (CAD).

        Retourne rendement cumulé et annualisé, volatilité annualisée, drawdown maximal, concentration,
        exposition par classe d'actifs et statistiques par actif, avec la provenance des données.
        Les portefeuilles sont déjà connus du système : ne fournis aucun poids.
        `fund_exposure` indique les FNB détenus et rappelle que la diversification sous-jacente des FNB n'est pas mesurée.

        Args:
            portfolio: "A" (portefeuille principal) ou "B" (portefeuille de comparaison). Par défaut "A".
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"portfolio": portfolio, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            label, w = _portfolio(ctx, portfolio)
            res = service.analyze(w, start_date or None, end_date or None)
            out = res.to_tool_dict()
            out["fund_exposure"] = _funds(service, res)
            out["key_facts"] = portfolio_key_facts(out, service.bundle.universe)
            out["key_facts"]["profil_actif"] = active_profile_facts(service, ctx.profile_id)
            if service.profiles.get(ctx.profile_id, {}).get("show_sector_context"):
                share, tickers, qqq = tech_share(res, service.rules_cfg.get("tech_sectors", []))
                out["key_facts"]["technology"] = technology_facts(round(100 * share, 2), tickers, round(100 * qqq, 2))
            out["portfolio"] = label
            return out

        return _run(tracer, ctx, "evaluate_portfolio", args, run)

    @tool
    def check_profile_constraints(profile_id: str = "", portfolio: str = "A", start_date: str = "", end_date: str = "") -> dict:
        """Exécute le Guardian Check : confronte un portefeuille fictif au profil d'un investisseur.

        Retourne le profil officiel du persona, puis un constat par règle (statut OK, ATTENTION, CONFLIT ou INFO,
        valeur mesurée, seuils heuristiques, justification, méthode, limites), les limites générales
        et les informations manquantes. Un statut CONFLIT signale un conflit potentiel selon des seuils heuristiques, pas une norme.
        Les mesures financières sont identiques pour tous les profils ; seuls les seuils et les statuts changent.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
            portfolio: "A" (portefeuille principal) ou "B" (portefeuille de comparaison). Par défaut "A".
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"profile_id": profile_id, "portfolio": portfolio, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            label, w = _portfolio(ctx, portfolio)
            res, report = service.check(w, pid, start_date or None, end_date or None)
            full = res.to_tool_dict()
            out = report.to_dict()
            out.update({"profile": service.profiles[pid], "portfolio": label, "window": full["window"],
                        "weights_pct": full["weights_pct"], "metrics": full["metrics"], "concentration": full["concentration"],
                        "provenance": res.provenance, "fund_exposure": _funds(service, res)})
            out["key_facts"] = portfolio_key_facts(out, service.bundle.universe, out["findings"])
            return out

        return _run(tracer, ctx, "check_profile_constraints", args, run)

    @tool
    def compare_scenarios(profile_id: str = "", start_date: str = "", end_date: str = "") -> dict:
        """Compare les portefeuilles fictifs A et B sélectionnés dans l'interface, sur exactement la même période et la même grille de dates.

        Retourne pour chacun : métriques historiques en CAD, concentration, expositions et constats du Guardian Check
        pour le profil demandé ; puis les écarts B moins A et des compromis historiques formulés sans désigner de gagnant.
        Nécessite qu'un portefeuille B soit sélectionné dans l'interface.

        Args:
            profile_id: "robert" ou "amira". Laisser vide pour le profil actif dans l'interface.
            start_date: Date de début optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
            end_date: Date de fin optionnelle au format AAAA-MM-JJ. Laisser vide pour la période complète.
        """
        args = {"profile_id": profile_id, "start_date": start_date, "end_date": end_date}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            _, wa = _portfolio(ctx, "A")
            _, wb = _portfolio(ctx, "B")
            cmp_ = service.compare(wa, wb, pid, start_date or None, end_date or None)
            out = cmp_.to_tool_dict()
            out["portfolio_A"]["fund_exposure"] = _funds(service, cmp_.a)
            out["portfolio_B"]["fund_exposure"] = _funds(service, cmp_.b)
            for key, g in (("portfolio_A", "guardian_A"), ("portfolio_B", "guardian_B")):
                out[key]["key_facts"] = portfolio_key_facts({**out[key], "window": out["window"]}, service.bundle.universe, out[g]["findings"])
            out["profile"] = service.profiles[pid]          # faits officiels du persona, à citer tels quels
            return out

        return _run(tracer, ctx, "compare_scenarios", args, run)

    @tool
    def check_esg_preferences(profile_id: str = "", portfolio: str = "A") -> dict:
        """Vérifie la cohérence d'un portefeuille fictif avec les préférences ESG DÉCLARÉES d'un profil (module déterministe, distinct du Guardian Check financier).

        Retourne l'état global et par ligne (controverse documentée à examiner, aucune controverse identifiée dans les sources consultées,
        information insuffisante, non applicable), la couverture des données en poids du portefeuille, l'exposition par ligne et celle des FNB,
        les sources consultées (URL, date, limites), les incertitudes et les règles appliquées. Aucun score ESG n'existe : n'en invente jamais.
        Les informations documentées sont séparées par catégorie (`documented_categories` : critère lié à la préférence ; `complementary_information` :
        hors critère déclaré, par exemple gouvernance), chacune avec sa décision (exclusion ou observation), sa dimension (E, S ou G), son poids et ses tickers.
        Ne jamais les additionner en un seul pourcentage « en conflit ».
        Une absence de résultat n'est pas une preuve d'absence de controverse. Pour un profil sans préférences ESG déclarées, retourne « non applicable ».

        Args:
            profile_id: "robert", "amira" ou "mateo". Laisser vide pour le profil actif dans l'interface.
            portfolio: "A" (portefeuille principal) ou "B" (portefeuille de comparaison). Par défaut "A".
        """
        args = {"profile_id": profile_id, "portfolio": portfolio}

        def run() -> dict:
            pid = _profile(service, ctx, profile_id)
            label, w = _portfolio(ctx, portfolio)
            out = service.check_esg(w, pid).to_dict()
            out["key_facts"] = esg_key_facts(out)
            out["portfolio"] = label
            out["profile"] = service.profiles[pid]
            return out

        return _run(tracer, ctx, "check_esg_preferences", args, run)

    return [get_profile, evaluate_portfolio, check_profile_constraints, compare_scenarios, check_esg_preferences]
