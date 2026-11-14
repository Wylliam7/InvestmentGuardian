"""Investment Guardian — V0 (une page). Lancer : voir README / IMPLEMENTATION_PLAN.md."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "src", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import yaml  # noqa: E402

from charts import allocation_figure, drawdown_figure, performance_figure  # noqa: E402
from guardian.agent.agent import GuardianAgent  # noqa: E402
from guardian.agent.aws_status import credentials_status, test_bedrock_connection  # noqa: E402
from guardian.agent.service import GuardianService  # noqa: E402
from guardian.agent.tools import SessionContext  # noqa: E402
from guardian.agent.tracer import Tracer  # noqa: E402
from guardian.data.loader import DataError  # noqa: E402
from guardian.finance.portfolio import PortfolioError, weights_from_percent  # noqa: E402
from guardian.rules.engine import ATTENTION, CONFLIT, OK, ConfigError  # noqa: E402

st.set_page_config(page_title="Investment Guardian", page_icon="🛡️", layout="wide")

STATUS_STYLE = {CONFLIT: ("🔴", "red"), ATTENTION: ("🟠", "orange"), OK: ("🟢", "green")}
SAMPLE_QUESTION = "Pourquoi ce portefeuille pourrait-il être risqué pour Robert ?"

st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.ig-title {font-size: 2.2rem; font-weight: 700; color: #0B3D91; margin-bottom: 0;}
.ig-sub {font-size: 1.05rem; color: #566573; margin-top: 0; font-style: italic;}
.ig-banner {background: #FEF5E7; border-left: 5px solid #D68910; padding: .6rem .9rem; border-radius: 4px; margin: .6rem 0 1rem 0;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Chargement et validation des données officielles…")
def get_service() -> GuardianService:
    return GuardianService.from_default()


def load_preset() -> dict:
    cfg = yaml.safe_load((ROOT / "config" / "presets.yaml").read_text(encoding="utf-8"))
    return cfg["presets"]["robert_nvda_40"]


def fmt_pct(x, digits=1):
    return "n.d." if x is None else f"{100 * x:.{digits}f} %"


# ----------------------------------------------------------------------------- en-tête
st.markdown('<p class="ig-title">🛡️ Investment Guardian</p>', unsafe_allow_html=True)
st.markdown('<p class="ig-sub">Your decisions. Your risks. Explained.</p>', unsafe_allow_html=True)
st.markdown('<div class="ig-banner"><b>Simulation éducative — aucun conseil financier personnalisé.</b> '
            'Aucune transaction réelle. Les résultats décrivent le passé (2021-11-12 au 2026-11-12) et ne prédisent pas l\'avenir.</div>',
            unsafe_allow_html=True)

# ----------------------------------------------------------------------------- données et moteur
try:
    service = get_service()
except (DataError, ConfigError) as e:
    st.error(f"Impossible de charger les données ou la configuration : {e}")
    st.stop()

preset = load_preset()
weights = weights_from_percent(preset["weights_pct"])
profile_id = preset["profile_id"]
profile = service.profiles[profile_id]

try:
    result, report = service.check(weights, profile_id)
except (PortfolioError, ConfigError, ValueError) as e:
    st.error(f"Analyse impossible : {e}")
    st.stop()

# ----------------------------------------------------------------------------- état de session
if "tracer" not in st.session_state:
    st.session_state.tracer = Tracer()
    st.session_state.ctx = SessionContext(weights=weights, profile_id=profile_id)
    st.session_state.agent = GuardianAgent(service, st.session_state.ctx, st.session_state.tracer)
    st.session_state.history = []
agent: GuardianAgent = st.session_state.agent
ctx: SessionContext = st.session_state.ctx

# ----------------------------------------------------------------------------- barre latérale
with st.sidebar:
    st.header("Amazon Bedrock")
    cs = credentials_status()
    st.write(f"Identifiants détectés : **{'oui' if cs['credentials_found'] else 'non'}**"
             + (f" ({cs['source']})" if cs.get("source") else ""))
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
        sim = st.checkbox("Simuler une panne de evaluate_portfolio",
                          help="Vérifie qu'aucun chiffre non validé n'est présenté si un outil échoue.")
        ctx.fail_tools = {"evaluate_portfolio"} if sim else set()
        st.caption("Le moteur et le tableau de bord restent calculés par Python dans tous les cas.")

# ----------------------------------------------------------------------------- profil et portefeuille
c1, c2 = st.columns([1, 1.4])
with c1:
    st.subheader(f"Profil : {profile['display_name']}")
    st.markdown(f"**{profile['age']} ans** · {profile['occupation']} · expérience {profile['experience'].lower()}")
    st.markdown(f"**Risque :** {profile['risk_profile_label']}  \n**Horizon :** {profile['horizon_years_min']} à {profile['horizon_years_max']} ans")
    st.markdown(f"**Objectif :** {profile['objective']}")
    with st.expander("Préférences et contraintes (cas officiel)"):
        for p_ in profile["preferences"]:
            st.markdown(f"- {p_}")
        st.caption(f"Source : {profile['source']}")
with c2:
    st.subheader("Portefeuille fictif")
    st.caption(preset["label"])
    rows = [{"Actif": a.ticker, "Nom": a.name, "Classe": a.asset_class, "Devise": a.currency,
             "Poids": f"{100 * a.weight:.0f} %"} for a in result.assets]
    t1, t2 = st.columns([1.5, 1])
    t1.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    t2.plotly_chart(allocation_figure(result), width="stretch")

# ----------------------------------------------------------------------------- indicateurs (moteur Python)
st.subheader("Indicateurs historiques")
st.caption(f"Calculés par le moteur Python, en CAD, du {result.series.start.date()} au {result.series.end.date()} "
           f"({result.n_obs} dates communes), rééquilibrage mensuel. Simulation historique, pas une prévision.")
k = st.columns(5)
k[0].metric("Rendement cumulé", fmt_pct(result.cumulative_return))
k[1].metric("Rendement annualisé", fmt_pct(result.annualized_return))
k[2].metric("Volatilité annualisée", fmt_pct(result.volatility))
k[3].metric("Drawdown maximal", fmt_pct(result.drawdown.max_drawdown))
k[4].metric("Plus grande position", f"{result.concentration.max_ticker} {fmt_pct(result.concentration.max_weight, 0)}")
k2 = st.columns(5)
k2[0].metric("Top 3 positions", fmt_pct(result.concentration.top3_weight, 0))
k2[1].metric("Indice HHI", f"{result.concentration.hhi:.3f}")
k2[2].metric("Nombre effectif de positions", f"{result.concentration.effective_n:.1f}")
dd = result.drawdown
k2[3].metric("Durée sous l'eau (dd max)", f"{dd.underwater_days} j", help=f"Du sommet {dd.peak_date.date()} "
             + (f"à la récupération {dd.recovery_date.date()}" if dd.recovered else "jusqu'à la fin (non récupéré)"))
k2[4].metric("Exposition par classe", " · ".join(f"{k_} {100 * v:.0f} %" for k_, v in result.class_exposure.items()))

tab_perf, tab_dd = st.tabs(["Performance normalisée", "Drawdown"])
tab_perf.plotly_chart(performance_figure(result), width="stretch")
tab_dd.plotly_chart(drawdown_figure(result), width="stretch")
with st.expander("Statistiques par actif (CAD, même fenêtre)"):
    st.dataframe(pd.DataFrame([{"Actif": a.ticker, "Poids": f"{100 * a.weight:.0f} %",
                                "Volatilité annualisée": fmt_pct(a.annualized_vol), "Rendement cumulé": fmt_pct(a.cumulative_return),
                                "Drawdown max": fmt_pct(a.max_drawdown)} for a in result.assets]),
                 hide_index=True, width="stretch")
    st.caption("Le rendement historique élevé d'un actif décrit le passé ; il ne signifie pas qu'il se répétera. "
               "Biais du survivant : l'univers a été choisi en 2026.")

# ----------------------------------------------------------------------------- Guardian Check
st.subheader("Guardian Check")
cnt = report.counts()
st.caption(f"Règles déterministes en Python, version {report.config_version}. **Les seuils sont des heuristiques "
           f"pédagogiques, pas des normes.** Constats : {cnt[CONFLIT]} conflit(s), {cnt[ATTENTION]} attention(s), {cnt[OK]} conforme(s).")
gc = st.columns(2)
for i, f in enumerate(report.findings):
    icon, color = STATUS_STYLE[f.status]
    with gc[i % 2].container(border=True):
        st.markdown(f"**{f.rule_id} · {f.title}**  \n{icon} :{color}[**{f.status}**]")
        st.markdown(f"Mesuré : **{100 * f.measured:.1f} %** · seuils heuristiques : attention > {100 * f.threshold_attention:.0f} %, "
                    f"conflit > {100 * f.threshold_conflict:.0f} % ({profile['display_name']})")
        with st.expander("Justification, méthode et limites"):
            st.markdown(f"**Justification.** {f.justification}")
            st.markdown(f"**Méthode.** {f.method}")
            if f.rule_id == "R2":
                st.markdown("**Actifs volatils retenus :** " + (", ".join(
                    f"{a['ticker']} ({a['weight_pct']:.0f} %, vol. {a['annualized_volatility_pct']:.1f} %)"
                    for a in f.evidence["volatile_assets"]) or "aucun"))
            st.markdown("**Limites.** " + " ".join(f"• {x}" for x in f.limitations))
            st.caption(f"Règle de type : heuristique · configuration {f.config_version} · nature : règle métier Python (pas une sortie de l'IA)")
with st.expander("Informations manquantes et limites générales"):
    st.markdown("**Informations nécessaires pour une évaluation plus complète :**")
    for x in report.missing_information:
        st.markdown(f"- {x}")
    st.markdown("**Limites générales :**")
    for x in report.general_limitations:
        st.markdown(f"- {x}")

# ----------------------------------------------------------------------------- agent
st.subheader("🤖 AI Guardian")
st.caption("Un agent Strands appelle des outils Python réels via Amazon Bedrock (Nova 2 Lite). "
           "Le texte du modèle est une interprétation ; les chiffres officiels sont ceux du moteur ci-dessus.")
with st.form("ask_form", clear_on_submit=False):
    q = st.text_area("Votre question", value=SAMPLE_QUESTION, height=70)
    submitted = st.form_submit_button("Poser la question à l'agent")
if submitted and q.strip():
    with st.spinner("L'agent interroge Bedrock et appelle les outils…"):
        st.session_state.history.append(agent.ask(q.strip()))

def render_request(t) -> None:
    """Affiche UNE requête utilisateur : son statut dépend uniquement des outils exécutés pendant cette requête."""
    st.markdown(f"**Question :** {t.question}")
    if t.error:
        st.error(f"{t.error['message']}  \nType : `{t.error['kind']}`")
        with st.expander("Détail technique de l'erreur"):
            st.code(t.error["detail"])
        st.info("Le moteur financier reste disponible : les indicateurs et le Guardian Check ci-dessus sont calculés sans AWS.")
    elif t.withheld:
        st.warning(f"**Analyse incomplète.** {t.withheld_reason}")
        st.info("Les indicateurs et le Guardian Check ci-dessus restent valides : ils proviennent du moteur Python.")
    else:
        if t.caveat:
            st.warning(t.caveat)
        st.markdown("**Interprétation générée par l'IA** (Nova 2 Lite) — à lire avec les résultats chiffrés et les constats ci-dessus :")
        st.markdown(t.text)
    n_ok = sum(1 for r in t.tool_records if r.status == "ok")
    st.caption(f"Requête n° {t.turn} · {len(t.tool_records)} appel(s) d'outil dans cette requête ({n_ok} réussi(s)) · "
               f"{t.cycles if t.cycles is not None else '?'} cycle(s) interne(s) du modèle · {t.duration_s} s · "
               f"jetons : {t.usage.get('inputTokens', '?')} entrée / {t.usage.get('outputTokens', '?')} sortie · "
               f"modèle {t.model_id} · {t.region}")


history = st.session_state.history
if history:
    with st.container(border=True):
        render_request(history[-1])
    if len(history) > 1:
        with st.expander(f"Requêtes précédentes ({len(history) - 1})"):
            for older in reversed(history[:-1]):
                with st.container(border=True):
                    render_request(older)
    st.caption("Chaque requête est évaluée seule : elle n'est validée que par les outils exécutés pendant cette requête.")

# ----------------------------------------------------------------------------- explicabilité
st.subheader("Explicabilité")
tab_trace, tab_src, tab_lim = st.tabs(["Trace des outils (réelle)", "Sources et hypothèses", "Limites"])
with tab_trace:
    st.caption("Journal écrit par notre code à chaque exécution d'outil. Il ne provient pas du modèle.")
    recs = agent.tracer.records
    if not recs:
        st.info("Aucun outil appelé pour l'instant. Posez une question à l'agent.")
    for r in reversed(recs):
        icon = "✅" if r.status == "ok" else "❌"
        with st.expander(f"{icon} #{r.id} · requête {r.turn} · {r.tool} · {r.duration_ms} ms"):
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
with tab_src:
    prov = result.provenance
    st.markdown("**Fichiers utilisés (lecture seule) :**")
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
with tab_lim:
    for x in result.provenance["limitations"]:
        st.markdown(f"- {x}")
    st.markdown("- Les seuils du Guardian Check sont des heuristiques de démonstration (voir `config/guardian_rules.yaml`).")
