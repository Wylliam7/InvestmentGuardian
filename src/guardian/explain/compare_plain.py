"""Compromis de la comparaison A/B en phrases simples, avec les valeurs exactes. Aucun « meilleur » : on décrit des écarts historiques."""
from __future__ import annotations

from guardian.explain.format import fr, pct

TOL_PTS = 0.5      # écart (en points de %) en dessous duquel deux valeurs sont dites proches
TOL_N = 0.25       # idem pour le nombre effectif de positions


def plain_tradeoffs(cmp_) -> list[str]:
    a, b = cmp_.a, cmp_.b
    out = []

    def pick(va: float, vb: float, tol: float):
        d = vb - va
        return None if abs(d) < tol else ("B" if d > 0 else "A")

    ret = pick(100 * a.cumulative_return, 100 * b.cumulative_return, TOL_PTS)
    if ret:
        hi, lo = (a, b) if ret == "A" else (b, a)
        out.append(f"{ret} a eu un rendement historique supérieur : {pct(hi.cumulative_return)} contre {pct(lo.cumulative_return)} "
                   f"pour {'B' if ret == 'A' else 'A'} (rendement cumulé sur la période).")
    else:
        out.append(f"A et B ont eu des rendements historiques proches : {pct(a.cumulative_return)} et {pct(b.cumulative_return)}.")

    vol = pick(100 * a.volatility, 100 * b.volatility, TOL_PTS)
    if vol:
        lo_w, hi_w = ("B", "A") if vol == "A" else ("A", "B")          # `vol` = celui dont les fluctuations sont les plus fortes
        lo_res, hi_res = (b, a) if vol == "A" else (a, b)
        out.append(f"{lo_w} a connu des fluctuations moins importantes : {pct(lo_res.volatility)} par an contre {pct(hi_res.volatility)} pour {hi_w}.")
    else:
        out.append(f"A et B ont connu des fluctuations proches : {pct(a.volatility)} et {pct(b.volatility)} par an.")

    dd_a, dd_b = abs(a.drawdown.max_drawdown), abs(b.drawdown.max_drawdown)
    deep = pick(100 * dd_a, 100 * dd_b, TOL_PTS)
    if deep:
        shallow = "B" if deep == "A" else "A"
        out.append(f"{deep} a connu une baisse maximale plus profonde : −{fr(100 * max(dd_a, dd_b))} % contre −{fr(100 * min(dd_a, dd_b))} % pour {shallow}.")
    else:
        out.append(f"A et B ont connu des baisses maximales proches : −{fr(100 * dd_a)} % et −{fr(100 * dd_b)} %.")

    na, nb = len(a.weights), len(b.weights)
    ea, eb = a.concentration.effective_n, b.concentration.effective_n
    spread = pick(ea, eb, TOL_N)
    if spread:
        wide, narrow = ("B", "A") if spread == "B" else ("A", "B")
        ew, en = (eb, ea) if spread == "B" else (ea, eb)
        nw, nn = (nb, na) if spread == "B" else (na, nb)
        out.append(f"{wide} est plus réparti entre ses positions : environ {fr(ew)} positions de poids égal ({nw} actifs) contre {fr(en)} pour {narrow} ({nn} actifs).")
    else:
        out.append(f"A et B ont une répartition comparable : environ {fr(ea)} et {fr(eb)} positions de poids égal ({na} et {nb} actifs).")
    if any(x.asset_class in ("etf_equity", "etf_bond") for x in (*a.assets, *b.assets)):
        out[-1] += " Cette mesure porte sur les poids des lignes, pas sur les entreprises sous-jacentes des FNB, dont la diversification n'est pas mesurée."
    return out


COMPARE_FOOTER = ("Ces écarts décrivent le passé (2021-2026), sur un seul cycle de marché. Aucun des deux portefeuilles n'est désigné comme meilleur : "
                  "le choix dépend de vos objectifs et de votre tolérance au risque.")

COMPARE_SENSITIVITY_NOTE = ("Pour voir comment un changement d'allocation modifie les indicateurs, changez la répartition de B (par exemple le poids de NVIDIA) : "
                            "les mêmes données historiques et la même méthode de calcul s'appliquent à A et B. Cette comparaison ne teste pas d'autres périodes, "
                            "ne modélise ni frais ni impôts et ne prévoit rien : elle décrit une seule trajectoire passée.")
