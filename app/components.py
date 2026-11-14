"""Composants d'affichage Streamlit de V2 (aucun calcul financier : tout vient du moteur et des modules `explain`)."""
from __future__ import annotations

import streamlit as st

from guardian.explain.cards import Card
from guardian.explain.format import fr, pct, pct_value
from guardian.explain.summary import PrioritySummary
from guardian.explain.trace_view import summary_lines

LEVEL_STYLE = {"important": ("🔴", "red"), "vigilance": ("🟠", "orange"), "ok": ("🟢", "green"), "info": ("🔵", "blue")}


# ----------------------------------------------------------------------------- Guardian Check
def render_card(card: Card) -> None:
    icon, color = LEVEL_STYLE[card.level_kind]
    with st.container(border=True):
        st.markdown(f"{icon} :{color}[**{card.level_label}**]")
        st.markdown(f"#### {card.headline}")
        st.markdown(card.measure)
        st.markdown(card.why)
        st.caption(card.precision)
        with st.expander("Comprendre ce calcul"):
            st.markdown(f"**Comment ce résultat est obtenu.** {card.how}")
            st.markdown("**Ce qu'il faut garder en tête.**")
            for lim in card.limits:
                st.markdown(f"- {lim}")
        with st.expander("Détails techniques (règle, seuils, version)"):
            a = card.advanced
            st.markdown(f"**{a['Règle']}** · statut interne : `{a['Statut interne']}` · valeur mesurée : {a['Valeur mesurée'] or 'n.d.'} · seuils heuristiques : {a['Seuils heuristiques']}")
            st.markdown(f"**Méthode.** {a['Méthode (technique)']}")
            st.markdown(f"**Justification.** {a['Justification (configuration)']}")
            st.markdown("**Limites (configuration).** " + " ".join(f"• {x}" for x in a["Limites (configuration)"]))
            st.caption(f"{a['Nature']} Configuration {a['Version de la configuration']}.")


def render_summary(s: PrioritySummary) -> None:
    with st.container(border=True):
        st.markdown("### À retenir en priorité")
        if s.items:
            st.markdown(s.intro)
            for it in s.items:
                st.markdown(f"- {it.text[0].upper() + it.text[1:]}")
        else:
            st.markdown(s.sentence)
        if s.related_note:
            st.caption(s.related_note)
        st.caption("Résumé généré automatiquement à partir des critères calculés (sans IA). Le détail de chaque critère est plus bas.")


# ----------------------------------------------------------------------------- traçabilité
def render_tools_technical(t) -> None:
    """Niveau 2 : détails techniques complets (noms exacts, arguments JSON, statut, durée, empreintes, résultat). Rien n'est supprimé."""
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
    for r in recs:
        st.markdown(f"**{'✅' if r.status == 'ok' else '❌'} #{r.id} · requête {r.turn} · {r.tool} · {r.duration_ms} ms**")
        st.markdown(f"Statut : `{r.status}` · début (UTC) : {r.started_at} · empreinte du résultat : `{r.result_digest}`")
        st.markdown("Arguments (JSON)")
        st.json(r.arguments)
        if r.error:
            st.error(r.error)
        else:
            st.markdown("Références aux données (fichiers, empreintes SHA-256, période, devise, version des règles)")
            st.json(r.data_refs)
            st.markdown("Résultat retourné par l'outil")
            st.json(r.result, expanded=False)
    st.caption(f"Requête n° {t.turn} · {len(recs)} appel(s) d'outil dans cette requête.")


def render_how_answered(t, profiles: dict, active_profile: str) -> None:
    """Niveau 1 : ce que l'assistant a réellement fait, en français simple (uniquement des appels exécutés)."""
    s = summary_lines(t.tool_records, profiles, active_profile)
    st.markdown("**Comment l'assistant a-t-il obtenu cette réponse ?**")
    if not s["calls"]:
        st.markdown("- Aucun outil financier n'a été exécuté pour cette requête.")
    for c in s["calls"]:
        st.markdown(f"- {'✅' if c.ok else '❌'} {c.text}")
    for n in s["notes"]:
        st.markdown(f"- {n}")
    for d in s["disclaimers"]:
        st.caption(d)


def render_facts_used(t) -> None:
    """Faits historiques repris des résultats d'outils (valeurs du moteur, jamais du texte du modèle)."""
    ev = next((r for r in sorted(t.tool_records, key=lambda r: r.id) if r.tool == "evaluate_portfolio" and r.status == "ok"), None)
    if ev is None:
        return
    m, c, w = ev.result["metrics"], ev.result["concentration"], ev.result["window"]
    st.markdown("**Faits historiques utilisés (valeurs calculées par le moteur)**")
    st.markdown(f"- Période : du {w['start']} au {w['end']} · devise : dollar canadien (CAD)\n"
                f"- Rendement historique cumulé : {fr(m['cumulative_return_pct'])} %\n"
                f"- Fluctuations annualisées : {fr(m['annualized_volatility_pct'])} %\n"
                f"- Plus forte baisse historique : {fr(m['max_drawdown_pct'])} %\n"
                f"- Plus grande position : {c['largest_position']} ({pct_value(c['largest_position_weight_pct'])}) · "
                f"environ {fr(c['effective_number_of_positions'])} positions de poids égal")


# ----------------------------------------------------------------------------- requêtes de l'assistant
def render_request(t, service, select_profile_cb, active_profile: str, show_facts: bool = False) -> None:
    """Affiche UNE requête : son statut ne dépend que des outils exécutés pendant cette requête."""
    st.markdown(f"**Question :** {t.question}")
    if t.context:
        wa = ", ".join(f"{k_} {pct_value(v)}" for k_, v in (t.context["weights_a_pct"] or {}).items())
        wb = ", ".join(f"{k_} {pct_value(v)}" for k_, v in (t.context["weights_b_pct"] or {}).items()) or "aucun"
        name = service.profiles[t.context["profile_id"]]["display_name"]
        st.caption(f"Contexte de cette requête : profil {name} · A = {wa} · B = {wb}")
    if t.clarification:
        st.warning(t.clarification)
        cols = st.columns(max(1, len(t.clarification_profiles)))
        for col, pid in zip(cols, t.clarification_profiles):
            col.button(f"Sélectionner {service.profiles[pid]['display_name']}", key=f"selprof_{t.turn}_{pid}", on_click=select_profile_cb, args=(pid,))
        st.caption(f"Requête n° {t.turn} · 0 appel d'outil · aucun appel au modèle (précision demandée avant toute analyse).")
        return
    if t.error:
        st.error(f"{t.error['message']}  \nType : `{t.error['kind']}`")
        with st.expander("Détail technique de l'erreur"):
            st.code(t.error["detail"])
        st.info("Le moteur financier reste disponible : tous les résultats de l'application sont calculés sans l'assistant IA.")
    elif t.withheld:
        st.warning(f"**Analyse incomplète.** {t.withheld_reason}")
        st.info("Les indicateurs et le Guardian Check des autres onglets restent valides : ils proviennent du moteur Python.")
    else:
        if t.caveat:
            st.warning(t.caveat)
        st.markdown("**Réponse de l'assistant IA** — une interprétation générée par Nova 2 Lite. Les chiffres viennent des outils financiers (voir plus bas) :")
        st.markdown(t.text)
        if show_facts:
            render_facts_used(t)
    render_how_answered(t, service.profiles, active_profile)
    with st.expander("Voir les détails techniques de l'analyse"):
        render_tools_technical(t)
    n_ok = sum(1 for r in t.tool_records if r.status == "ok")
    st.caption(f"Requête n° {t.turn} · {len(t.tool_records)} appel(s) d'outil dans cette requête ({n_ok} réussi(s)) · "
               f"{t.cycles if t.cycles is not None else '?'} cycle(s) interne(s) du modèle · {t.duration_s} s · "
               f"jetons : {t.usage.get('inputTokens', '?')} entrée / {t.usage.get('outputTokens', '?')} sortie")
