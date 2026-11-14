"""Graphiques Plotly construits directement à partir des résultats du moteur (aucune donnée recopiée)."""
from __future__ import annotations

import plotly.graph_objects as go

from guardian.finance.analysis import AnalysisResult
from guardian.finance.metrics import drawdown_series

PORTFOLIO_COLOR = "#0B3D91"
ASSET_COLORS = ["#C0392B", "#2E86C1", "#27AE60", "#8E44AD", "#D68910", "#7F8C8D"]


def _layout(fig: go.Figure, title: str, yaxis: str) -> go.Figure:
    fig.update_layout(title=title, yaxis_title=yaxis, template="plotly_white", height=380,
                      margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    return fig


def performance_figure(result: AnalysisResult) -> go.Figure:
    """Valeur normalisée (base 100) du portefeuille rééquilibré et de chaque actif, en CAD."""
    fig = go.Figure()
    v = result.value
    fig.add_trace(go.Scatter(x=v.index, y=100.0 * v / v.iloc[0], name="Portefeuille (rééquilibré mensuel)",
                             line=dict(color=PORTFOLIO_COLOR, width=3)))
    for i, t in enumerate(result.asset_prices_cad.columns):
        p = result.asset_prices_cad[t]
        fig.add_trace(go.Scatter(x=p.index, y=100.0 * p / p.iloc[0], name=t, opacity=0.7,
                                 line=dict(color=ASSET_COLORS[i % len(ASSET_COLORS)], width=1.2)))
    return _layout(fig, "Performance historique normalisée (base 100, CAD)", "Valeur (base 100)")


def drawdown_figure(result: AnalysisResult) -> go.Figure:
    dd = 100.0 * drawdown_series(result.value)
    fig = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", name="Drawdown du portefeuille",
                               line=dict(color="#C0392B")))
    return _layout(fig, "Baisse depuis le dernier sommet (drawdown, %)", "%")


def allocation_figure(result: AnalysisResult) -> go.Figure:
    tickers = list(result.weights)
    fig = go.Figure(go.Pie(labels=tickers, values=[100.0 * result.weights[t] for t in tickers], hole=0.55,
                           textinfo="label+percent", sort=False))
    fig.update_layout(template="plotly_white", height=300, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
    return fig
