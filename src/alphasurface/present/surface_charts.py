"""Plotly figures for the vol surface. Monochrome, themed from present.theme.

Plotly here, not TradingView Lightweight Charts: a 3D surface is not a time series, and Lightweight
Charts does not draw one. Price charts stay where they are.
"""

from __future__ import annotations

import plotly.graph_objects as go

from alphasurface.present import theme

T = theme.TOKENS

# Sequential, one hue, light to dark: more vol reads darker. Starts at a visible step above the
# surface so the lowest vol is still a color, not a hole.
SCALE = [
    [0.0, T["surface_raised"]],
    [0.25, T["line_strong"]],
    [0.5, T["ink_2"]],
    [0.75, T["fg_muted"]],
    [1.0, T["navy"]],
]
GRID = "rgba(22,26,51,0.06)"


def apply_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        # Empty title.text on purpose: Streamlit's plotly theme bold-wraps the title in JS
        # and renders a literal "undefined" when the figure has no title at all.
        title=dict(text=""),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.SANS, color=T["fg_subtle"], size=11),
        margin=dict(l=0, r=0, t=8, b=0),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=T["fg_muted"], size=11), itemwidth=30),
        hoverlabel=dict(
            bgcolor=T["surface"],
            bordercolor=T["line"],
            font_color=T["fg"],
            font_family=theme.SANS,
            font_size=12,
        ),
    )
    # Horizontal gridlines only, a hairline baseline, no box: the data carries the chart.
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor=T["line"],
        ticks="outside",
        ticklen=3,
        tickcolor=T["line"],
        title_font_size=11,
    )
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False, title_font_size=11)
    return fig


def _colorbar(**extra) -> dict:
    return dict(
        title=dict(text="IV, %", font=dict(size=11, color=T["fg_subtle"])),
        tickfont=dict(color=T["fg_subtle"], size=10),
        thickness=10,
        len=0.8,
        outlinewidth=0,
        **extra,
    )


def surface_heatmap(heat, labels: list[str], height: int | None = None) -> go.Figure:
    """IV by expiry (rows, nearest at the top) and moneyness K/F - 1 in percent (columns).
    Blank cells are strikes not quoted for that expiry."""
    z = heat.to_numpy() * 100
    fig = go.Figure(
        go.Heatmap(
            x=[float(c) for c in heat.columns],
            y=labels,
            z=z,
            colorscale=SCALE,
            colorbar=_colorbar(x=1.0, xpad=8),
            xgap=1,
            ygap=1,
            hoverongaps=False,
            hovertemplate="%{y}<br>moneyness %{x:+.1f}%<br>IV %{z:.1f}%<extra></extra>",
        )
    )
    fig = apply_layout(fig, height or max(260, 34 * len(labels) + 70))
    fig.update_xaxes(title="moneyness, K/F - 1 (%)", ticksuffix="%", showline=False, ticks="")
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", type="category")
    return fig


def surface_3d(mesh, height: int = 560) -> go.Figure:
    """Implied vol over moneyness (percent from the forward) and days to expiry."""
    xi, yi, zi = mesh
    fig = go.Figure(
        go.Surface(
            x=xi,
            y=yi,
            z=zi * 100,
            colorscale=SCALE,
            colorbar=_colorbar(x=0.9),
            contours={"z": {"show": True, "usecolormap": True, "project": {"z": True}, "width": 1}},
            hovertemplate="moneyness %{x:+.1f}%<br>%{y:.0f} days<br>IV %{z:.1f}%<extra></extra>",
        )
    )
    axis = dict(
        backgroundcolor="rgba(0,0,0,0)",
        gridcolor=T["line"],
        zerolinecolor=T["line_strong"],
        color=T["fg_subtle"],
        showbackground=False,
        title_font=dict(size=11, color=T["fg_muted"]),
        tickfont=dict(size=10),
    )
    fig.update_layout(
        scene=dict(
            domain=dict(x=[0.0, 0.88], y=[0.0, 1.0]),
            xaxis=dict(title="moneyness, %", ticksuffix="%", **axis),
            yaxis=dict(title="days to expiry", **axis),
            zaxis=dict(title="IV, %", **axis),
            camera=dict(eye=dict(x=1.45, y=-1.55, z=0.75), center=dict(x=0, y=0, z=-0.12)),
            aspectratio=dict(x=1.35, y=1.35, z=0.7),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.SANS, color=T["fg_muted"], size=11),
        height=height,
        margin=dict(l=0, r=0, t=0, b=0),
        title=dict(text=""),
    )
    return fig


def smile_chart(
    board,
    *,
    axis: str = "moneyness",
    forward: float | None = None,
    prior=None,
    prior_label: str = "Prior pull",
    height: int = 360,
) -> go.Figure:
    """One expiry's smile: out-of-the-money puts below the forward and calls above it, one
    continuous curve, against moneyness (percent from the forward) or strike. A prior stored
    smile for the same expiry draws in gray behind it."""

    def xs(frame):
        return (frame["moneyness"] - 1) * 100 if axis == "moneyness" else frame["strike"]

    fig = go.Figure()
    if prior is not None and not prior.empty:
        fig.add_trace(
            go.Scatter(
                x=xs(prior),
                y=prior["iv"] * 100,
                mode="lines",
                name=prior_label,
                line=dict(color=T["line_strong"], width=2),
                hovertemplate="%{x:.1f}<br>IV %{y:.2f}%<extra>" + prior_label + "</extra>",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=xs(board),
            y=board["iv"] * 100,
            mode="lines+markers",
            name="Now",
            line=dict(color=T["fg"], width=2),
            marker=dict(size=5, color=T["fg"]),
            customdata=board[["strike", "delta", "kind"]],
            hovertemplate=(
                "K %{customdata[0]:,.0f} %{customdata[2]}<br>IV %{y:.2f}%<br>"
                "delta %{customdata[1]:+.2f}<extra></extra>"
            ),
        )
    )
    at = 0.0 if axis == "moneyness" else forward
    if at is not None:
        fig.add_vline(
            x=at,
            line=dict(color=T["fg_subtle"], width=1, dash="dot"),
            annotation_text=f"F {forward:,.2f}" if forward else "F",
            annotation_position="top",
            annotation_font=dict(color=T["fg_subtle"], size=11),
        )
    fig = apply_layout(fig, height)
    fig.update_xaxes(
        title="moneyness, K/F - 1 (%)" if axis == "moneyness" else "strike",
        ticksuffix="%" if axis == "moneyness" else "",
    )
    fig.update_yaxes(title=None, ticksuffix="%")
    fig.update_layout(
        legend=dict(orientation="h", x=0, y=1.1), showlegend=prior is not None and not prior.empty
    )
    return fig


def term_structure_chart(
    term, *, vix=None, rv: float | None = None, height: int = 360
) -> go.Figure:
    """ATM vol by days to expiry, with the VIX family (constant-maturity index vols) as points
    and realized vol as a level line for reference. One axis: all of it is annualized vol."""
    fig = go.Figure(
        go.Scatter(
            x=term["dte"],
            y=term["atm_iv"] * 100,
            mode="lines+markers",
            name="ATM implied",
            line=dict(color=T["fg"], width=2),
            marker=dict(size=7, color=T["fg"]),
            hovertemplate="%{x:.0f} days<br>ATM %{y:.2f}%<extra></extra>",
        )
    )
    if vix is not None and not vix.empty:
        fig.add_trace(
            go.Scatter(
                x=vix["days"],
                y=vix["level"],
                mode="markers+text",
                name="VIX family",
                text=vix["label"],
                textposition="top center",
                textfont=dict(size=10, color=T["fg_subtle"]),
                marker=dict(
                    size=9,
                    symbol="diamond",
                    color=T["surface"],
                    line=dict(color=T["ink_2"], width=2),
                ),
                hovertemplate="%{text}<br>%{y:.2f}%<extra></extra>",
            )
        )
    if rv is not None and rv == rv:
        fig.add_hline(
            y=rv * 100,
            line=dict(color=T["line_strong"], width=1.5, dash="dash"),
            annotation_text=f"Realized 21D {rv:.1%}",
            annotation_position="bottom right",
            annotation_font=dict(color=T["fg_subtle"], size=11),
        )
    fig = apply_layout(fig, height)
    fig.update_xaxes(title="days to expiry")
    fig.update_yaxes(title=None, ticksuffix="%")
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.1), showlegend=len(fig.data) > 1)
    return fig
