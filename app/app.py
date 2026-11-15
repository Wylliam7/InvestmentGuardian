"""Investment Guardian — V2 (refonte UX). Parcours : Je choisis → J'analyse → Je comprends → Je compare → Je questionne l'IA → Je vérifie.

Quatre onglets : Mon portefeuille · Comprendre mes risques · Comparer deux choix · Assistant IA.
Le moteur financier et le Guardian Check sont inchangés par rapport à V1 ; cette couche ne fait que présenter leurs résultats.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from charts import (allocation_figure, comparison_drawdown_figure, comparison_performance_figure,  # noqa: E402
                    drawdown_figure, performance_figure)
from components import render_card, render_esg_section, render_request, render_summary  # noqa: E402
from guardian.agent.agent import (EXPLAIN_ESG_REQUIRED, EXPLAIN_RISKS_LABEL, EXPLAIN_RISKS_REQUIRED, GuardianAgent,  # noqa: E402
                                  explain_risks_task)
from guardian.agent.aws_status import credentials_status, test_bedrock_connection  # noqa: E402
from guardian.agent.service import GuardianService  # noqa: E402
from guardian.agent.tools import SessionContext  # noqa: E402
from guardian.agent.tracer import Tracer  # noqa: E402
from guardian.data.loader import DataError  # noqa: E402
from guardian.explain.cards import LEVELS, PLAIN_TITLES, build_cards, diversification_sentence  # noqa: E402
from guardian.explain.compare_plain import COMPARE_FOOTER, COMPARE_SENSITIVITY_NOTE, plain_tradeoffs  # noqa: E402
from guardian.explain.esg_view import build_esg_view  # noqa: E402
from guardian.explain.funds import fund_exposure  # noqa: E402
from guardian.explain.format import fr, fr_date, horizon_text, persona_sentence, pct, pct_value  # noqa: E402
from guardian.explain.glossary import DIVERSIFICATION_HELP, METRIC_HELP, TERMS  # noqa: E402
from guardian.explain.summary import build_priority_summary  # noqa: E402
from guardian.finance.builder import normalize_to_100, parse_weight_rows, rows_from_weights  # noqa: E402
from guardian.esg.data import EsgDataError  # noqa: E402
from guardian.finance.compare import ComparisonError  # noqa: E402
from guardian.finance.portfolio import PortfolioError  # noqa: E402
from guardian.finance.presets import (PresetError, load_presets, load_profile_defaults, validate_presets,  # noqa: E402
                                      validate_profile_defaults)
from guardian.rules.engine import ATTENTION, CONFLIT, INFO, ConfigError, evaluate  # noqa: E402
from profile_flow import loadable, matches_suggestion, plan_switch, slot_status  # noqa: E402

st.set_page_config(page_title="Investment Guardian", page_icon="🛡️", layout="wide")

SEVERITY_ORDER = {CONFLIT: 0, ATTENTION: 1, "OK": 2, INFO: 3}
AUTH_LABELS = {"iam-role": "Rôle IAM (identifiants temporaires)", "env": "Variables d'environnement", "shared-credentials-file": "Fichier de profil AWS",
               "assume-role": "Rôle assumé", "sso": "Authentification unique (SSO)"}

st.markdown("""
<style>
.block-container {padding-top: 1.4rem; padding-left: 2.2rem; padding-right: 2.2rem; max-width: 100%;}
h1 {font-size: 3.4rem !important; font-weight: 800 !important; line-height: 1.1 !important; margin-bottom: .1rem !important;}
h2, h3 {margin-top: 1.1rem !important;}
h4 {margin-top: .3rem !important; margin-bottom: .4rem !important;}
.ig-sub {font-size: 1.4rem; margin: 0 0 .2rem 0; opacity: .9;}
.ig-banner {background: #FFF4D6; color: #3D2C00; border-left: 6px solid #B7791F; padding: .8rem 1.1rem;
            border-radius: 4px; margin: .4rem 0 1.2rem 0; font-size: 1.02rem; line-height: 1.5;}
.ig-banner b {color: #2B1F00;}
button[data-baseweb="tab"] p {font-size: 1.08rem; font-weight: 600;}
[data-testid="stMetricLabel"] p {font-size: 1.02rem;}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {line-height: 1.55;}
[data-testid="stVerticalBlockBorderWrapper"] {margin-bottom: .5rem;}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------------------- en-tête
st.title("🛡️ Investment Guardian")
st.markdown('<p class="ig-sub">Comprenez les risques de vos décisions d\'investissement.</p>', unsafe_allow_html=True)
st.caption("Your decisions. Your risks. Explained.")
st.markdown('<div class="ig-banner"><b>Simulation éducative — aucun conseil financier personnalisé.</b> '
            "Aucune transaction réelle. Les résultats décrivent le passé (2021-11-12 au 2026-11-12) et ne prédisent pas l'avenir. "
            "Les repères de vigilance sont pédagogiques, pas des normes.</div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- données et moteur
@st.cache_resource(show_spinner="Chargement et validation des données officielles…")
def get_service() -> GuardianService:
    return GuardianService.from_default()


@st.cache_data(ttl=300, show_spinner=False)
def cached_credentials() -> dict:
    """Détection locale des identifiants (sans appel Bedrock), mise en cache pour ne pas la répéter à chaque rafraîchissement."""
    return credentials_status()


try:
    service = get_service()
    PRESETS = load_presets()
    validate_presets(PRESETS, service.bundle.universe.index, service.profiles)
    DEFAULTS = load_profile_defaults()
    validate_profile_defaults(DEFAULTS, PRESETS, service.profiles)
except (DataError, ConfigError, PresetError) as e:
    st.error(f"Impossible de charger les données ou la configuration : {e}")
    st.stop()

UNIVERSE = sorted(service.bundle.universe.index)
PROFILE_IDS = list(service.profiles)
DEFAULT_A, DEFAULT_B = DEFAULTS[PROFILE_IDS[0]]["a"], DEFAULTS[PROFILE_IDS[0]]["b"]
SUGGESTED_QUESTIONS = ("Pourquoi ce portefeuille pourrait-il présenter des risques pour ce profil ?",
                       "Compare le portefeuille A avec le portefeuille B. Quels compromis historiques observes-tu ?")


def fmt_pts(x):
    return "n.d." if x is None else f"{x:+.1f}".replace(".", ",") + " pts"


# ----------------------------------------------------------------------------- état de session
def _slot_from_preset(pid: str, ver: int = 0) -> dict:
    """Nouvel emplacement chargé depuis un préréglage. `ver` change toujours, pour ne pas réutiliser l'état de l'ancien éditeur."""
    p = PRESETS[pid]
    return {"preset": pid, "df": pd.DataFrame(rows_from_weights(p["weights_pct"])), "ver": ver,
            "applied_pct": dict(p["weights_pct"]), "msg": None, "dirty": False}


if "slots" not in st.session_state:
    st.session_state.slots = {"A": _slot_from_preset(DEFAULT_A), "B": _slot_from_preset(DEFAULT_B)}
    st.session_state.use_b = True
    st.session_state.tracer = Tracer()
    st.session_state.ctx = SessionContext(weights={}, profile_id=PROFILE_IDS[0])
    st.session_state.agent = GuardianAgent(service, st.session_state.ctx, st.session_state.tracer)
    st.session_state.history = []
    st.session_state.touched = False            # l'utilisateur n'a encore choisi ni modifié aucune allocation
    st.session_state.last_profile = PROFILE_IDS[0]
    st.session_state.profile_notice = None      # {"kind": "auto"|"suggest"|"loaded", "profile": id}
    st.session_state.prev_slots = None
    st.session_state.analysis_ok = None         # confirmation de la dernière analyse déclenchée par le bouton
    st.session_state.explain_turn = None        # dernière demande « Explique-moi mes risques avec l'IA »
    st.session_state.q_text = SUGGESTED_QUESTIONS[0]

slots = st.session_state.slots
ctx: SessionContext = st.session_state.ctx
agent: GuardianAgent = st.session_state.agent


def load_preset_cb(key: str) -> None:
    """Choix explicite d'un préréglage par l'utilisateur."""
    pid = st.session_state[f"preset_{key}"]
    st.session_state.touched = True
    st.session_state.profile_notice = None
    st.session_state.analysis_ok = None
    if pid == "custom":
        slots[key]["preset"] = "custom"
    else:
        slots[key] = _slot_from_preset(pid, slots[key]["ver"] + 1)


def _statuses() -> dict:
    return {k: slot_status(slots[k], PRESETS) for k in ("A", "B")}


def on_profile_change() -> None:
    """Changement de profil : proposer les scénarios du profil, sans jamais écraser un portefeuille personnalisé ou en cours d'édition."""
    new = st.session_state.profile_id
    st.session_state.last_profile = new
    st.session_state.analysis_ok = None
    d = DEFAULTS[new]
    if matches_suggestion(slots, d):
        st.session_state.profile_notice = None
        return
    if plan_switch(_statuses(), st.session_state.touched) == "auto_load":
        st.session_state.prev_slots = copy.deepcopy(slots)          # permet de revenir en un clic à l'allocation précédente
        for k, pid in (("A", d["a"]), ("B", d["b"])):
            slots[k] = _slot_from_preset(pid, slots[k]["ver"] + 1)
        st.session_state.profile_notice = {"kind": "auto", "profile": new}
    else:
        st.session_state.profile_notice = {"kind": "suggest", "profile": new}


def load_suggestions_cb() -> None:
    """Action explicite : charge les scénarios suggérés, uniquement dans les emplacements qui sont des préréglages intacts."""
    new = st.session_state.profile_id
    d = DEFAULTS[new]
    st.session_state.prev_slots = copy.deepcopy(slots)
    targets = loadable(_statuses())                               # jamais un portefeuille personnalisé ou en cours d'édition
    for k in targets:
        slots[k] = _slot_from_preset(d["a" if k == "A" else "b"], slots[k]["ver"] + 1)
    st.session_state.analysis_ok = None
    st.session_state.profile_notice = {"kind": "loaded", "profile": new, "kept": [k for k in ("A", "B") if k not in targets]}


def revert_slots_cb() -> None:
    if st.session_state.prev_slots:
        for k in ("A", "B"):
            old = st.session_state.prev_slots[k]
            old["ver"] = slots[k]["ver"] + 1
            slots[k] = old
        st.session_state.prev_slots = None
        st.session_state.touched = True
        st.session_state.analysis_ok = None
        st.session_state.profile_notice = None


def select_profile_cb(pid: str) -> None:
    st.session_state.profile_id = pid
    on_profile_change()


def set_question_cb(text: str) -> None:
    st.session_state.q_text = text


def applied_fractions(key: str) -> dict:
    return {t: w / 100.0 for t, w in slots[key]["applied_pct"].items()}


def slot_label(key: str) -> str:
    pid = slots[key]["preset"]
    return PRESETS[pid]["label"] if pid in PRESETS and PRESETS[pid]["weights_pct"] == slots[key]["applied_pct"] else "Portefeuille personnalisé"


# ----------------------------------------------------------------------------- sélection du profil
top1, top2 = st.columns([1, 3])
profile_id = top1.selectbox("Profil de l'investisseur", PROFILE_IDS, key="profile_id", on_change=on_profile_change,
                            format_func=lambda p: service.profiles[p]["display_name"],
                            help="Robert et Amira sont des personnages fictifs du cas officiel du Datathon.")
profile = service.profiles[profile_id]
horizon = horizon_text(profile)
HAS_ESG = bool(profile.get("esg_preferences"))
esg_line = ""
if HAS_ESG:
    esg_line = "  \n**Préférences ESG :** " + " ".join(profile["esg_preferences"]["importance"].split()) + " " + " ".join(
        c["official_wording"] for c in profile["esg_preferences"]["criteria"])
top2.markdown(f"**{profile['display_name']}** · {profile['age']} ans · {profile['occupation']} · risque **{profile['risk_profile_label'].lower()}** · "
              f"horizon **{horizon}**  \n**Objectif :** {profile['objective']}" + esg_line)

notice = st.session_state.profile_notice
if notice and notice["profile"] == profile_id:
    d = DEFAULTS[profile_id]
    names = f"A = {PRESETS[d['a']]['label']} ; B = {PRESETS[d['b']]['label']}"
    if notice["kind"] == "auto":
        st.info(f"Scénarios par défaut de **{profile['display_name']}** chargés (vous n'aviez encore rien modifié) : {names}. "
                "Vous pouvez évaluer n'importe quelle allocation pour ce profil en la choisissant dans « Mon portefeuille ».")
        if st.session_state.prev_slots:
            st.button("↩ Revenir à mon allocation précédente", on_click=revert_slots_cb, key="revert_slots")
    elif notice["kind"] == "suggest":
        st.info(f"**Scénarios suggérés pour {profile['display_name']}** : {names}. Vos allocations actuelles sont conservées : "
                "rien n'a été remplacé. Un portefeuille personnalisé ou en cours d'édition n'est jamais écrasé.")
        st.button(f"Charger les scénarios suggérés pour {profile['display_name']}", on_click=load_suggestions_cb, key="load_suggestions")
    elif notice["kind"] == "loaded":
        kept = " et ".join(notice["kept"])
        st.info(f"Scénarios suggérés chargés ({names})." + (f" Emplacement(s) conservé(s) car personnalisé(s), en cours d'édition ou déjà identique(s) : {kept}." if kept else ""))
        if st.session_state.prev_slots:
            st.button("↩ Revenir à mon allocation précédente", on_click=revert_slots_cb, key="revert_slots")

# contexte de l'agent = sélection réelle de l'interface
use_b = st.session_state.get("use_b", True)
ctx.profile_id = profile_id
ctx.weights = applied_fractions("A")
ctx.weights_b = applied_fractions("B") if use_b else None
ctx.fail_tools = {"evaluate_portfolio"} if st.session_state.get("sim_fail_eval") else set()

tab_build, tab_dash, tab_cmp, tab_ai = st.tabs(["1 · Mon portefeuille", "2 · Comprendre mes risques", "3 · Comparer deux choix", "4 · Assistant IA"])


# ----------------------------------------------------------------------------- 1. Mon portefeuille
def portfolio_editor(key: str, title: str) -> None:
    slot = slots[key]
    st.subheader(title)
    mine = [p for p in PRESETS if PRESETS[p]["profile_id"] == profile_id]       # scénarios du profil sélectionné, proposés en premier
    options = mine + [p for p in PRESETS if p not in mine] + ["custom"]
    st.session_state[f"preset_{key}"] = slot["preset"] if slot["preset"] in options else "custom"
    st.selectbox("Scénario prédéfini (★ = scénario du profil sélectionné)", options, key=f"preset_{key}", on_change=load_preset_cb, args=(key,),
                 help="Des portefeuilles fictifs de départ. Vous pouvez ensuite modifier les lignes ou en ajouter.",
                 format_func=lambda p: "Personnalisé" if p == "custom" else ("★ " if p in mine else "") + PRESETS[p]["label"])
    if slot["preset"] in PRESETS:
        st.markdown(f"**{PRESETS[slot['preset']]['label']}**")
        st.caption(" ".join(PRESETS[slot["preset"]]["description"].split()))
    else:
        st.markdown("**Portefeuille personnalisé**")
    if slot.get("msg"):
        st.info(slot["msg"])
    edited = st.data_editor(
        slot["df"], key=f"editor_{key}_{slot['ver']}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={"ticker": st.column_config.SelectboxColumn("Actif", options=UNIVERSE, help=TERMS["Actif"] + " Choisissez parmi les 31 actifs du jeu de données."),
                       "weight_pct": st.column_config.NumberColumn("Pondération (%)", step=0.5, format="%.2f", help=TERMS["Pondération"])})
    rows = [{"ticker": r["ticker"], "weight_pct": r["weight_pct"]} for r in edited.to_dict("records")]
    res = parse_weight_rows(rows, service.bundle.universe.index)
    slot["dirty"] = not (res.valid and res.weights_pct == slot["applied_pct"])      # saisie différente des poids analysés
    st.metric("Total des pondérations saisies", f"{fr(res.total_pct, 2)} %", help="Le total doit être exactement 100 %.",
              delta=(f"{res.total_pct - 100:+.2f} pts vs 100 %".replace(".", ",") if abs(res.total_pct - 100) > 0.005 else "100 %"),
              delta_color="off" if abs(res.total_pct - 100) <= 0.005 else "inverse")
    for err in res.errors:
        st.error(err)
    if res.valid:
        st.success("Pondérations valides : actifs connus, aucun doublon, aucun poids négatif, total de 100 %.")
    c1, c2 = st.columns(2)
    if c1.button("Analyser ce portefeuille", key=f"apply_{key}", disabled=not res.valid, type="primary",
                 help="Calcule les résultats avec ces pondérations. Aucun appel à l'assistant IA n'est effectué."):
        try:
            service.check(res.fraction_weights, profile_id)                         # calcul réel : si cela échoue, rien n'est appliqué
        except (PortfolioError, ConfigError, ValueError) as e:
            st.error(f"L'analyse a échoué : {e}. Les pondérations précédentes restent utilisées.")
        else:
            st.session_state.touched = True
            st.session_state.profile_notice = None
            slot["applied_pct"] = dict(res.weights_pct)
            slot["preset"] = next((p for p, v in PRESETS.items() if v["weights_pct"] == slot["applied_pct"]), "custom")
            slot["msg"] = None
            st.session_state.analysis_ok = {"key": key, "weights_pct": dict(res.weights_pct)}
            st.rerun()
    if res.only_sum_is_wrong and c2.button("Normaliser à 100 % (proportionnel)", key=f"norm_{key}",
                                           help="Action explicite : chaque pondération est multipliée par 100 / total. Rien n'est modifié sans ce clic."):
        st.session_state.touched = True
        slot["df"] = pd.DataFrame(rows_from_weights(normalize_to_100(res.rows_seen)))
        slot["ver"] += 1
        slot["msg"] = "Pondérations normalisées à 100 % à votre demande (proportionnellement). Cliquez sur « Analyser ce portefeuille » pour les appliquer."
        st.rerun()
    ok = st.session_state.analysis_ok
    if ok and ok["key"] == key and ok["weights_pct"] == slot["applied_pct"] and not slot["dirty"]:
        st.success(f"Votre portefeuille {key} a été analysé. Consultez l'onglet « Comprendre mes risques » pour découvrir les résultats.")
    elif slot["dirty"] and res.valid:
        st.warning("Modifications non appliquées : l'analyse utilise encore les pondérations ci-dessous. Cliquez sur « Analyser ce portefeuille ».")
    st.markdown("**Pondérations réellement analysées :** " + " · ".join(f"{t} {pct_value(w)}" for t, w in slot["applied_pct"].items()))


with tab_build:
    st.header("Mon portefeuille")
    st.markdown("Choisissez comment répartir votre argent fictif entre différents investissements.")
    with st.expander("Aide : comprendre les termes"):
        for term, definition in TERMS.items():
            st.markdown(f"- **{term}** : {definition}")
    st.checkbox("Comparer avec un second portefeuille (B)", key="use_b", help="Active l'onglet « Comparer deux choix » et l'outil de comparaison de l'assistant IA.")
    use_b = st.session_state.use_b
    cols = st.columns(2 if use_b else 1)
    with cols[0]:
        portfolio_editor("A", "Portefeuille A")
    if use_b:
        with cols[1]:
            portfolio_editor("B", "Portefeuille B")
    # les boutons « Analyser » ont pu changer les poids appliqués pendant ce passage
    ctx.weights = applied_fractions("A")
    ctx.weights_b = applied_fractions("B") if use_b else None

# ----------------------------------------------------------------------------- analyse du portefeuille A
try:
    weights_a = applied_fractions("A")
    result, report = service.check(weights_a, profile_id)
except (PortfolioError, ConfigError, ValueError) as e:
    st.error(f"Analyse impossible : {e}")
    st.stop()

cards = build_cards(result, report, profile, service.bundle.universe, service.rules_cfg)
summary = build_priority_summary(result, report, profile, service.bundle.universe)

# ----------------------------------------------------------------------------- 2. Comprendre mes risques
with tab_dash:
    st.header("Comprendre mes risques")
    st.markdown(f"**Portefeuille A — {slot_label('A')}**, évalué pour **{profile['display_name']}**. "
                f"Période historique : du {result.series.start.date()} au {result.series.end.date()} ({result.n_obs} dates communes), en dollars canadiens.")
    if HAS_ESG:
        st.info(f"Pour {profile['display_name']}, deux analyses distinctes : **A · Risques financiers** puis **B · Mes préférences ESG** (plus bas). "
                "Elles ne sont jamais combinées en une note unique : un portefeuille peut avoir peu d'alertes financières tout en ayant une cohérence ESG inconnue.")
        st.markdown("## A · Risques financiers")
    render_summary(summary)

    st.markdown("### Aller plus loin avec l'IA")
    explain_clicked = st.button(EXPLAIN_RISKS_LABEL, type="primary", key="explain_btn",
                                help="L'assistant IA (Amazon Bedrock, Nova 2 Lite) explique ces résultats en français simple, en s'appuyant sur les outils Python.")
    st.caption("L'IA reformule et relie les résultats calculés ci-dessous à votre profil. Elle ne modifie ni les chiffres, ni les repères, ni les statuts, "
               "et ne donne aucun conseil d'achat ou de vente.")
    if explain_clicked:
        with st.spinner("L'assistant IA analyse votre portefeuille avec les outils Python…"):
            required = EXPLAIN_RISKS_REQUIRED + (EXPLAIN_ESG_REQUIRED if HAS_ESG else ())
            tr = agent.ask(EXPLAIN_RISKS_LABEL, task=explain_risks_task(profile["display_name"], has_esg=HAS_ESG), required_tools=required, kind="explain_risks")
        st.session_state.history.append(tr)
        st.session_state.explain_turn = tr
    et = st.session_state.explain_turn
    if et is not None:
        current = {t: round(100 * w, 4) for t, w in weights_a.items()}
        if et.context and et.context.get("profile_id") == profile_id and et.context.get("weights_a_pct") == current:
            with st.container(border=True):
                st.markdown("#### Explication de l'assistant IA")
                render_request(et, service, select_profile_cb, profile_id, show_facts=True)
        else:
            st.info("La dernière explication de l'IA concernait un autre profil ou un autre portefeuille. Cliquez à nouveau sur le bouton pour l'actualiser.")

    st.markdown("### Les alertes du Guardian Check")
    st.markdown(persona_sentence(profile) + " (cas officiel du Datathon)")
    st.caption("Chaque carte répond à quatre questions : quel est le problème, quel chiffre l'explique, pourquoi cela compte pour ce profil, et à quel point la vigilance est justifiée.")
    ordered = sorted(cards, key=lambda c: SEVERITY_ORDER[c.status])
    gc = st.columns(2)
    for i, card in enumerate(ordered):
        with gc[i % 2]:
            render_card(card)

    st.markdown("### Les chiffres à connaître")
    st.caption("Mesures historiques calculées par le moteur Python. Elles décrivent le passé et sont identiques quel que soit le profil sélectionné ; "
               "seule leur interprétation change.")
    dd = result.drawdown
    k = st.columns(4)
    k[0].metric("Rendement historique", pct(result.cumulative_return), help=METRIC_HELP["return"], border=True)
    k[0].caption(f"Soit environ {pct(result.annualized_return)} par an en moyenne. Un fait passé, pas une prévision.")
    k[1].metric("Fluctuations du portefeuille", pct(result.volatility), help=METRIC_HELP["volatility"], border=True)
    k[1].caption("Variation typique de la valeur sur un an (volatilité annualisée).")
    k[2].metric("Plus forte baisse historique", pct(dd.max_drawdown), help=METRIC_HELP["drawdown"], border=True)
    k[2].caption(f"Du {fr_date(dd.peak_date)} au {fr_date(dd.trough_date)}.")
    k[3].metric("Répartition de mon portefeuille", f"≈ {fr(result.concentration.effective_n)} positions", help=METRIC_HELP["diversification"], border=True)
    k[3].caption(diversification_sentence(result))
    _fx = fund_exposure(result.weights, service.bundle.universe, result.concentration.max_ticker, result.concentration.max_weight)
    if _fx["has_funds"]:
        k[3].caption(_fx["pedagogical_note"])

    st.markdown("### L'évolution historique")
    t_perf, t_dd = st.tabs(["Évolution de la valeur", "Plus fortes baisses"])
    t_perf.plotly_chart(performance_figure(result), width="stretch")
    t_dd.plotly_chart(drawdown_figure(result), width="stretch")

    if HAS_ESG:
        st.markdown("## B · Mes préférences ESG")
        try:
            esg_view = build_esg_view(service.check_esg(weights_a, profile_id), service.bundle.universe)
            render_esg_section(esg_view)
        except (EsgDataError, PortfolioError, ValueError) as e:
            st.error(f"La vérification ESG est indisponible : {e}")

    with st.expander("Voir plus de statistiques"):
        st.markdown(f"- **Rendement annualisé historique :** {pct(result.annualized_return)} (moyenne géométrique par an, un fait passé)")
        st.markdown(f"- **Plus grande position :** {result.concentration.max_ticker} {pct(result.concentration.max_weight, 0)} · "
                    f"**les 3 plus grandes :** {pct(result.concentration.top3_weight, 0)}")
        st.markdown(f"- **Répartition :** {diversification_sentence(result)} (indice HHI : {fr(result.concentration.hhi, 3)})")
        st.caption(DIVERSIFICATION_HELP)
        st.markdown("- **Classes d'actifs :** " + " · ".join(f"{k_} {pct(v, 0)}" for k_, v in result.class_exposure.items()))
        st.markdown("- **Devises de cotation :** " + " · ".join(f"{k_} {pct(v, 0)}" for k_, v in result.currency_exposure.items()))
        st.markdown(f"- **Plus forte baisse :** sommet {dd.peak_date.date()}, creux {dd.trough_date.date()}, "
                    + (f"récupérée le {dd.recovery_date.date()}" if dd.recovered else "non récupérée à la fin de la période")
                    + f" ({dd.underwater_days} jours calendaires sous le sommet)")
        st.plotly_chart(allocation_figure(result), width="stretch")
        st.dataframe(pd.DataFrame([{"Actif": a.ticker, "Nom": a.name, "Classe": a.asset_class, "Secteur": a.sector, "Part": pct(a.weight),
                                    "Fluctuations annualisées": pct(a.annualized_vol), "Rendement historique": pct(a.cumulative_return),
                                    "Plus forte baisse": pct(a.max_drawdown)} for a in result.assets]), hide_index=True, width="stretch")
        st.caption("Un rendement historique élevé décrit le passé ; il ne signifie pas qu'il se répétera. Biais du survivant : l'univers a été choisi en 2026.")

    with st.expander("Même portefeuille, autre profil : mêmes mesures, niveaux de vigilance différents"):
        reps = {pid: evaluate(result, pid, service.rules_cfg, service.profiles) for pid in PROFILE_IDS}
        table = []
        for f in report.findings:
            if f.status == INFO:
                continue
            row = {"Critère": PLAIN_TITLES[f.rule_id], "Mesure (identique)": f.display["measured"].replace(".", ",")}
            for pid in PROFILE_IDS:
                g = reps[pid].by_id()[f.rule_id]
                row[service.profiles[pid]["display_name"]] = f"{LEVELS[g.status][1]} (repères : {g.display['attention'].replace('.', ',')} ; {g.display['conflict'].replace('.', ',')})"
            table.append(row)
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    with st.expander("Informations manquantes et limites générales"):
        st.markdown("**Informations nécessaires pour une évaluation plus complète :**")
        for x in report.missing_information:
            st.markdown(f"- {x}")
        st.markdown("**Limites générales :**")
        for x in report.general_limitations:
            st.markdown(f"- {x}")
    with st.expander("Profil officiel et préférences"):
        for p_ in profile["preferences"]:
            st.markdown(f"- {p_}")
        st.caption(f"Source : {profile['source']}")

# ----------------------------------------------------------------------------- 3. Comparer deux choix
with tab_cmp:
    st.header("Comparer deux choix")
    st.markdown("Comparez deux façons de répartir votre argent fictif, sur la même période historique.")
    if not use_b:
        st.info("Activez le second portefeuille (B) dans l'onglet « Mon portefeuille » pour comparer deux allocations.")
    else:
        try:
            cmp_ = service.compare(applied_fractions("A"), applied_fractions("B"), profile_id)
        except (PortfolioError, ComparisonError, ConfigError, ValueError) as e:
            st.error(f"Comparaison impossible : {e}")
            cmp_ = None
        if cmp_ is not None:
            a, b = cmp_.a, cmp_.b
            cv = cmp_.conventions
            st.caption(f"**A** : {slot_label('A')} · **B** : {slot_label('B')} · évalués pour **{profile['display_name']}** sur exactement la même période "
                       f"({cv['window']}, {cv['n_observations']} dates communes), en {cv['currency']}, avec le même rééquilibrage mensuel. "
                       "Les écarts décrivent le passé ; aucun portefeuille n'est désigné comme meilleur.")
            st.markdown("### Les compromis à retenir")
            for line in plain_tradeoffs(cmp_):
                st.markdown(f"- {line}")
            ca, cb = cmp_.report_a.counts(), cmp_.report_b.counts()
            st.markdown(f"- Pour {profile['display_name']}, nos critères signalent **{ca[CONFLIT]} risque(s) important(s) et {ca[ATTENTION]} point(s) de vigilance pour A**, "
                        f"contre **{cb[CONFLIT]} et {cb[ATTENTION]} pour B**.")
            st.caption(COMPARE_FOOTER)
            st.caption(COMPARE_SENSITIVITY_NOTE)
            c1, c2 = st.columns(2)
            c1.plotly_chart(comparison_performance_figure(a, b, "A", "B"), width="stretch")
            c2.plotly_chart(comparison_drawdown_figure(a, b, "A", "B"), width="stretch")
            d = cmp_.deltas
            with st.expander("Voir le tableau complet des mesures"):
                rows = [
                    ("Rendement historique (cumulé)", pct(a.cumulative_return), pct(b.cumulative_return), fmt_pts(d["cumulative_return_pts"])),
                    ("Rendement annualisé historique", pct(a.annualized_return), pct(b.annualized_return), fmt_pts(d["annualized_return_pts"])),
                    ("Fluctuations annualisées (volatilité)", pct(a.volatility), pct(b.volatility), fmt_pts(d["annualized_volatility_pts"])),
                    ("Plus forte baisse historique", pct(a.drawdown.max_drawdown), pct(b.drawdown.max_drawdown), fmt_pts(d["max_drawdown_pts"])),
                    ("Plus grande position", f"{a.concentration.max_ticker} {pct(a.concentration.max_weight, 0)}",
                     f"{b.concentration.max_ticker} {pct(b.concentration.max_weight, 0)}", fmt_pts(d["largest_position_weight_pts"])),
                    ("Nombre d'actifs", str(len(a.weights)), str(len(b.weights)), f"{len(b.weights) - len(a.weights):+d}"),
                    ("Positions équivalentes de poids égal", fr(a.concentration.effective_n), fr(b.concentration.effective_n), f"{d['effective_positions']:+.1f}".replace(".", ",")),
                ]
                st.dataframe(pd.DataFrame(rows, columns=["Mesure", "A", "B", "Écart (B − A)"]), hide_index=True, width="stretch")
                st.caption(d["note"])
            with st.expander("Voir la composition des deux portefeuilles"):
                comp = pd.DataFrame({"A (%)": {t: 100 * w for t, w in a.weights.items()}, "B (%)": {t: 100 * w for t, w in b.weights.items()}}).fillna(0.0).round(1)
                cls = pd.DataFrame({"A (%)": {k_: 100 * v for k_, v in a.class_exposure.items()}, "B (%)": {k_: 100 * v for k_, v in b.class_exposure.items()}}).fillna(0.0).round(1)
                cc1, cc2 = st.columns(2)
                cc1.markdown("Par actif")
                cc1.dataframe(comp, width="stretch")
                cc2.markdown("Par classe d'actifs")
                cc2.dataframe(cls, width="stretch")
            _fxa = fund_exposure(cmp_.a.weights, service.bundle.universe, cmp_.a.concentration.max_ticker, cmp_.a.concentration.max_weight)
            _fxb = fund_exposure(cmp_.b.weights, service.bundle.universe, cmp_.b.concentration.max_ticker, cmp_.b.concentration.max_weight)
            if _fxa["has_funds"] or _fxb["has_funds"]:
                st.caption("À propos des FNB : un FNB détient plusieurs titres, donc une part de X % dans un FNB diversifié n'est pas équivalente à X % dans une entreprise "
                           "individuelle. La diversification sous-jacente des FNB n'est pas mesurée ici ; les repères de concentration s'appliquent pourtant de la même façon.")
            with st.expander("Voir les niveaux de vigilance critère par critère"):
                fa, fb = cmp_.report_a.by_id(), cmp_.report_b.by_id()
                gtable = []
                for rid, fa_ in fa.items():
                    if fa_.status == INFO:
                        continue
                    fb_ = fb[rid]
                    gtable.append({"Critère": PLAIN_TITLES[rid], "A : mesure": fa_.display["measured"].replace(".", ","), "A : niveau": LEVELS[fa_.status][1],
                                   "B : mesure": fb_.display["measured"].replace(".", ","), "B : niveau": LEVELS[fb_.status][1]})
                st.dataframe(pd.DataFrame(gtable), hide_index=True, width="stretch")
            if HAS_ESG:
                st.markdown("### Préférences ESG : comparaison (séparée des risques financiers)")
                ea, eb = service.check_esg(applied_fractions("A"), profile_id), service.check_esg(applied_fractions("B"), profile_id)
                st.dataframe(pd.DataFrame([
                    {"": "État global", "A": ea.overall_label, "B": eb.overall_label},
                    {"": "Part cherchée dans nos sources", "A": pct(ea.coverage_checked, 0), "B": pct(eb.coverage_checked, 0)},
                    {"": "Part non évaluable faute de données", "A": pct(ea.weights_by_state.get("INSUFFICIENT", 0.0), 0), "B": pct(eb.weights_by_state.get("INSUFFICIENT", 0.0), 0)},
                    {"": "Informations documentées à examiner (critère lié à la préférence)",
                     "A": "; ".join(f"{c['label']} : {', '.join(c['tickers'])} ({pct(c['weight'], 0)})" for c in ea.categories if c["relevance"] == "direct") or "aucune dans les sources consultées",
                     "B": "; ".join(f"{c['label']} : {', '.join(c['tickers'])} ({pct(c['weight'], 0)})" for c in eb.categories if c["relevance"] == "direct") or "aucune dans les sources consultées"},
                    {"": "Information complémentaire (hors critère déclaré)",
                     "A": "; ".join(f"{c['label']} : {', '.join(c['tickers'])} ({pct(c['weight'], 0)})" for c in ea.categories if c["relevance"] != "direct") or "aucune dans les sources consultées",
                     "B": "; ".join(f"{c['label']} : {', '.join(c['tickers'])} ({pct(c['weight'], 0)})" for c in eb.categories if c["relevance"] != "direct") or "aucune dans les sources consultées"},
                ]), hide_index=True, width="stretch")
                st.caption("Cette comparaison ne désigne aucun portefeuille comme plus « durable » : l'absence d'information documentée n'est pas une preuve de conformité.")
            st.markdown("### Détail des alertes de chaque portefeuille")
            tab_a, tab_b = st.tabs(["Portefeuille A", "Portefeuille B"])
            cards_by = {"A": build_cards(a, cmp_.report_a, profile, service.bundle.universe, service.rules_cfg),
                        "B": build_cards(b, cmp_.report_b, profile, service.bundle.universe, service.rules_cfg)}
            for tab, key in ((tab_a, "A"), (tab_b, "B")):
                with tab:
                    for card in sorted(cards_by[key], key=lambda c: SEVERITY_ORDER[c.status]):
                        render_card(card)

# ----------------------------------------------------------------------------- 4. Assistant IA
with tab_ai:
    st.header("Assistant IA")
    st.markdown("Posez une question sur vos portefeuilles. L'assistant appelle de vrais outils Python pour calculer, puis explique les résultats : "
                f"il n'invente pas de chiffres et ne décide pas à votre place. Profil actuel : **{profile['display_name']}** · "
                f"portefeuille B {'activé' if use_b else 'désactivé'}.")
    st.caption("Chaque question est évaluée seule, avec ses propres appels d'outils.")
    questions = list(SUGGESTED_QUESTIONS) + ([f"{profile['display_name']} veut éviter les entreprises controversées. Ce portefeuille respecte-t-il ses préférences ESG ?"] if HAS_ESG else [])
    qcols = st.columns(len(questions))
    for i, (col, text) in enumerate(zip(qcols, questions)):
        col.button(f"💬 {text}", key=f"suggest_{i}", on_click=set_question_cb, args=(text,))
    with st.form("ask_form", clear_on_submit=False):
        q = st.text_area("Votre question", key="q_text", height=80)
        submitted = st.form_submit_button("Poser la question à l'agent")
    if submitted and q.strip():
        with st.spinner("L'assistant interroge Amazon Bedrock et appelle les outils…"):
            st.session_state.history.append(agent.ask(q.strip()))
    history = st.session_state.history
    if history:
        with st.container(border=True):
            render_request(history[-1], service, select_profile_cb, profile_id)
        older = history[:-1][-5:]
        if older:
            st.markdown(f"#### Requêtes précédentes ({len(history) - 1})")
            for t_ in reversed(older):
                with st.container(border=True):
                    render_request(t_, service, select_profile_cb, profile_id)
        st.caption("Chaque requête n'est validée que par les outils exécutés pendant cette requête. Les réponses rejetées ne sont pas affichées comme des analyses.")

    st.header("Sources, hypothèses et limites")
    t_src, t_hyp, t_lim = st.tabs(["Sources des données", "Hypothèses", "Limites"])
    prov = result.provenance
    with t_src:
        st.dataframe(pd.DataFrame([{"Fichier": n, "Lignes": v["rows"], "Empreinte SHA-256 (12 premiers caractères)": v["sha256"][:12]}
                                   for n, v in prov["data_files"].items()]), hide_index=True, width="stretch")
        if prov["data_manifest_mismatch"]:
            st.warning(f"Empreinte différente de la version auditée : {prov['data_manifest_mismatch']}")
        st.markdown(f"- **Période :** {prov['window']['start']} → {prov['window']['end']} ({prov['window']['n_observations']} dates)")
        st.markdown(f"- **Calendrier :** {prov['calendar_policy']}")
        st.markdown(f"- **Change :** {prov['fx_policy']} ({prov['fx_days_carried_forward_in_window']} date(s) avec taux reporté dans la fenêtre)")
    with t_hyp:
        st.markdown(f"- **Rééquilibrage :** {prov['rebalancing']} ({prov['n_rebalances']} rééquilibrages) · **facteur d'annualisation :** {fr(prov['annualization_factor'], 2)}")
        for x in prov["assumptions"]:
            st.markdown(f"- {x}")
    with t_lim:
        for x in prov["limitations"]:
            st.markdown(f"- {x}")
        st.markdown("- Les repères du Guardian Check sont des heuristiques pédagogiques (voir `config/guardian_rules.yaml`), pas des normes.")
    if agent.tracer.records:
        with st.expander("Exporter la trace technique de toutes les requêtes (JSON)"):
            st.download_button("Télécharger la trace (JSON)", json.dumps(agent.tracer.export(), ensure_ascii=False, indent=2),
                               file_name="trace_investment_guardian.json", mime="application/json")

# ----------------------------------------------------------------------------- barre latérale (simple ; technique replié)
with st.sidebar:
    st.markdown("### 🛡️ Investment Guardian")
    st.markdown(f"**Profil actif :** {profile['display_name']}")
    st.caption(f"Risque {profile['risk_profile_label'].lower()} · horizon {horizon}")
    st.success("Moteur financier : disponible")
    cs = cached_credentials()
    last = st.session_state.history[-1] if st.session_state.history else None
    if last is not None and last.error:
        st.warning("Assistant IA : indisponible lors du dernier essai")
    elif cs["credentials_found"]:
        st.success("Assistant IA : prêt")
    else:
        st.warning("Assistant IA : indisponible (aucun identifiant détecté)")
    st.caption("Simulation éducative : aucun conseil financier personnalisé, aucune transaction.")
    with st.expander("Paramètres avancés et diagnostic technique"):
        st.markdown("**Intégration AWS**")
        st.markdown("Service utilisé : Amazon Bedrock (modèle Amazon Nova 2 Lite), via Strands Agents.")
        st.markdown(f"Identifiant exact du modèle : `{agent.model_id}`")
        st.markdown(f"Région AWS : `{agent.region}`")
        st.markdown("Authentification : " + (AUTH_LABELS.get(cs.get("source"), cs.get("source") or "aucune") if cs["credentials_found"] else "aucune détectée")
                    + " (aucun identifiant n'est affiché ni stocké).")
        n_calls = len(agent.tracer.records)
        st.markdown(f"Cette session : {len(st.session_state.history)} requête(s) à l'assistant, {n_calls} appel(s) d'outil journalisé(s).")
        if st.button("Tester la connexion Bedrock", key="test_bedrock"):
            with st.spinner("Requête minimale…"):
                st.session_state.conn_test = test_bedrock_connection(agent.model_id, agent.region)
        ct = st.session_state.get("conn_test")
        if ct:
            if ct["ok"]:
                st.success("Bedrock répond.")
            else:
                st.error(f"{ct['error']['message']} ({ct['error']['kind']})")
        st.divider()
        st.markdown("**Outils de test**")
        st.checkbox("Simuler une panne de evaluate_portfolio", key="sim_fail_eval",
                    help="Vérifie qu'aucun chiffre non validé n'est présenté si un outil échoue.")
        st.caption("Le moteur et les résultats restent calculés par Python dans tous les cas.")
