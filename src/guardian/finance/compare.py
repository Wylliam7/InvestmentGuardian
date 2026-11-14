"""Comparaison A/B de deux portefeuilles fictifs : même période, même grille, même devise, mêmes conventions.

La comparaison décrit des écarts historiques et des compromis ; elle ne désigne jamais un « meilleur » portefeuille.
"""
from __future__ import annotations

from dataclasses import dataclass

from guardian.finance.analysis import AnalysisResult
from guardian.rules.engine import ATTENTION, CONFLIT, GuardianReport

SAME_TOL_PTS = 0.5          # écart de rendement/volatilité/drawdown considéré comme négligeable (points de %)
SAME_TOL_N = 0.25           # idem pour le nombre effectif de positions


class ComparisonError(ValueError):
    pass


@dataclass(frozen=True)
class ComparisonResult:
    a: AnalysisResult
    b: AnalysisResult
    report_a: GuardianReport
    report_b: GuardianReport
    profile_id: str
    deltas: dict              # B moins A ; points de pourcentage pour les fractions
    tradeoffs: tuple          # phrases neutres, sans verdict
    conventions: dict

    def to_tool_dict(self) -> dict:
        da, db = self.a.to_tool_dict(), self.b.to_tool_dict()
        keep = lambda d: {k: d[k] for k in ("weights_pct", "metrics", "concentration", "asset_class_exposure_pct")}  # noqa: E731
        return {
            "status": "ok", "profile_id": self.profile_id, "profile_name": self.report_a.profile_name,
            "window": da["window"], "conventions": self.conventions,
            "portfolio_A": keep(da), "portfolio_B": keep(db),
            "differences_B_minus_A": self.deltas,
            "guardian_A": {"counts": self.report_a.counts(), "findings": [f.to_dict() for f in self.report_a.findings]},
            "guardian_B": {"counts": self.report_b.counts(), "findings": [f.to_dict() for f in self.report_b.findings]},
            "historical_tradeoffs": list(self.tradeoffs),
            "no_winner_notice": "Cette comparaison décrit des écarts historiques ; elle ne désigne pas un meilleur portefeuille "
                                "et ne prévoit pas les résultats futurs.",
            "thresholds_are_heuristics": True,
            "provenance": da["provenance"],
        }


def _pct(x):
    return None if x is None else round(100 * x, 2)


def _sign(delta: float, tol: float) -> int:
    return 0 if abs(delta) < tol else (1 if delta > 0 else -1)


def _tradeoffs(a: AnalysisResult, b: AnalysisResult, ra: GuardianReport, rb: GuardianReport, name: str) -> list:
    out = []
    d_ret = 100 * (b.cumulative_return - a.cumulative_return)
    d_vol = 100 * (b.volatility - a.volatility)
    d_dd = 100 * (abs(b.drawdown.max_drawdown) - abs(a.drawdown.max_drawdown))     # > 0 : drawdown de B plus profond
    d_n = b.concentration.effective_n - a.concentration.effective_n
    s_ret, s_vol, s_dd, s_n = _sign(d_ret, SAME_TOL_PTS), _sign(d_vol, SAME_TOL_PTS), _sign(d_dd, SAME_TOL_PTS), _sign(d_n, SAME_TOL_N)

    def who(s, high="B", low="A"):
        return high if s > 0 else low

    if s_ret:
        out.append(f"Rendement cumulé historique plus élevé pour {who(s_ret)} ({abs(d_ret):.1f} points d'écart).")
    else:
        out.append("Rendements cumulés historiques proches entre A et B.")
    if s_vol:
        out.append(f"Volatilité annualisée plus élevée pour {who(s_vol)} ({abs(d_vol):.1f} points d'écart).")
    else:
        out.append("Volatilités annualisées proches entre A et B.")
    if s_dd:
        out.append(f"Drawdown maximal plus profond pour {who(s_dd)} ({abs(d_dd):.1f} points d'écart).")
    else:
        out.append("Drawdowns maximaux proches entre A et B.")
    if s_n:
        out.append(f"Nombre effectif de positions plus élevé pour {who(s_n)} ({b.concentration.effective_n:.1f} pour B, "
                   f"{a.concentration.effective_n:.1f} pour A) ; plus la valeur est élevée, plus le poids est réparti.")
    if s_ret and s_vol and s_ret == s_vol:
        out.append(f"Compromis historique observé : le portefeuille au rendement cumulé le plus élevé ({who(s_ret)}) est aussi celui "
                   f"dont la volatilité a été la plus élevée sur cette période.")
    elif s_ret and s_vol and s_ret != s_vol:
        out.append("Sur cette période, le portefeuille au rendement cumulé le plus élevé n'est pas celui dont la volatilité a été la plus élevée.")
    ca, cb = ra.counts(), rb.counts()
    out.append(f"Constats Guardian pour {name} (seuils heuristiques) : A compte {ca[CONFLIT]} conflit(s) potentiel(s) et "
               f"{ca[ATTENTION]} attention(s) ; B compte {cb[CONFLIT]} conflit(s) potentiel(s) et {cb[ATTENTION]} attention(s).")
    out.append("Ces écarts décrivent le passé (2021-2026), sur un seul cycle de marché ; ils ne désignent pas une meilleure allocation et ne prévoient pas l'avenir.")
    return out


def compare_portfolios(service, weights_a: dict, weights_b: dict, profile_id: str, start=None, end=None) -> ComparisonResult:
    """Évalue A et B sur EXACTEMENT la même fenêtre et la même grille ; échoue si ce n'est pas le cas."""
    res_a, rep_a = service.check(weights_a, profile_id, start, end)
    res_b, rep_b = service.check(weights_b, profile_id, start, end)
    if not res_a.value.index.equals(res_b.value.index):
        raise ComparisonError("Les deux portefeuilles ne sont pas évalués sur la même grille de dates.")
    if res_a.series.rebalance != res_b.series.rebalance:
        raise ComparisonError("Les deux portefeuilles n'utilisent pas la même convention de rééquilibrage.")
    ann = None if (res_a.annualized_return is None or res_b.annualized_return is None) else _pct(res_b.annualized_return - res_a.annualized_return)
    deltas = {
        "cumulative_return_pts": _pct(res_b.cumulative_return - res_a.cumulative_return),
        "annualized_return_pts": ann,
        "annualized_volatility_pts": _pct(res_b.volatility - res_a.volatility),
        "max_drawdown_pts": _pct(res_b.drawdown.max_drawdown - res_a.drawdown.max_drawdown),
        "largest_position_weight_pts": _pct(res_b.concentration.max_weight - res_a.concentration.max_weight),
        "effective_positions": round(res_b.concentration.effective_n - res_a.concentration.effective_n, 2),
        "note": "écart = B moins A ; pour le drawdown (valeur négative), un écart positif signifie un drawdown moins profond pour B",
    }
    conventions = {"currency": "CAD", "window": f"{res_a.series.start.date()} → {res_a.series.end.date()}",
                   "n_observations": res_a.n_obs, "same_date_grid": True,
                   "rebalancing": res_a.provenance["rebalancing"], "price_field": "adj_close",
                   "annualization_factor": round(res_a.factor, 2)}
    name = rep_a.profile_name
    return ComparisonResult(a=res_a, b=res_b, report_a=rep_a, report_b=rep_b, profile_id=profile_id, deltas=deltas,
                            tradeoffs=tuple(_tradeoffs(res_a, res_b, rep_a, rep_b, name)), conventions=conventions)
