"""Scenarios: thousands of hypothetical futures, then what they mean for a price, a position, a
hedged option and a bankroll, plus history replayed from today's price.

Every tab makes the same point: a decision is judged against the distribution of outcomes, not
the one path you happen to picture. Formulas: docs/formulas.md section 14.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from derive import market_state as ms
from derive import positions as pos
from derive import pot_odds as po
from derive import simulate as sim
from present import data, theme
from present import scenario_charts as charts
from storage import reader

T = theme.TOKENS
conn = data.conn()
NO_BAR = {"displayModeBar": False}
MODELS = {"Brownian motion": "gbm", "Jump diffusion": "jump", "Historical bootstrap": "bootstrap"}

# Named stress and calm windows, each starting at the session before the move began.
EPISODES = [
    ("Financial crisis, Sep 2008", "2008-09-12"),
    ("Flash crash, May 2010", "2010-04-23"),
    ("US downgrade, Aug 2011", "2011-07-22"),
    ("China devaluation, Aug 2015", "2015-08-17"),
    ("Low-vol grind, 2017", "2017-01-03"),
    ("Volmageddon, Feb 2018", "2018-01-26"),
    ("Q4 selloff, 2018", "2018-09-20"),
    ("Covid crash, Feb 2020", "2020-02-19"),
    ("Bear market, 2022", "2022-01-03"),
    ("Yen carry unwind, Jul 2024", "2024-07-16"),
    ("Tariff shock, Apr 2025", "2025-04-02"),
]


def closes(symbol: str) -> pd.Series:
    """Daily closes for any symbol, live-topped (present.data), with today's mark in session."""
    return data.closes(symbol)


@st.cache_data(ttl=600, max_entries=6, show_spinner="Simulating paths...")
def simulate(model: str, spot: float, mu: float, sigma: float, days: int, n: int, seed: int,
             jump: tuple[float, float, float], history: str, block: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if model == "jump":
        return sim.jump(spot, mu, sigma, days, n, rng, *jump)
    if model == "bootstrap":
        lr = np.diff(np.log(closes(history).to_numpy()))
        return sim.bootstrap(spot, mu, sigma, days, n, rng, lr, block)
    return sim.gbm(spot, mu, sigma, days, n, rng)


@st.cache_data(ttl=600, max_entries=6, show_spinner="Sweeping realized vol...")
def edge_sweep(spot, strike, rate, iv, div, kind, side, every, days, mu, seed, n=1500):
    vols = np.linspace(0.5 * iv, 1.5 * iv, 9)
    mean, sd = [], []
    for i, v in enumerate(vols):
        paths = sim.gbm(spot, mu, v, days, n, np.random.default_rng(seed + i))
        out = pos.delta_hedged_pnl(paths, strike, rate, iv, div, kind, side, every) * pos.MULT
        mean.append(out.mean())
        sd.append(out.std())
    return vols, np.array(mean), np.array(sd)


def money(x: float) -> str:
    return f"{x:+,.0f}"


def pct(x: float, digits: int = 0) -> str:
    return "n/a" if x != x else f"{x:.{digits}%}"


symbols = sorted({s for s in reader.available_symbols(conn, "1d") if not s.startswith("^")}
                 | {"SPY", "QQQ", "IWM", "DIA"})

with st.sidebar:
    st.header("Market")
    symbol = data.clean(st.selectbox(
        "Symbol", symbols, index=symbols.index("SPY"), accept_new_options=True,
    ) or "SPY")
    px = closes(symbol)
    if len(px) < 30:
        st.error(f"No daily history for {symbol}.")
        st.stop()
    q = data.quote(symbol)
    spot = float(q["last"]) if q else float(px.iloc[-1])
    rv = float(ms.rolling_vol(px).iloc[-1]) / 100
    vix, irx = closes("^VIX"), data.closes("^IRX", live=False)
    m = data.metrics(symbol)
    if m is not None and m.get("ivx") == m.get("ivx") and m.get("ivx"):
        iv_default, iv_from = float(m["ivx"]), "tastytrade IVx"
    elif symbol == "SPY" and len(vix):
        iv_default, iv_from = float(vix.iloc[-1]) / 100, "VIX"
    else:
        iv_default, iv_from = rv, "realized vol"
    st.caption(f"Spot {spot:,.2f} {'live' if q else 'last close'}. IV from {iv_from}.")
    iv = st.number_input(
        "Implied vol, for pricing (%)", 1.0, 300.0, round(iv_default * 100, 1), 0.5,
    ) / 100
    sigma = st.number_input(
        "Realized vol, for the paths (%)", 1.0, 300.0, round(rv * 100, 1), 0.5,
        help="Defaults to 21-day realized.",
    ) / 100
    rate = st.number_input("Risk-free rate (%)", value=round(float(irx.iloc[-1]), 2) if len(irx) else 4.0,
                           step=0.25, help="Latest 13-week T-bill yield.") / 100
    div = st.number_input("Dividend yield (%)", 0.0, 20.0, 1.2, 0.1) / 100
    mu = st.number_input(
        "Drift (annual %)", value=round((rate - div) * 100, 2), step=0.5,
        help="Risk-neutral by default: r minus q.",
    ) / 100

    st.header("Simulation")
    model_name = st.radio("Model", list(MODELS))
    model = MODELS[model_name]
    jump = (3.0, -0.04, 0.05)
    block = 5
    if model == "jump":
        jump = (
            st.number_input("Jumps per year", 0.0, 50.0, 3.0, 0.5),
            st.number_input("Mean jump (%)", -30.0, 30.0, -4.0, 0.5) / 100,
            st.number_input("Jump size spread (%)", 0.0, 30.0, 5.0, 0.5) / 100,
        )
    elif model == "bootstrap":
        block = st.slider("Block length (sessions)", 1, 20, 5)
    n_paths = st.select_slider("Paths", [1000, 2500, 5000, 10000], value=2500)
    horizon = st.slider("Horizon (trading days)", 1, 252, 21)
    seed = int(st.number_input("Seed", 0, 99_999, 7))

history = symbol if len(px) > 750 else "SPY"
paths = simulate(model, spot, mu, sigma, horizon, n_paths, seed, jump, history, block)

theme.intro("Market scenarios", eyebrow="Scenarios",
            tag=f"{symbol}, {n_paths:,} paths, {horizon} sessions, {model_name.lower()}")

tab_paths, tab_pos, tab_vol, tab_size, tab_replay = st.tabs(
    ["Paths", "Position", "Vol edge", "Sizing", "Replay"]
)

# --- Paths ---------------------------------------------------------------------------------
with tab_paths:
    stats = sim.terminal_stats(paths)
    dd = sim.max_drawdown(paths)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Median end", f"{stats['median']:,.2f}", f"{stats['median'] / spot - 1:+.2%}",
              delta_color="off")
    c2.metric("Mean end", f"{stats['mean']:,.2f}", f"{stats['mean'] / spot - 1:+.2%}",
              delta_color="off")
    c3.metric("Finish higher", pct(stats["p_up"]))
    c4.metric("Median worst drawdown", f"{np.median(dd):.1%}", help="Peak to trough, per path.")

    with theme.card("fan"):
        theme.panel_head("Simulated paths", f"{n_paths:,} paths, {horizon} sessions")
        bands = sim.bands(paths)
        st.plotly_chart(charts.fan(paths, bands), width="stretch", config=NO_BAR)

    left, right = st.columns(2)
    with left, theme.card("terminal"):
        theme.panel_head("Price at horizon")
        st.plotly_chart(charts.histogram(
            paths[:, -1],
            [(spot, "spot", T["line_strong"]), (stats["median"], "median", T["fg"]),
             (stats["mean"], "mean", T["ink_2"])],
            "price at horizon"), width="stretch", config=NO_BAR)
        rows = "".join(
            f'<div class="bar-row" style="grid-template-columns: 5rem 1fr 4.5rem;">'
            f'<span class="name">{q}th</span><span></span><span class="num">{stats[f"p{q}"]:,.2f}</span></div>'
            for q in (5, 25, 50, 75, 95)
        )
        st.markdown(f'<div class="bar-table">{rows}</div>', unsafe_allow_html=True)

    with right, theme.card("touch"):
        theme.panel_head("Touch versus finish")
        level = st.number_input("Price level", value=float(round(spot * 0.95, 2)), step=1.0)
        touch = sim.touch_probability(paths, level)
        beyond = float((paths[:, -1] <= level).mean() if level < spot else (paths[:, -1] >= level).mean())
        a, b = st.columns(2)
        a.metric("Touches it", pct(touch))
        b.metric("Ends beyond it", pct(beyond))
        st.plotly_chart(charts.histogram(
            dd * 100, [(np.median(dd) * 100, "median", T["fg"]),
                       (np.percentile(dd, 5) * 100, "worst 5%", T["risk"])],
            "worst drawdown along the path (%)", height=240, bins=60), width="stretch", config=NO_BAR)

# --- Position ------------------------------------------------------------------------------
with tab_pos:
    c1, c2, c3 = st.columns([1.4, 1, 1])
    structures = pos.presets(spot)
    preset = c1.selectbox("Structure", list(structures), index=list(structures).index("Short strangle"))
    width = c2.number_input("Wing distance (% of spot)", 1.0, 40.0, 5.0, 0.5) / 100
    dte = int(c3.number_input("Days to expiry (trading)", 1, 504, max(horizon, 21)))
    seeded = pd.DataFrame([vars(leg) for leg in pos.presets(spot, width)[preset]])
    edited = st.data_editor(
        seeded, key=f"legs-{symbol}-{preset}-{width}", num_rows="dynamic", hide_index=True,
        width="stretch",
        column_config={
            "kind": st.column_config.SelectboxColumn("Kind", options=list(pos.KINDS), required=True),
            "strike": st.column_config.NumberColumn("Strike", format="%.2f",
                                                    help="Ignored for stock."),
            "qty": st.column_config.NumberColumn(
                "Quantity", step=1, help="Contracts, or 100-share lots. Negative is short."),
        },
    )
    legs = [pos.Leg(r.kind, float(r.strike or 0), float(r.qty))
            for r in edited.dropna(subset=["kind", "qty"]).itertuples() if r.qty]
    st.session_state["scenario_legs"], st.session_state["scenario_dte"] = legs, dte

    if not legs:
        st.info("Add a leg to see its profile.")
    else:
        h = min(horizon, dte)
        if horizon > dte:
            st.caption(f"Horizon capped at expiry, {dte} sessions.")
        S_h = paths[:, h]
        pnl = pos.pnl(legs, spot, S_h, dte, h, rate, iv, iv, div)
        cost = pos.premium(legs, spot, dte, rate, iv, div)
        var, cvar = sim.var_cvar(pnl)
        fair_paths = simulate("gbm", spot, rate - div, iv, h, n_paths, seed, jump, history, block)
        fair = pos.pnl(legs, spot, fair_paths[:, -1], dte, h, rate, iv, iv, div)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Premium", f"{abs(cost):,.0f}", "credit" if cost < 0 else "debit", delta_color="off",
                  delta_arrow="off")
        c2.metric("Expected P&L", money(pnl.mean()))
        c3.metric("Chance of profit", pct((pnl > 0).mean()))
        c4.metric("VaR 95%", money(-var), help="Loss exceeded in the worst 5% of paths.")
        c5.metric("Expected shortfall", money(-cvar), help="Average loss in the worst 5% of paths.")

        with theme.card("profile"):
            theme.panel_head("P&L profile", f"Priced at {iv:.1%} IV, paths at {sigma:.1%} realized")
            lo_, hi_ = min(S_h.min(), spot * 0.8), max(S_h.max(), spot * 1.2)
            grid = np.linspace(lo_, hi_, 300)
            at_h = pos.pnl(legs, spot, grid, dte, h, rate, iv, iv, div)
            at_exp = pos.pnl(legs, spot, grid, dte, dte, rate, iv, iv, div) if h < dte else None
            st.plotly_chart(charts.profile(grid, at_h, at_exp, S_h, spot, f"After {h} sessions"),
                            width="stretch", config=NO_BAR)
            st.caption("Flat vol across strikes, no costs.")

        left, right = st.columns([1.3, 1])
        with left, theme.card("pnl"):
            theme.panel_head("P&L distribution")
            st.plotly_chart(charts.histogram(
                pnl, [(0.0, "break even", T["line_strong"]), (pnl.mean(), "mean", T["fg"]),
                      (-var, "VaR 95%", T["risk"])], "P&L ($)"), width="stretch", config=NO_BAR)
            q = np.percentile(pnl, [5, 25, 50, 75, 95])
            st.caption(f"Quartiles {money(q[1])}, {money(q[2])}, {money(q[3])}. "
                       f"5th to 95th percentile {money(q[0])} to {money(q[4])}.")
        with right, theme.card("edge"):
            theme.panel_head("Expected P&L by assumption")
            rows = [
                (f"Paths at {iv:.1%} implied, risk-neutral", fair.mean()),
                (f"Paths at {sigma:.1%} realized, {model_name.lower()}", pnl.mean()),
                ("Difference", pnl.mean() - fair.mean()),
            ]
            st.markdown('<div class="bar-table">' + "".join(
                f'<div class="bar-row" style="grid-template-columns: 1fr 5rem;"><span class="name">{n}</span>'
                f'<span class="num">{money(v)}</span></div>' for n, v in rows) + "</div>",
                unsafe_allow_html=True)
            st.caption("Before costs.")

# --- Vol edge ------------------------------------------------------------------------------
with tab_vol:
    c1, c2, c3, c4 = st.columns(4)
    side = 1 if c1.segmented_control("Side", ["Sell", "Buy"], default="Sell") == "Buy" else -1
    kind = (c2.segmented_control("Kind", ["Call", "Put"], default="Call") or "Call").lower()
    moneyness = c3.number_input("Strike (% of spot)", 50.0, 150.0, 100.0, 1.0) / 100
    hedge_label = c4.selectbox("Hedge", ["Daily", "Every 2 sessions", "Weekly", "Unhedged"])
    every = {"Daily": 1, "Every 2 sessions": 2, "Weekly": 5, "Unhedged": 0}[hedge_label]
    step = pos.strike_step(spot)
    strike = round(spot * moneyness / step) * step

    out = pos.delta_hedged_pnl(paths, strike, rate, iv, div, kind, side, every) * pos.MULT
    entry = float(pos.bs_price(spot, strike, horizon / pos.TRADING_DAYS, rate, iv, div, kind)) * pos.MULT
    var, cvar = sim.var_cvar(out)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean P&L", money(out.mean()), f"premium {entry:,.0f}", delta_color="off", delta_arrow="off")
    c2.metric("Standard deviation", f"{out.std():,.0f}")
    c3.metric("Chance of profit", pct((out > 0).mean()))
    c4.metric("Expected shortfall", money(-cvar), help="Average loss in the worst 5% of paths.")

    left, right = st.columns(2)
    with left, theme.card("hedged"):
        theme.panel_head(f"{'Short' if side < 0 else 'Long'} {strike:g} {kind}, {hedge_label.lower()} hedge",
                         f"{iv:.1%} IV, {sigma:.1%} realized, {horizon} sessions")
        st.plotly_chart(charts.histogram(
            out, [(0.0, "break even", T["line_strong"]), (out.mean(), "mean", T["fg"]),
                  (-var, "VaR 95%", T["risk"])], "P&L per contract ($)"), width="stretch", config=NO_BAR)
    with right, theme.card("sweep"):
        theme.panel_head("P&L against realized vol", "Mean and one SD")
        if every == 0:
            st.info("Choose a hedge frequency to see the sweep.")
        else:
            vols, mean, sd = edge_sweep(spot, strike, rate, iv, div, kind, side, every, horizon,
                                        mu, seed)
            st.plotly_chart(charts.edge_curve(vols, mean, sd, iv), width="stretch", config=NO_BAR)

# --- Sizing --------------------------------------------------------------------------------
with tab_size:
    c1, c2, c3 = st.columns(3)
    p = c1.number_input("Win probability (%)", 1.0, 99.0, 55.0, 1.0) / 100
    b = c2.number_input("Payoff (win per 1 risked)", 0.05, 20.0, 1.0, 0.05)
    n_bets = int(c3.number_input("Bets per path", 10, 2000, 250, 10))
    kelly = po.kelly(p, po.from_payoff(1.0, b))
    f = st.slider("Stake per bet (% of bankroll)", 0.0, 99.0, round(kelly * 100, 1), 0.5) / 100
    W = sim.bet_paths(p, b, f, n_bets, min(n_paths, 5000), np.random.default_rng(seed))
    end = W[:, -1]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Kelly stake", f"{kelly:.1%}", f"half {kelly / 2:.1%}", delta_color="off", delta_arrow="off")
    c2.metric("Median bankroll", f"{np.median(end):,.2f}x")
    c3.metric("Mean bankroll", f"{end.mean():,.2f}x")
    c4.metric("Ends below start", pct((end < 1).mean()))
    c5.metric("50% drop from a peak", pct((sim.max_drawdown(W) <= -0.5).mean()),
              help=f"Below half the starting bankroll at some point: {pct((W.min(axis=1) <= 0.5).mean())}.")
    if kelly == 0:
        st.info("No edge at these odds: the Kelly stake is zero.")

    left, right = st.columns(2)
    with left, theme.card("growth"):
        theme.panel_head("Growth against stake", "Expected log growth per bet")
        top = min(0.99, max(3 * kelly, f * 1.5, 0.1))
        fs = np.linspace(0, top, 400)
        st.plotly_chart(charts.growth(fs, sim.growth_rate(p, b, fs),
                                      [(kelly, "Kelly"), (kelly / 2, "half"), (f, "yours")]),
                        width="stretch", config=NO_BAR)
    with right, theme.card("wealth"):
        theme.panel_head("Bankroll paths", "Log scale")
        st.plotly_chart(charts.wealth(W), width="stretch", config=NO_BAR)

# --- Replay --------------------------------------------------------------------------------
with tab_replay:
    spy, vix_all = closes("SPY"), closes("^VIX")
    legs = st.session_state.get("scenario_legs", [])
    dte = st.session_state.get("scenario_dte", max(horizon, 21))
    h = min(horizon, dte) if legs else horizon
    replayed, rows = {}, []
    for name, start in EPISODES:
        path = sim.replay(spy, start, h, spot)
        if path is None:
            continue
        replayed[name] = path
        v = sim.replay(vix_all, start, h, 1.0)
        prices = path.to_numpy()
        logret = np.diff(np.log(prices))
        row = {
            "Episode": name,
            "From": str(path.index[0]),
            "Return": prices[-1] / spot - 1,
            "Worst drawdown": float(sim.max_drawdown(prices[None, :])[0]),
            "Realized vol": float(logret.std(ddof=1) * math.sqrt(252)) if len(logret) > 1 else math.nan,
            "VIX change": float(v.iloc[-1] - 1) if v is not None else math.nan,
        }
        if legs:
            vol_path = iv * (v.to_numpy() if v is not None else np.ones(len(prices)))
            entry_v = pos.value(legs, np.array([spot]), dte, rate, iv, div)[0]
            marks = np.array([pos.value(legs, np.array([prices[t]]), dte - t, rate, vol_path[t], div)[0]
                              for t in range(len(prices))]) - entry_v
            row["Position P&L"], row["Worst P&L on the way"] = marks[-1], marks.min()
        rows.append(row)

    if not rows:
        st.info("SPY daily history does not cover these episodes.")
    else:
        names = [r["Episode"] for r in rows]
        chosen = st.selectbox("Highlight", names, index=names.index("Covid crash, Feb 2020")
                              if "Covid crash, Feb 2020" in names else 0)
        with theme.card("replay"):
            theme.panel_head(f"Historical episodes from {spot:,.2f}", f"SPY path over {h} sessions")
            st.plotly_chart(charts.replays(replayed, chosen, spot), width="stretch", config=NO_BAR)
            st.caption("Implied vol scaled by VIX over each window.")
        table = pd.DataFrame(rows).set_index("Episode")
        fmt = {"Return": "{:+.1%}", "Worst drawdown": "{:.1%}", "Realized vol": "{:.1%}",
               "VIX change": "{:+.0%}"}
        if legs:
            fmt |= {"Position P&L": "{:+,.0f}", "Worst P&L on the way": "{:+,.0f}"}
        with theme.card("replay-table"):
            theme.panel_head("Episodes", "Position from the Position tab" if legs else "")
            st.dataframe(table.style.format(fmt, na_rep=""), width="stretch")
