"""Cartes Guardian en français simple. Les VALEURS, SEUILS et STATUTS viennent exclusivement du moteur ; ce module ne fait que les formuler.

Chaque carte : A. quel problème ? B. quel chiffre ? C. pourquoi pour ce profil ? D. quel niveau de vigilance ? E. comment c'est calculé ?
Les statuts internes (CONFLIT, ATTENTION, OK, INFO) sont conservés dans `status` et dans les détails avancés.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guardian.explain.funds import fund_exposure
from guardian.explain.format import asset_label, fr, fr_date, horizon_text, pct, pct_value
from guardian.rules.engine import ATTENTION, CONFLIT, INFO, OK, GuardianReport

LEVELS = {
    CONFLIT: ("important", "Risque important à examiner"),
    ATTENTION: ("vigilance", "Point de vigilance"),
    OK: ("ok", "Aucun dépassement détecté selon ce critère"),
    INFO: ("info", "Information complémentaire"),
}
PLAIN_TITLES = {"R1": "Poids de la plus grande position", "R2": "Part d'actifs très fluctuants", "R4": "Fluctuations du portefeuille",
                "R5": "Plus forte baisse historique", "R7": "Répartition entre positions", "R10": "Contexte de l'analyse"}
CALC_DISCLAIMER = "Ce repère est pédagogique et ne constitue pas une norme universelle."


@dataclass(frozen=True)
class Card:
    rule_id: str
    status: str                 # statut interne du moteur : OK, ATTENTION, CONFLIT, INFO
    level_kind: str             # important | vigilance | ok | info
    level_label: str
    headline: str               # A. quel est le problème ?
    measure: str                # B. quel chiffre l'explique ?
    why: str                    # C. pourquoi pour ce profil ?
    precision: str              # repère utilisé, en français simple
    how: str                    # E. comprendre ce calcul
    limits: tuple
    advanced: dict = field(default_factory=dict)   # jargon et détails techniques (repliés dans l'interface)
    note: str | None = None     # précision pédagogique (FNB) : ne change ni la mesure, ni le repère, ni le statut


def diversification_sentence(result) -> str:
    """Distingue le nombre RÉEL de positions et le nombre EFFECTIF (1/HHI)."""
    n = len(result.weights)
    eff = result.concentration.effective_n
    return (f"Votre portefeuille contient {n} actif{'s' if n > 1 else ''}. Selon la répartition de leurs poids, sa diversification est "
            f"équivalente à environ {fr(eff)} position{'s' if eff >= 2 else ''} de poids égal.")


def _preference_note(profile: dict, keyword: str) -> str:
    for p in profile.get("preferences", []):
        if keyword in p.lower():
            return f" Préférence indiquée par {profile['display_name']} : « {p} »"
    return ""


def _info_measure(fd, name: str, universe) -> str:
    ev = fd.evidence
    parts = [f"L'analyse porte sur {fr(ev['window_years'])} ans ({ev['n_observations']} dates communes) ; les fonds (FNB) ne sont pas décomposés en titres."]
    if ev.get("tech_share_pct") is not None:
        tick = ", ".join(asset_label(universe, t) for t in ev["tech_positions"]) or "aucune position"
        s = f"Part des positions étiquetées technologie ou communication : {pct_value(ev['tech_share_pct'])} ({tick})."
        if ev.get("qqq_weight_pct"):
            s += f" S'y ajoutent {pct_value(ev['qqq_weight_pct'])} dans QQQ, un fonds fortement technologique non décomposé."
        parts.append(s)
    return " ".join(parts)


def build_cards(result, report: GuardianReport, profile: dict, universe, rules_cfg: dict) -> list[Card]:
    name = profile["display_name"]
    horizon = horizon_text(profile)
    short = f"Pour {name} (horizon de {horizon}, risque {profile['risk_profile_label'].lower()})"
    f = report.by_id()
    top = result.concentration.max_ticker
    top_label = asset_label(universe, top)
    cards: list[Card] = []
    fx = fund_exposure(result.weights, universe, top, result.concentration.max_weight)

    def level(status):
        return LEVELS[status]

    def adv(fd) -> dict:
        d = {"Règle": fd.rule_id, "Statut interne": fd.status, "Valeur mesurée": fd.display.get("measured", ""),
             "Seuils heuristiques": f"attention {fd.display.get('attention', '')} ; conflit {fd.display.get('conflict', '')}" if fd.status != INFO else "aucun seuil",
             "Méthode (technique)": fd.method, "Justification (configuration)": fd.justification,
             "Limites (configuration)": list(fd.limitations), "Version de la configuration": fd.config_version,
             "Nature": "Règle déterministe calculée par le code Python ; seuils heuristiques du prototype, pas des normes."}
        return d

    def ok_why() -> str:
        return (f"Selon ce critère, aucun repère n'est dépassé pour {name}. Cela ne signifie pas que le portefeuille est sans risque : "
                "les autres critères et les limites de l'analyse restent à lire.")

    # ---------------------------------------------------------------- R1
    fd = f["R1"]
    k, lab = level(fd.status)
    wpct = 100 * result.concentration.max_weight
    cards.append(Card(
        "R1", fd.status, k, lab,
        headline=("Aucune position ne domine votre portefeuille." if fd.status == OK
                  else f"Votre portefeuille dépend beaucoup de {top_label}." if fd.status == CONFLIT
                  else f"Une position pèse lourd dans votre portefeuille : {top_label}."),
        measure=f"{top_label} représente {pct_value(wpct)} de votre argent fictif.",
        why=(ok_why() if fd.status == OK else
             f"{short} : une forte part dans une seule position peut augmenter l'effet d'une mauvaise période de cette position sur l'ensemble "
             f"du portefeuille.{_preference_note(profile, 'diversification')}"),
        precision=(f"Notre outil considère qu'une position qui dépasse {pct_value(100 * fd.threshold_conflict)} mérite une vigilance importante "
                   f"pour le profil de {name}, et qu'au-delà de {pct_value(100 * fd.threshold_attention)} c'est un point de vigilance. {CALC_DISCLAIMER}"),
        how="Pour chaque position, on regarde sa part dans votre allocation, puis on retient la plus grande.",
        note=fx["pedagogical_note"] if fx["has_funds"] and fx["largest_position_is_fund"] else None,
        limits=("Cette mesure regarde la part de chaque position. Un fonds qui détient plusieurs entreprises peut être plus diversifié qu'une action "
                "individuelle, même si notre règle leur applique le même repère.",
                "Elle ne tient pas compte des liens entre les actifs."),
        advanced=adv(fd)))

    # ---------------------------------------------------------------- R2
    fd = f["R2"]
    k, lab = level(fd.status)
    vol_assets = fd.evidence["volatile_assets"]
    share = 100 * fd.measured
    vol_thr = pct_value(fd.evidence["asset_volatility_threshold_pct"], 0)
    listing = ", ".join(f"{asset_label(universe, a['ticker'])} ({pct_value(a['weight_pct'])})" for a in vol_assets)
    cards.append(Card(
        "R2", fd.status, k, lab,
        headline=("Peu d'actifs de votre portefeuille ont beaucoup fluctué." if fd.status == OK
                  else "Une part importante de votre portefeuille est placée dans des actifs qui ont beaucoup fluctué." if fd.status == CONFLIT
                  else "Une part de votre portefeuille est placée dans des actifs qui ont beaucoup fluctué."),
        measure=(f"{pct_value(share)} de votre argent fictif est placé dans des actifs très fluctuants : {listing}." if vol_assets
                 else f"Aucun actif ne dépasse le repère de fluctuation ({vol_thr} par an) et il n'y a pas de cryptomonnaie."),
        why=(ok_why() if fd.status == OK else
             f"{short} : les actifs qui ont beaucoup fluctué par le passé peuvent connaître de fortes hausses comme de fortes baisses ; "
             "plus ils pèsent lourd, plus la valeur de tout le portefeuille est sensible à leurs variations."),
        precision=(f"Notre outil considère qu'une part de ces actifs qui dépasse {pct_value(100 * fd.threshold_conflict)} mérite une vigilance importante "
                   f"pour {name}, et {pct_value(100 * fd.threshold_attention)} un point de vigilance. {CALC_DISCLAIMER}"),
        how=(f"On repère les actifs dont le prix a fluctué de plus de {vol_thr} par an sur la période (ainsi que les cryptomonnaies), "
             "puis on additionne leurs parts dans votre allocation."),
        limits=("Les fluctuations passées ne prédisent pas les fluctuations futures.",
                f"Le repère de {vol_thr} par an est lui-même un choix pédagogique, calculé sur une seule période de cinq ans."),
        advanced=adv(fd)))

    # ---------------------------------------------------------------- R4
    fd = f["R4"]
    k, lab = level(fd.status)
    cards.append(Card(
        "R4", fd.status, k, lab,
        headline=("Les fluctuations de votre portefeuille restent sous le repère." if fd.status == OK
                  else "Votre portefeuille a beaucoup fluctué par le passé." if fd.status == CONFLIT
                  else "Votre portefeuille a assez fluctué par le passé."),
        measure=f"Ses fluctuations (volatilité) ont été d'environ {pct(fd.measured)} par an sur la période observée.",
        why=(ok_why() if fd.status == OK else
             f"{short} : des fluctuations importantes signifient que la valeur du portefeuille a souvent beaucoup varié, à la hausse comme à la baisse."),
        precision=(f"Notre outil considère que des fluctuations au-delà de {pct_value(100 * fd.threshold_conflict)} par an méritent une vigilance importante "
                   f"pour {name}, et au-delà de {pct_value(100 * fd.threshold_attention)} un point de vigilance. {CALC_DISCLAIMER}"),
        how="On mesure l'écart typique des variations quotidiennes de la valeur du portefeuille (rééquilibré chaque mois), puis on le ramène à une année.",
        limits=("C'est un indicateur de risque parmi d'autres : l'horizon, la diversification et vos préférences comptent aussi.",
                "Calculée sur cinq ans seulement, avec un biais du survivant dans l'univers d'actifs."),
        advanced=adv(fd)))

    # ---------------------------------------------------------------- R5
    fd = f["R5"]
    k, lab = level(fd.status)
    dd = result.drawdown
    recov = (f"Le portefeuille a retrouvé son niveau de départ le {fr_date(dd.recovery_date)}." if dd.recovered
             else "Le portefeuille n'avait pas retrouvé ce sommet à la fin de la période.")
    cards.append(Card(
        "R5", fd.status, k, lab,
        headline=("Les baisses passées de votre portefeuille restent sous le repère." if fd.status == OK
                  else "Votre portefeuille a déjà connu une baisse importante." if fd.status == CONFLIT
                  else "Votre portefeuille a déjà connu une baisse notable."),
        measure=(f"Sa plus forte baisse historique a atteint −{fr(100 * fd.measured)} % (du {fr_date(dd.peak_date)} au {fr_date(dd.trough_date)}). {recov}"),
        why=(ok_why() if fd.status == OK else
             f"{short} : une baisse profonde demande du temps pour être récupérée, et l'horizon de {horizon} limite ce temps. "
             f"Cela ne dit rien de la tolérance personnelle réelle de {name}, que nous ne connaissons pas."),
        precision=(f"Notre outil considère qu'une baisse historique au-delà de {pct_value(100 * fd.threshold_conflict)} mérite une vigilance importante "
                   f"pour {name}, et au-delà de {pct_value(100 * fd.threshold_attention)} un point de vigilance. {CALC_DISCLAIMER}"),
        how="On suit la valeur du portefeuille simulé jour après jour et on repère la plus grande baisse depuis un sommet.",
        limits=("Une seule trajectoire historique : une baisse future pourrait être plus importante ou plus faible.",
                "Le repère ne présume pas de la perte que vous accepteriez réellement : aucune perte maximale acceptable n'a été saisie."),
        advanced=adv(fd)))

    # ---------------------------------------------------------------- R7
    fd = f["R7"]
    k, lab = level(fd.status)
    cards.append(Card(
        "R7", fd.status, k, lab,
        headline=("Votre argent est réparti entre plusieurs positions." if fd.status == OK
                  else "Votre argent est réparti entre peu de positions." if fd.status == CONFLIT
                  else "Votre argent pourrait être réparti plus largement."),
        measure=diversification_sentence(result),
        why=(ok_why() if fd.status == OK else
             f"{short} : quand l'argent est réparti entre peu de positions, le résultat dépend d'un petit nombre d'investissements."
             f"{_preference_note(profile, 'diversification')}"),
        precision=(f"Notre outil considère qu'une diversification équivalente à moins de {fr(fd.threshold_conflict, 0)} positions de poids égal mérite une vigilance "
                   f"importante pour {name}, et moins de {fr(fd.threshold_attention, 0)} un point de vigilance. {CALC_DISCLAIMER}"),
        how="On calcule 1 divisé par la somme des carrés des parts de chaque position (indice HHI). Quatre positions égales donnent 4.",
        note=fx["pedagogical_note"] if fx["has_funds"] else None,
        limits=("Cette mesure compte des positions, pas leurs liens : deux actions très corrélées comptent pour deux.",
                "Elle ne tient pas compte de la diversification interne des fonds (FNB) et n'est pas le nombre d'entreprises sous-jacentes."),
        advanced=adv(fd)))

    # ---------------------------------------------------------------- R10 (information)
    fd = f["R10"]
    k, lab = level(INFO)
    cards.append(Card(
        "R10", INFO, k, lab,
        headline="Ce qu'il faut savoir sur cette analyse.",
        measure=_info_measure(fd, name, universe),
        why=("Cette information n'est pas un contrôle : aucun repère n'est appliqué."
             + (f" {name} souhaite éviter une concentration exclusivement technologique ; nous affichons la part technologique à titre informatif."
                if fd.evidence.get("tech_share_pct") is not None else "")),
        precision="Aucun repère n'est appliqué à cette information.",
        how="Fenêtre d'analyse, nombre de dates communes et, lorsque le profil le mentionne, part des positions étiquetées technologie.",
        limits=tuple(fd.limitations),
        advanced=adv(fd)))
    return cards
