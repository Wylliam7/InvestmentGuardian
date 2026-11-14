"""Investment Guardian — V1. Quatre vues : Portfolio Builder, Risk Dashboard, Comparaison A/B, AI Guardian & Explicabilité."""
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

from profile_flow import loadable, matches_suggestion, plan_switch, slot_status  # noqa: E402
from charts import (allocation_figure, comparison_drawdown_figure, comparison_performance_figure,  # noqa: E402
                    drawdown_figure, performance_figure)
from guardian.agent.agent import GuardianAgent  # noqa: E402
from guardian.agent.aws_status import credentials_status, test_bedrock_connection  # noqa: E402
from guardian.agent.service import GuardianService  # noqa: E402
from guardian.agent.tools import SessionContext  # noqa: E402
from guardian.agent.tracer import Tracer  # noqa: E402
from guardian.data.loader import DataError  # noqa: E402
from guardian.finance.builder import normalize_to_100, parse_weight_rows, rows_from_weights  # noqa: E402
from guardian.finance.compare import ComparisonError  # noqa: E402
from guardian.finance.portfolio import PortfolioError  # noqa: E402
from guardian.finance.presets import (PresetError, load_presets, load_profile_defaults, validate_presets,  # noqa: E402
                                      validate_profile_defaults)
from guardian.rules.engine import ATTENTION, CONFLIT, INFO, OK, STATUS_LABELS, ConfigError, evaluate  # noqa: E402

st.set_page_config(page_title="Investment Guardian", page_icon="🛡️", layout="wide")

STATUS_STYLE = {CONFLIT: ("🔴", "red"), ATTENTION: ("🟠", "orange"), OK: ("🟢", "green"), INFO: ("🔵", "blue")}
SAMPLE_QUESTION = ("Pour ce profil, compare le portefeuille A avec le portefeuille B. "
                   "Quels compromis historiques observes-tu ?")

st.markdown("""
<style>
.block-container {padding-top: 1.4rem; padding-left: 2.2rem; padding-right: 2.2rem; max-width: 100%;}
h1 {font-size: 3.4rem !important; font-weight: 800 !important; line-height: 1.1 !important; margin-bottom: .1rem !important;}
h2, h3 {margin-top: 1.1rem !important;}
.ig-sub {font-size: 1.35rem; font-style: italic; margin: 0 0 .9rem 0; opacity: .85;}
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
st.markdown('<p class="ig-sub">Your decisions. Your risks. Explained.</p>', unsafe_allow_html=True)
st.markdown('<div class="ig-banner"><b>Simulation éducative — aucun conseil financier personnalisé.</b> '
            "Aucune transaction réelle. Les résultats décrivent le passé (2021-11-12 au 2026-11-12) et ne prédisent pas l'avenir. "
            "Les seuils du Guardian Check sont des heuristiques du prototype, pas des normes.</div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- données et moteur
@st.cache_resource(show_spinner="Chargement et validation des données officielles…")
def get_service() -> GuardianService:
    return GuardianService.from_default()


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


def fmt_pct(x, digits=1):
    return "n.d." if x is None else f"{100 * x:.{digits}f} %"


def fmt_signed_pts(x):
    return "n.d." if x is None else f"{x:+.1f} pts"


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
    st.session_state.profile_notice = None      # {"kind": "auto"|"suggest", "profile": id}
    st.session_state.prev_slots = None

slots = st.session_state.slots
ctx: SessionContext = st.session_state.ctx
agent: GuardianAgent = st.session_state.agent


def load_preset_cb(key: str) -> None:
    """Choix explicite d'un préréglage par l'utilisateur."""
    pid = st.session_state[f"preset_{key}"]
    st.session_state.touched = True
    st.session_state.profile_notice = None
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
    st.session_state.profile_notice = {"kind": "loaded", "profile": new, "kept": [k for k in ("A", "B") if k not in targets]}


def revert_slots_cb() -> None:
    if st.session_state.prev_slots:
        for k in ("A", "B"):
            old = st.session_state.prev_slots[k]
            old["ver"] = slots[k]["ver"] + 1
            slots[k] = old
        st.session_state.prev_slots = None
        st.session_state.touched = True
        st.session_state.profile_notice = None


def select_profile_cb(pid: str) -> None:
    st.session_state.profile_id = pid
    on_profile_change()


def applied_fractions(key: str) -> dict:
    return {t: w / 100.0 for t, w in slots[key]["applied_pct"].items()}


def slot_label(key: str) -> str:
    pid = slots[key]["preset"]
    return PRESETS[pid]["label"] if pid in PRESETS and PRESETS[pid]["weights_pct"] == slots[key]["applied_pct"] else "Portefeuille personnalisé"


# ----------------------------------------------------------------------------- sélection du profil
top1, top2 = st.columns([1, 3])
profile_id = top1.selectbox("Profil de l'investisseur", PROFILE_IDS, key="profile_id", on_change=on_profile_change,
                            format_func=lambda p: service.profiles[p]["display_name"])
profile = service.profiles[profile_id]
hz_max = profile.get("horizon_years_max")
horizon = f"{profile['horizon_years_min']} à {hz_max} ans" if hz_max else f"{profile['horizon_years_min']} ans ou plus"
top2.markdown(f"**{profile['display_name']}** · {profile['age']} ans · {profile['occupation']} · risque **{profile['risk_profile_label'].lower()}** · "
              f"horizon **{horizon}**  \n**Objectif :** {profile['objective']}")

notice = st.session_state.profile_notice
if notice and notice["profile"] == profile_id:
    d = DEFAULTS[profile_id]
    names = f"A = {PRESETS[d['a']]['label']} ; B = {PRESETS[d['b']]['label']}"
    if notice["kind"] == "auto":
        st.info(f"Scénarios par défaut de **{profile['display_name']}** chargés (vous n'aviez encore rien modifié) : {names}. "
                "Vous pouvez évaluer n'importe quelle allocation pour ce profil en la choisissant dans « Portfolio Builder ».")
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

# ----------------------------------------------------------------------------- barre latérale
with st.sidebar:
    st.header("Amazon Bedrock")
    cs = credentials_status()
    st.write(f"Identifiants détectés : **{'oui' if cs['credentials_found'] else 'non'}**" + (f" ({cs['source']})" if cs.get("source") else ""))
    st.write(f"Modèle : `{agent.model_id}`")
    st.write(f"Région : `{agent.region}`")
    st.caption("Aucun secret n'est affiché ni stocké. Les identifiants viennent de la chaîne AWS standard.")
    if st.button("Tester la connexion Bedrock"):
        with st.spinner("Requête minimale…"):
            st.session_state.conn_test = test_bedrock_connection(agent.model_id, agent.region)
    ct = st.session_state.get("conn_test")
    if ct:
        if ct["ok"]:
            st.success("Bedrock répond.")
        else:
            st.error(f"{ct['error']['message']} ({ct['error']['kind']})")
    st.divider()
    with st.expander("Outils de test"):
        sim = st.checkbox("Simuler une panne de evaluate_portfolio", help="Vérifie qu'aucun chiffre non validé n'est présenté si un outil échoue.")
        ctx.fail_tools = {"evaluate_portfolio"} if sim else set()
        st.caption("Le moteur et le tableau de bord restent calculés par Python dans tous les cas.")

tab_build, tab_dash, tab_cmp, tab_ai = st.tabs(["1 · Portfolio Builder", "2 · Risk Dashboard", "3 · Comparaison A/B",
                                                 "4 · AI Guardian & Explicabilité"])


# ----------------------------------------------------------------------------- 1. Portfolio Builder
def portfolio_editor(key: str, title: str) -> None:
    slot = slots[key]
    st.subheader(title)
    mine = [p for p in PRESETS if PRESETS[p]["profile_id"] == profile_id]       # scénarios du profil sélectionné, proposés en premier
    options = mine + [p for p in PRESETS if p not in mine] + ["custom"]
    st.session_state[f"preset_{key}"] = slot["preset"] if slot["preset"] in options else "custom"
    st.selectbox("Portefeuille prédéfini (★ = scénario du profil sélectionné)", options, key=f"preset_{key}", on_change=load_preset_cb, args=(key,),
                 format_func=lambda p: "Personnalisé" if p == "custom" else ("★ " if p in mine else "") + PRESETS[p]["label"])
    if slot["preset"] in PRESETS:
        st.caption(" ".join(PRESETS[slot["preset"]]["description"].split()))
    if slot.get("msg"):
        st.info(slot["msg"])
    edited = st.data_editor(
        slot["df"], key=f"editor_{key}_{slot['ver']}", num_rows="dynamic", hide_index=True, width="stretch",
        column_config={"ticker": st.column_config.SelectboxColumn("Actif", options=UNIVERSE, help="Actifs de l'univers officiel (31)."),
                       "weight_pct": st.column_config.NumberColumn("Poids (%)", step=0.5, format="%.2f")})
    rows = [{"ticker": r["ticker"], "weight_pct": r["weight_pct"]} for r in edited.to_dict("records")]
    res = parse_weight_rows(rows, service.bundle.universe.index)
    slot["dirty"] = not (res.valid and res.weights_pct == slot["applied_pct"])      # saisie différente des poids analysés
    st.metric("Somme des poids saisis", f"{res.total_pct:.2f} %", delta=f"{res.total_pct - 100:+.2f} pts vs 100 %" if abs(res.total_pct - 100) > 0.005 else "100 %",
              delta_color="off" if abs(res.total_pct - 100) <= 0.005 else "inverse")
    for err in res.errors:
        st.error(err)
    if res.valid:
        st.success("Poids valides : actifs connus, aucun doublon, aucun poids négatif, somme = 100 %.")
    c1, c2 = st.columns(2)
    if c1.button("Analyser ce portefeuille", key=f"apply_{key}", disabled=not res.valid, type="primary"):
        st.session_state.touched = True
        st.session_state.profile_notice = None
        slot["applied_pct"] = dict(res.weights_pct)
        slot["preset"] = next((p for p, v in PRESETS.items() if v["weights_pct"] == slot["applied_pct"]), "custom")
        slot["msg"] = None
        st.rerun()
    if res.only_sum_is_wrong and c2.button("Normaliser à 100 % (proportionnel)", key=f"norm_{key}",
                                           help="Action explicite : chaque poids est multiplié par 100 / somme. Rien n'est modifié sans ce clic."):
        st.session_state.touched = True
        slot["df"] = pd.DataFrame(rows_from_weights(normalize_to_100(res.rows_seen)))
        slot["ver"] += 1
        slot["msg"] = "Poids normalisés à 100 % à votre demande (proportionnellement). Cliquez sur « Analyser » pour les appliquer."
        st.rerun()
    pending = res.valid and res.weights_pct != slot["applied_pct"]
    if pending:
        st.warning("Modifications non appliquées : l'analyse utilise encore les poids ci-dessous. Cliquez sur « Analyser ».")
    st.markdown("**Poids réellement analysés :** " + " · ".join(f"{t} {w:g} %" for t, w in slot["applied_pct"].items()))


with tab_build:
    st.caption("Choisissez un portefeuille fictif prédéfini, ajoutez ou retirez des lignes, modifiez les poids, puis cliquez sur « Analyser ». "
               "Long seulement, sans levier. Les poids saisis ne sont jamais modifiés sans votre action explicite.")
    st.checkbox("Activer le portefeuille B (comparaison A/B)", key="use_b")
    use_b = st.session_state.use_b
    ctx.weights_b = applied_fractions("B") if use_b else None
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


def render_findings(rep, cols=2) -> None:
    gc = st.columns(cols)
    for i, f in enumerate(rep.findings):
        icon, color = STATUS_STYLE[f.status]
        with gc[i % cols].container(border=True):
            st.markdown(f"**{f.rule_id} · {f.title}**  \n{icon} :{color}[**{f.status_label}**]")
            if f.status == INFO:
                st.markdown(f.summary)
            else:
                st.markdown(f"Mesuré : **{f.display['measured']}** · seuils heuristiques : attention {f.display['attention']}, conflit {f.display['conflict']}")
                st.caption(f.display["phrase"])
            with st.expander("Explication, méthode et limites"):
                st.markdown(f"**Justification.** {f.justification}")
                st.markdown(f"**Méthode.** {f.method}")
                if f.rule_id == "R2":
                    st.markdown("**Actifs volatils retenus :** " + (", ".join(
                        f"{a['ticker']} ({a['weight_pct']:.0f} %, vol. {a['annualized_volatility_pct']:.1f} %)" for a in f.evidence["volatile_assets"]) or "aucun"))
                st.markdown("**Limites.** " + " ".join(f"• {x}" for x in f.limitations))
                st.caption(f"Nature : règle métier Python déterministe, heuristique, configuration {f.config_version}. Ce n'est pas une sortie de l'IA.")


# ----------------------------------------------------------------------------- 2. Risk Dashboard
with tab_dash:
    st.subheader(f"Portefeuille A — {slot_label('A')}")
    st.caption(f"Évalué pour **{profile['display_name']}**. Mesures calculées par le moteur Python, en CAD, du {result.series.start.date()} au "
               f"{result.series.end.date()} ({result.n_obs} dates communes), rééquilibrage mensuel. Les mesures sont identiques quel que soit le profil ; "
               "seuls les constats Guardian changent.")
    k = st.columns(4)
    k[0].metric("Rendement cumulé", fmt_pct(result.cumulative_return), border=True)
    k[1].metric("Rendement annualisé", fmt_pct(result.annualized_return), border=True)
    k[2].metric("Volatilité annualisée", fmt_pct(result.volatility), border=True)
    k[3].metric("Drawdown maximal", fmt_pct(result.drawdown.max_drawdown), border=True)
    dd = result.drawdown
    with st.expander("Concentration et expositions"):
        st.markdown(f"- **Plus grande position :** {result.concentration.max_ticker} {fmt_pct(result.concentration.max_weight, 0)} · "
                    f"**3 plus grandes :** {fmt_pct(result.concentration.top3_weight, 0)}\n"
                    f"- **HHI :** {result.concentration.hhi:.3f} · **nombre effectif de positions :** {result.concentration.effective_n:.1f}\n"
                    f"- **Classes d'actifs :** " + " · ".join(f"{k_} {100 * v:.0f} %" for k_, v in result.class_exposure.items()) + "\n"
                    f"- **Devises de cotation :** " + " · ".join(f"{k_} {100 * v:.0f} %" for k_, v in result.currency_exposure.items()) + "\n"
                    f"- **Drawdown maximal :** sommet {dd.peak_date.date()}, creux {dd.trough_date.date()}, "
                    + (f"récupéré le {dd.recovery_date.date()}" if dd.recovered else "non récupéré à la fin de la période")
                    + f" ({dd.underwater_days} jours calendaires sous l'eau)")
        st.plotly_chart(allocation_figure(result), width="stretch")
    t_perf, t_dd = st.tabs(["Performance normalisée", "Drawdown"])
    t_perf.plotly_chart(performance_figure(result), width="stretch")
    t_dd.plotly_chart(drawdown_figure(result), width="stretch")
    with st.expander("Statistiques par actif (CAD, même fenêtre)"):
        st.dataframe(pd.DataFrame([{"Actif": a.ticker, "Classe": a.asset_class, "Secteur": a.sector, "Poids": f"{100 * a.weight:.1f} %",
                                    "Volatilité annualisée": fmt_pct(a.annualized_vol), "Rendement cumulé": fmt_pct(a.cumulative_return),
                                    "Drawdown max": fmt_pct(a.max_drawdown)} for a in result.assets]), hide_index=True, width="stretch")
        st.caption("Un rendement historique élevé décrit le passé ; il ne signifie pas qu'il se répétera. Biais du survivant : l'univers a été choisi en 2026.")

    st.subheader("Guardian Check")
    cnt = report.counts()
    st.markdown(f"Selon les **seuils heuristiques du prototype** (pas des normes), le portefeuille A présente **{cnt[CONFLIT]} conflit(s) potentiel(s)** "
                f"et **{cnt[ATTENTION]} point(s) d'attention** par rapport aux objectifs déclarés de {profile['display_name']} ; "
                f"{cnt[OK]} contrôle(s) conforme(s). Un conflit potentiel n'est pas une conclusion absolue : il ne présume pas de la tolérance personnelle réelle.")
    render_findings(report)
    with st.expander("Même portefeuille, autre profil : mesures identiques, statuts selon les seuils de chaque profil"):
        reps = {pid: evaluate(result, pid, service.rules_cfg, service.profiles) for pid in PROFILE_IDS}
        table = []
        for f in report.findings:
            if f.status == INFO:
                continue
            row = {"Règle": f"{f.rule_id} · {f.title}", "Mesure (identique)": f.display["measured"]}
            for pid in PROFILE_IDS:
                g = reps[pid].by_id()[f.rule_id]
                row[service.profiles[pid]["display_name"]] = f"{STATUS_STYLE[g.status][0]} {g.status_label} (attention {g.display['attention']} ; conflit {g.display['conflict']})"
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

# ----------------------------------------------------------------------------- 3. Comparaison A/B
with tab_cmp:
    if not use_b:
        st.info("Activez le portefeuille B dans l'onglet « Portfolio Builder » pour comparer deux allocations.")
    else:
        try:
            cmp_ = service.compare(applied_fractions("A"), applied_fractions("B"), profile_id)
        except (PortfolioError, ComparisonError, ConfigError, ValueError) as e:
            st.error(f"Comparaison impossible : {e}")
            cmp_ = None
        if cmp_ is not None:
            a, b = cmp_.a, cmp_.b
            la, lb = slot_label("A"), slot_label("B")
            st.subheader("Comparaison A/B")
            cv = cmp_.conventions
            st.caption(f"**A** : {la} · **B** : {lb} · évalués pour **{profile['display_name']}** sur exactement la même période "
                       f"({cv['window']}, {cv['n_observations']} dates communes), en {cv['currency']}, rééquilibrage {cv['rebalancing']}, mêmes données. "
                       "Les écarts décrivent le passé ; aucun portefeuille n'est désigné comme meilleur.")
            d = cmp_.deltas
            rows = [
                ("Rendement cumulé historique", fmt_pct(a.cumulative_return), fmt_pct(b.cumulative_return), fmt_signed_pts(d["cumulative_return_pts"])),
                ("Rendement annualisé historique", fmt_pct(a.annualized_return), fmt_pct(b.annualized_return), fmt_signed_pts(d["annualized_return_pts"])),
                ("Volatilité annualisée", fmt_pct(a.volatility), fmt_pct(b.volatility), fmt_signed_pts(d["annualized_volatility_pts"])),
                ("Drawdown maximal", fmt_pct(a.drawdown.max_drawdown), fmt_pct(b.drawdown.max_drawdown), fmt_signed_pts(d["max_drawdown_pts"])),
                ("Plus grande position", f"{a.concentration.max_ticker} {fmt_pct(a.concentration.max_weight, 0)}",
                 f"{b.concentration.max_ticker} {fmt_pct(b.concentration.max_weight, 0)}", fmt_signed_pts(d["largest_position_weight_pts"])),
                ("Nombre effectif de positions", f"{a.concentration.effective_n:.1f}", f"{b.concentration.effective_n:.1f}", f"{d['effective_positions']:+.1f}"),
            ]
            st.dataframe(pd.DataFrame(rows, columns=["Mesure", "A", "B", "Écart (B − A)"]), hide_index=True, width="stretch")
            st.caption(d["note"])
            c1, c2 = st.columns(2)
            c1.plotly_chart(comparison_performance_figure(a, b, "A", "B"), width="stretch")
            c2.plotly_chart(comparison_drawdown_figure(a, b, "A", "B"), width="stretch")
            st.markdown("**Compromis historiques observés (sans verdict)**")
            for t_ in cmp_.tradeoffs:
                st.markdown(f"- {t_}")
            st.markdown("**Composition**")
            comp = pd.DataFrame({"A (%)": {t: 100 * w for t, w in a.weights.items()}, "B (%)": {t: 100 * w for t, w in b.weights.items()}}).fillna(0.0).round(1)
            cls = pd.DataFrame({"A (%)": {k_: 100 * v for k_, v in a.class_exposure.items()}, "B (%)": {k_: 100 * v for k_, v in b.class_exposure.items()}}).fillna(0.0).round(1)
            cc1, cc2 = st.columns(2)
            cc1.markdown("Par actif")
            cc1.dataframe(comp, width="stretch")
            cc2.markdown("Par classe d'actifs")
            cc2.dataframe(cls, width="stretch")
            st.markdown(f"**Constats Guardian pour {profile['display_name']}** (seuils heuristiques)")
            fa, fb = cmp_.report_a.by_id(), cmp_.report_b.by_id()
            gtable = []
            for rid, fa_ in fa.items():
                if fa_.status == INFO:
                    continue
                fb_ = fb[rid]
                gtable.append({"Règle": f"{rid} · {fa_.title}", "A : mesuré": fa_.display["measured"], "A : statut": f"{STATUS_STYLE[fa_.status][0]} {fa_.status_label}",
                               "B : mesuré": fb_.display["measured"], "B : statut": f"{STATUS_STYLE[fb_.status][0]} {fb_.status_label}",
                               "Seuils (attention ; conflit)": f"{fa_.display['attention']} ; {fa_.display['conflict']}"})
            st.dataframe(pd.DataFrame(gtable), hide_index=True, width="stretch")
            with st.expander("Détail des constats par portefeuille"):
                ga, gb = st.columns(2)
                with ga:
                    st.markdown("**Portefeuille A**")
                    render_findings(cmp_.report_a, cols=1)
                with gb:
                    st.markdown("**Portefeuille B**")
                    render_findings(cmp_.report_b, cols=1)

# ----------------------------------------------------------------------------- 4. AI Guardian & Explicabilité
def render_tools_used(t) -> None:
    """Preuve visible des outils réellement exécutés pendant CETTE requête (issue du journal, pas du modèle)."""
    st.markdown("**Outils exécutés pendant cette requête (trace réelle)**")
    recs = sorted(t.tool_records, key=lambda r: r.id)
    if not recs:
        st.caption("Aucun outil n'a été appelé pendant cette requête.")
    for r in recs:
        icon = "✅" if r.status == "ok" else "❌"
        args = ", ".join(f"{k}={v!r}" for k, v in r.arguments.items() if v not in ("", None)) or "aucun argument"
        st.markdown(f"{icon} `{r.tool}` · appel n° {r.id} · {r.duration_ms} ms · {args}" + (f" · **erreur** : {r.error}" if r.error else ""))
    cmp_calls = [r for r in recs if r.tool == "compare_scenarios"]
    if any(r.status == "ok" for r in cmp_calls):
        ok = next(r for r in cmp_calls if r.status == "ok")
        st.success(f"compare_scenarios : appelé avec succès (appel n° {ok.id}). Son résultat complet est dans la trace ci-dessous.")
    elif cmp_calls:
        st.error("compare_scenarios : appelé mais en échec (voir ci-dessus).")
    else:
        st.caption("compare_scenarios : non appelé pendant cette requête"
                   + ("." if (t.context or {}).get("weights_b_pct") else " (aucun portefeuille B n'était sélectionné)."))
    st.caption("Pour ouvrir la trace détaillée : descendez à « Explicabilité » → onglet « Trace des outils (réelle) » → cliquez sur la ligne "
               f"correspondant à la requête {t.turn} (arguments, références aux données, résultat retourné).")


def render_request(t) -> None:
    """Affiche UNE requête utilisateur : son statut dépend uniquement des outils exécutés pendant cette requête."""
    st.markdown(f"**Question :** {t.question}")
    if t.context:
        wa = ", ".join(f"{k_} {v:g} %" for k_, v in (t.context["weights_a_pct"] or {}).items())
        wb = ", ".join(f"{k_} {v:g} %" for k_, v in (t.context["weights_b_pct"] or {}).items()) or "aucun"
        st.caption(f"Contexte de cette requête : profil {t.context['profile_id']} · A = {wa} · B = {wb}")
    if t.clarification:
        st.warning(t.clarification)
        cols = st.columns(max(1, len(t.clarification_profiles)))
        for col, pid in zip(cols, t.clarification_profiles):
            col.button(f"Sélectionner {service.profiles[pid]['display_name']}", key=f"selprof_{t.turn}_{pid}",
                       on_click=select_profile_cb, args=(pid,))
        st.caption(f"Requête n° {t.turn} · 0 appel d'outil · aucun appel au modèle (précision demandée avant toute analyse).")
        return
    if t.error:
        st.error(f"{t.error['message']}  \nType : `{t.error['kind']}`")
        with st.expander("Détail technique de l'erreur"):
            st.code(t.error["detail"])
        st.info("Le moteur financier reste disponible : les indicateurs et le Guardian Check sont calculés sans AWS.")
    elif t.withheld:
        st.warning(f"**Analyse incomplète.** {t.withheld_reason}")
        st.info("Les indicateurs et le Guardian Check des autres onglets restent valides : ils proviennent du moteur Python.")
    else:
        if t.caveat:
            st.warning(t.caveat)
        st.markdown("**Interprétation générée par l'IA** (Nova 2 Lite). Les faits chiffrés proviennent des outils Python (voir la trace) ; "
                    "les formulations et l'interprétation sont celles du modèle :")
        st.markdown(t.text)
    render_tools_used(t)
    n_ok = sum(1 for r in t.tool_records if r.status == "ok")
    st.caption(f"Requête n° {t.turn} · {len(t.tool_records)} appel(s) d'outil dans cette requête ({n_ok} réussi(s)) · "
               f"{t.cycles if t.cycles is not None else '?'} cycle(s) interne(s) du modèle · {t.duration_s} s · "
               f"jetons : {t.usage.get('inputTokens', '?')} entrée / {t.usage.get('outputTokens', '?')} sortie · modèle {t.model_id} · {t.region}")


with tab_ai:
    st.subheader("🤖 AI Guardian")
    st.caption("Un agent Strands appelle des outils Python réels via Amazon Bedrock (Nova 2 Lite). Il analyse les portefeuilles réellement sélectionnés "
               f"dans l'interface (profil : {profile['display_name']} ; B {'activé' if use_b else 'désactivé'}). Chaque question est évaluée seule, avec ses propres appels d'outils.")
    with st.form("ask_form", clear_on_submit=False):
        q = st.text_area("Votre question", value=SAMPLE_QUESTION, height=80)
        submitted = st.form_submit_button("Poser la question à l'agent")
    if submitted and q.strip():
        with st.spinner("L'agent interroge Bedrock et appelle les outils…"):
            st.session_state.history.append(agent.ask(q.strip()))
    history = st.session_state.history
    if history:
        with st.container(border=True):
            render_request(history[-1])
        if len(history) > 1:
            with st.expander(f"Requêtes précédentes ({len(history) - 1})"):
                for older in reversed(history[:-1]):
                    with st.container(border=True):
                        render_request(older)
        st.caption("Chaque requête n'est validée que par les outils exécutés pendant cette requête. Les réponses rejetées ne sont pas affichées comme des analyses.")

    st.subheader("Explicabilité")
    t_trace, t_src, t_lim = st.tabs(["Trace des outils (réelle)", "Sources et hypothèses", "Limites"])
    with t_trace:
        st.caption("Journal écrit par notre code à chaque exécution d'outil. Il ne provient pas du modèle.")
        recs = agent.tracer.records
        if not recs:
            st.info("Aucun outil appelé pour l'instant. Posez une question à l'agent.")
        last_turn = max((r.turn for r in recs), default=0)
        for r in reversed(recs):
            icon = "✅" if r.status == "ok" else "❌"
            with st.expander(f"{icon} #{r.id} · requête {r.turn} · {r.tool} · {r.duration_ms} ms", expanded=(r.turn == last_turn and r.tool == "compare_scenarios")):
                st.markdown(f"**Statut :** {r.status} · **Début (UTC) :** {r.started_at} · **Empreinte du résultat :** `{r.result_digest}`")
                st.markdown("**Arguments**")
                st.json(r.arguments)
                if r.error:
                    st.error(r.error)
                else:
                    st.markdown("**Références aux données**")
                    st.json(r.data_refs)
                    st.markdown("**Résultat retourné à l'agent**")
                    st.json(r.result, expanded=False)
        if recs:
            st.download_button("Exporter la trace (JSON)", json.dumps(agent.tracer.export(), ensure_ascii=False, indent=2),
                               file_name="trace_investment_guardian.json", mime="application/json")
    with t_src:
        prov = result.provenance
        st.dataframe(pd.DataFrame([{"Fichier": n, "Lignes": v["rows"], "SHA-256 (12 premiers)": v["sha256"][:12]}
                                   for n, v in prov["data_files"].items()]), hide_index=True, width="stretch")
        if prov["data_manifest_mismatch"]:
            st.warning(f"Empreinte différente de la version auditée : {prov['data_manifest_mismatch']}")
        st.markdown(f"- **Période :** {prov['window']['start']} → {prov['window']['end']} ({prov['window']['n_observations']} dates)")
        st.markdown(f"- **Calendrier :** {prov['calendar_policy']}")
        st.markdown(f"- **Change :** {prov['fx_policy']} ({prov['fx_days_carried_forward_in_window']} date(s) avec taux reporté dans la fenêtre)")
        st.markdown(f"- **Rééquilibrage :** {prov['rebalancing']} ({prov['n_rebalances']} rééquilibrages) · **facteur d'annualisation :** {prov['annualization_factor']}")
        st.markdown("**Hypothèses :**")
        for x in prov["assumptions"]:
            st.markdown(f"- {x}")
    with t_lim:
        for x in result.provenance["limitations"]:
            st.markdown(f"- {x}")
        st.markdown("- Les seuils du Guardian Check sont des heuristiques de démonstration (voir `config/guardian_rules.yaml`).")
