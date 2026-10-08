"""Plotly figures for the overview page. Monochrome, themed from present.theme."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from present import theme
from present.surface_charts import apply_layout

T = theme.TOKENS


def _ink(alpha: float) -> str:
    return f"rgba(17,17,17,{alpha})"  # TOKENS["fg"] at an opacity


def cone_chart(history: pd.DataFrame, cone: pd.DataFrame, height: int = 420) -> go.Figure:
    """Daily closes with the forward 1 and 2 SD expected-move cone.

    One series plus two same-hue bands, so the bands read as uncertainty around the
    price, not as extra series. Band edges are labeled directly at the cone's end.
    """
    last_ts = history["ts"].iloc[-1]
    dates = last_ts + pd.to_timedelta(cone["day"], unit="D")

    fig = go.Figure()
    for hi, lo, alpha, sd in (("hi2", "lo2", 0.05, 2), ("hi1", "lo1", 0.10, 1)):
        edge = dict(color=_ink(0.25), width=1)
        fig.add_trace(go.Scatter(
            x=dates, y=cone[hi], mode="lines", line=edge, showlegend=False,
            hovertemplate=f"+{sd} SD %{{y:,.2f}}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=dates, y=cone[lo], mode="lines", line=edge, fill="tonexty",
            fillcolor=_ink(alpha), showlegend=False,
            hovertemplate=f"-{sd} SD %{{y:,.2f}}<extra></extra>",
        ))
        fig.add_annotation(
            x=dates.iloc[-1], y=cone[hi].iloc[-1], text=f"{sd} SD", showarrow=False,
            xanchor="left", xshift=4, font=dict(size=11, color=T["fg_subtle"]),
        )

    # Single series: the subheader names it, so no legend box (dataviz rule).
    fig.add_trace(go.Scatter(
        x=history["ts"], y=history["close"], mode="lines", name="close", showlegend=False,
        line=dict(color=T["fg"], width=2),
        hovertemplate="%{x|%b %d}  %{y:,.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[last_ts], y=[history["close"].iloc[-1]], mode="markers", showlegend=False,
        marker=dict(color=T["fg"], size=8), hoverinfo="skip",
    ))
    fig.add_vline(x=last_ts, line=dict(color=T["line_strong"], width=1, dash="dot"))

    fig.update_yaxes(title=None)
    fig.update_xaxes(title=None)
    return apply_layout(fig, height)


def term_curve_chart(curve: pd.DataFrame, height: int = 300) -> go.Figure:
    """The VIX curve today in ink, a week and a month ago in grays, x spaced by tenor."""
    fig = go.Figure()
    styles = {"A month ago": (T["line_strong"], "dot"), "A week ago": (T["ink_2"], "dash"),
              "Today": (T["fg"], "solid")}
    for name, (color, dash) in styles.items():
        if name not in curve:
            continue
        fig.add_trace(go.Scatter(
            x=curve["days"], y=curve[name], mode="lines+markers", name=name,
            line=dict(color=color, width=2 if name == "Today" else 1.5, dash=dash),
            marker=dict(size=6 if name == "Today" else 4), text=list(curve.index),
            hovertemplate="%{text}  %{y:.2f}<extra>" + name + "</extra>",
        ))
    fig.update_xaxes(title=None, type="log", tickvals=list(curve["days"]),
                     ticktext=list(curve.index))
    fig.update_yaxes(title=None)
    fig = apply_layout(fig, height)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.12))
    return fig


def score_history_chart(history: pd.Series, height: int = 160) -> go.Figure:
    """A year of the fear and greed lens, with the neutral band shaded."""
    h = history.tail(252)
    fig = go.Figure()
    fig.add_hrect(y0=45, y1=55, fillcolor=_ink(0.05), line_width=0)
    fig.add_trace(go.Scatter(x=list(h.index), y=h.to_numpy(), mode="lines",
                             line=dict(color=T["fg"], width=1.6),
                             hovertemplate="%{x|%b %d}  %{y:.0f}<extra></extra>"))
    fig.update_yaxes(range=[0, 100], tickvals=[0, 25, 50, 75, 100], title=None)
    fig.update_xaxes(title=None)
    fig = apply_layout(fig, height)
    fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=4, b=0))
    return fig
