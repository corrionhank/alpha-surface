"""Plotly figures for the scenarios page. Monochrome: ink for what matters, gray for context,
and the risk color only on a line that marks a loss threshold, always labeled."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from present import theme
from present.surface_charts import apply_layout

T = theme.TOKENS


def _ink(alpha: float) -> str:
    return f"rgba(17,17,17,{alpha})"


def _vline(fig: go.Figure, x: float, text: str, color: str = T["line_strong"], dash: str = "dot",
           position: str = "top") -> None:
    fig.add_vline(x=x, line=dict(color=color, width=1, dash=dash), annotation_text=text,
                  annotation_position=position, annotation_font=dict(size=11, color=T["fg_subtle"]))


def fan(paths: np.ndarray, bands: pd.DataFrame, n_show: int = 80, height: int = 420) -> go.Figure:
    """A sample of paths in faint ink under the percentile fan, median in solid ink."""
    days = np.arange(paths.shape[1])
    fig = go.Figure()
    show = paths[: min(n_show, len(paths))]
    # One trace with NaN breaks draws every sample path at the cost of one.
    x = np.tile(np.append(days, np.nan), len(show))
    y = np.hstack([np.append(p, np.nan) for p in show])
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=_ink(0.07), width=1),
                             hoverinfo="skip", showlegend=False))
    for lo, hi, alpha, label in (("p5", "p95", 0.07, "5 to 95"), ("p25", "p75", 0.12, "25 to 75")):
        fig.add_trace(go.Scatter(x=days, y=bands[hi], mode="lines", line=dict(width=0),
                                 hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=days, y=bands[lo], mode="lines", line=dict(width=0),
                                 fill="tonexty", fillcolor=_ink(alpha), name=f"{label} pct",
                                 hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=days, y=bands["p50"], mode="lines", name="Median",
                             line=dict(color=T["fg"], width=2),
                             hovertemplate="day %{x}<br>median %{y:,.2f}<extra></extra>"))
    fig.update_xaxes(title="trading days ahead")
    fig.update_yaxes(title="price")
    fig = apply_layout(fig, height)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08))
    return fig


def histogram(values: np.ndarray, marks: list[tuple[float, str, str]], x_title: str,
              height: int = 320, bins: int = 80) -> go.Figure:
    """Distribution of outcomes with labeled vertical marks: (x, label, color).

    When one bin holds most of the mass (a short option that usually expires worthless), the
    count axis goes logarithmic so the tail, which is the point, stays visible.
    """
    counts, _ = np.histogram(values, bins=bins)
    log = counts.max() > 0.3 * len(values)
    fig = go.Figure(go.Histogram(x=values, nbinsx=bins, marker=dict(color=_ink(0.55)),
                                 hovertemplate="%{x}<br>%{y} paths<extra></extra>"))
    for i, (x, label, color) in enumerate(marks):
        dash = "dot" if color == T["line_strong"] else "dash"
        fig.add_vline(x=x, line=dict(color=color, width=1, dash=dash))
        # Stagger the labels down the plot so marks that sit close together stay readable.
        fig.add_annotation(x=x, y=1 - 0.09 * i, xref="x", yref="paper", text=label,
                           showarrow=False, xanchor="left", xshift=4,
                           font=dict(size=11, color=T["fg_subtle"]), bgcolor="rgba(255,255,255,0.8)")
    fig.update_xaxes(title=x_title)
    fig.update_yaxes(title="paths, log scale" if log else "paths", type="log" if log else "linear")
    fig = apply_layout(fig, height)
    fig.update_layout(bargap=0.04, showlegend=False)
    return fig


def profile(grid: np.ndarray, pnl_h: np.ndarray, pnl_exp: np.ndarray | None, terminal: np.ndarray,
            spot: float, horizon_label: str, height: int = 380) -> go.Figure:
    """P&L across terminal prices, over the shaded distribution of where price actually ends."""
    fig = go.Figure()
    density, edges = np.histogram(terminal, bins=70, density=True)
    mids = (edges[:-1] + edges[1:]) / 2
    fig.add_trace(go.Bar(x=mids, y=density, yaxis="y2", marker=dict(color=_ink(0.08)),
                         hoverinfo="skip", name="Price at horizon", width=edges[1] - edges[0]))
    if pnl_exp is not None:
        fig.add_trace(go.Scatter(x=grid, y=pnl_exp, mode="lines", name="At expiry",
                                 line=dict(color=T["ink_2"], width=1.5, dash="dash"),
                                 hovertemplate="S %{x:,.2f}<br>P&L %{y:+,.0f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=grid, y=pnl_h, mode="lines", name=horizon_label,
                             line=dict(color=T["fg"], width=2),
                             hovertemplate="S %{x:,.2f}<br>P&L %{y:+,.0f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=T["line_strong"], width=1))
    _vline(fig, spot, "spot")
    fig.update_xaxes(title="price at horizon")
    fig.update_yaxes(title="P&L ($)")
    fig = apply_layout(fig, height)
    fig.update_layout(
        yaxis2=dict(overlaying="y", side="right", showgrid=False, showticklabels=False,
                    rangemode="tozero"),
        legend=dict(orientation="h", x=0, y=1.1), bargap=0,
    )
    return fig


def edge_curve(vols: np.ndarray, mean: np.ndarray, sd: np.ndarray, iv: float,
               height: int = 340) -> go.Figure:
    """Mean hedged P&L across realized vols, with a one-SD band: edge versus noise."""
    x = vols * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=mean + sd, mode="lines", line=dict(width=0), hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=mean - sd, mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_ink(0.08), name="1 SD", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=mean, mode="lines+markers", name="Mean P&L",
                             line=dict(color=T["fg"], width=2), marker=dict(size=6),
                             hovertemplate="realized %{x:.1f}%<br>mean %{y:+,.0f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=T["line_strong"], width=1))
    _vline(fig, iv * 100, "implied", position="bottom right")
    fig.update_xaxes(title="realized vol over the trade (%)")
    fig.update_yaxes(title="P&L per contract ($)")
    fig = apply_layout(fig, height)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.1))
    return fig


def growth(fs: np.ndarray, g: np.ndarray, marks: list[tuple[float, str]], height: int = 320) -> go.Figure:
    """Log growth per bet against the fraction staked, with Kelly and friends marked."""
    fig = go.Figure(go.Scatter(x=fs * 100, y=g * 100, mode="lines", line=dict(color=T["fg"], width=2),
                               hovertemplate="stake %{x:.1f}%<br>growth %{y:+.3f}% per bet<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=T["line_strong"], width=1))
    for i, (f, label) in enumerate(marks):
        _vline(fig, f * 100, label, position="top right" if i % 2 == 0 else "bottom right")
    fig.update_xaxes(title="fraction of bankroll per bet (%)")
    fig.update_yaxes(title="expected log growth per bet (%)")
    fig = apply_layout(fig, height)
    fig.update_layout(showlegend=False)
    return fig


def wealth(paths: np.ndarray, n_show: int = 60, height: int = 340) -> go.Figure:
    """Bankroll paths on a log scale: sample, median, and the mean the lucky few drag up."""
    n = np.arange(paths.shape[1])
    show = paths[: min(n_show, len(paths))]
    x = np.tile(np.append(n, np.nan), len(show))
    y = np.hstack([np.append(p, np.nan) for p in show])
    fig = go.Figure(go.Scatter(x=x, y=y, mode="lines", line=dict(color=_ink(0.08), width=1),
                               hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=n, y=np.median(paths, axis=0), mode="lines", name="Median",
                             line=dict(color=T["fg"], width=2)))
    fig.add_trace(go.Scatter(x=n, y=paths.mean(axis=0), mode="lines", name="Mean",
                             line=dict(color=T["ink_2"], width=2, dash="dash")))
    fig.add_hline(y=1, line=dict(color=T["line_strong"], width=1))
    fig.update_xaxes(title="bets")
    fig.update_yaxes(title="bankroll (start = 1)", type="log")
    fig = apply_layout(fig, height)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.1))
    return fig


def replays(paths: dict[str, pd.Series], selected: str, spot: float, height: int = 400) -> go.Figure:
    """Every episode rescaled to today's price; the selected one in ink, the rest in gray."""
    fig = go.Figure()
    for name, path in paths.items():
        on = name == selected
        fig.add_trace(go.Scatter(
            x=np.arange(len(path)), y=path.to_numpy(), mode="lines", name=name,
            line=dict(color=T["fg"] if on else _ink(0.18), width=2.2 if on else 1.2),
            hovertemplate=f"{name}<br>day %{{x}}<br>%{{y:,.2f}}<extra></extra>",
            showlegend=False,
        ))
    fig.add_hline(y=spot, line=dict(color=T["line_strong"], width=1, dash="dot"))
    fig.update_xaxes(title="trading days from the start of the episode")
    fig.update_yaxes(title="price, rescaled to today")
    return apply_layout(fig, height)
