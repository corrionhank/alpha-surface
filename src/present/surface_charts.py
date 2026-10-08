"""Plotly figures for the vol surface. Monochrome, themed from present.theme.

Plotly here, not TradingView Lightweight Charts: a 3D surface is not a time series, and Lightweight
Charts does not draw one. Price charts stay where they are.
"""

from __future__ import annotations

import plotly.graph_objects as go

from present import theme

T = theme.TOKENS

# Sequential gray to ink: more vol reads darker. No hue, per the style guide.
SCALE = [[0.0, T["line_strong"]], [0.5, T["fg_subtle"]], [1.0, T["fg"]]]
GRID = "rgba(17,17,17,0.06)"


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
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=T["fg_muted"], size=11),
                    itemwidth=30),
        hoverlabel=dict(bgcolor=T["surface"], bordercolor=T["line"], font_color=T["fg"],
                        font_family=theme.SANS, font_size=12),
    )
    # Horizontal gridlines only, a hairline baseline, no box: the data carries the chart.
    fig.update_xaxes(showgrid=False, zeroline=False, showline=True, linecolor=T["line"],
                     ticks="outside", ticklen=3, tickcolor=T["line"], title_font_size=11)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, showline=False, title_font_size=11)
    return fig


def surface_3d(mesh, height: int = 560) -> go.Figure:
    """Implied vol over log-moneyness and days to expiry."""
    xi, yi, zi = mesh

    fig = go.Figure(
        go.Surface(
            x=xi, y=yi, z=zi * 100, colorscale=SCALE, showscale=True,
            colorbar=dict(title="IV %", tickfont=dict(color=T["fg_subtle"]), thickness=12, len=0.7,
                          outlinewidth=0),
            contours={"z": {"show": True, "usecolormap": True, "project": {"z": True},
                            "width": 1}},
            hovertemplate="log-moneyness %{x:.3f}<br>%{y:.0f} DTE<br>IV %{z:.1f}%<extra></extra>",
        )
    )
    axis = dict(backgroundcolor="rgba(0,0,0,0)", gridcolor=T["line"], zerolinecolor=T["line_strong"],
                color=T["fg_subtle"], showbackground=False)
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="log(K/F)", **axis),
            yaxis=dict(title="days to expiry", **axis),
            zaxis=dict(title="IV %", **axis),
            camera=dict(eye=dict(x=1.6, y=-1.5, z=0.9)),
            aspectratio=dict(x=1.3, y=1.5, z=0.75),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=theme.SANS, color=T["fg_muted"], size=11),
        height=height,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    return fig


def smile_chart(board, spot: float, height: int = 380) -> go.Figure:
    """One expiry's smile: IV against strike, puts and calls drawn separately.

    Split by side on purpose. The kink at the forward is real, and averaging across it hides the
    single most informative feature of an equity surface, which is that the put wing is bid.
    """
    fig = go.Figure()
    # Two series in one hue family: ink for puts, gray dashed for calls, named in the legend.
    sides = (("put", T["fg"], "solid", "Puts (OTM)"), ("call", T["ink_2"], "dash", "Calls (OTM)"))
    for kind, color, dash, label in sides:
        side = board[board["kind"] == kind]
        if side.empty:
            continue
        fig.add_trace(go.Scatter(
            x=side["strike"], y=side["iv"] * 100, mode="lines+markers", name=label,
            line=dict(color=color, width=2, dash=dash), marker=dict(size=5),
            customdata=side[["delta", "dte"]],
            hovertemplate=("K %{x:.0f}<br>IV %{y:.2f}%<br>delta %{customdata[0]:.2f}"
                           "<extra></extra>"),
        ))
    fig.add_vline(x=spot, line=dict(color=T["line_strong"], width=1, dash="dot"),
                  annotation_text="spot", annotation_font_color=T["fg_subtle"])
    fig.update_xaxes(title="strike")
    fig.update_yaxes(title="implied vol (%)")
    fig = apply_layout(fig, height)
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.08))
    return fig


def term_structure_chart(term, height: int = 380) -> go.Figure:
    """ATM vol by expiry. Upward slope is the calm state; inversion means the front is bid."""
    fig = go.Figure(go.Scatter(
        x=term["dte"], y=term["atm_iv"] * 100, mode="lines+markers",
        line=dict(color=T["fg"], width=2), marker=dict(size=6),
        hovertemplate="%{x:.0f} DTE<br>ATM IV %{y:.2f}%<extra></extra>", name="ATM IV",
    ))
    fig.update_xaxes(title="days to expiry")
    fig.update_yaxes(title="ATM implied vol (%)")
    return apply_layout(fig, height)
