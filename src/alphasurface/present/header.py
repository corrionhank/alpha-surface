"""The market bar under the nav on every app page: the tape, market status, tools, account menu.

With tastytrade credentials the tape is live from the streamer (collector.tasty) and refreshes
every 20 seconds during the session; without them, or for a symbol the streamer does not carry,
it falls back to the last stored daily close.
"""

from __future__ import annotations

import logging

import pandas as pd
import streamlit as st

from alphasurface.present import auth, data, theme, tools
from alphasurface.storage import reader

log = logging.getLogger(__name__)

# Tape order: index ETFs, then implied vol, then the rates and haven legs. Stored symbols use
# Yahoo's carets; the streamer's index symbols do not.
_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "^VIX", "^VIX1D", "^VIX3M", "TLT", "GLD"]
ET = "America/New_York"


@st.cache_data(ttl=300)
def _stored() -> dict[str, dict]:
    out = {}
    for symbol in _SYMBOLS:
        df = reader.get_ohlcv(data.conn(), symbol, "1d", tail=2)
        if len(df) < 2:
            continue
        last, prev = float(df["close"].iloc[-1]), float(df["close"].iloc[-2])
        out[symbol] = {"last": last, "prev": prev, "ts": df["ts"].iloc[-1]}
    return out


@st.cache_data(ttl=15, show_spinner=False)
def _live() -> dict[str, dict]:
    """Live marks and prior closes from the streamer. Empty when unavailable."""
    from alphasurface.collector import tasty

    if not tasty.ready():
        return {}
    try:
        rows = tasty.stream_quotes([s.lstrip("^") for s in _SYMBOLS], wait=3.0)
    except Exception:  # the bar must render even when the feed is down
        log.warning("live tape unavailable", exc_info=True)
        return {}
    out = {}
    for symbol in _SYMBOLS:
        row = rows.get(symbol.lstrip("^"))
        if row is None:
            continue
        last, prev = tasty.mark(row), row["prev_close"]
        if last == last and prev == prev and prev > 0:
            out[symbol] = {"last": last, "prev": prev}
    return out


market_open = data.market_open


def _tape(quotes: dict[str, dict]) -> str:
    up, down = theme.polarity()
    cells = []
    for symbol in _SYMBOLS:
        q = quotes.get(symbol)
        if q is None:
            continue
        chg = (q["last"] / q["prev"] - 1) * 100
        cells.append(
            f'<span class="tk"><b>{symbol.lstrip("^")}</b>{q["last"]:,.2f} '
            f'<span style="color:{up if chg >= 0 else down}">{chg:+.2f}%</span></span>'
        )
    return "".join(cells)


def _strip() -> None:
    """Tape and session state. Runs as a fragment that reruns alone every 20 seconds in the
    session, so the quotes move without rerunning the page."""
    stored = _stored()
    live = _live()
    is_open = market_open()
    # In the session the live mark wins; outside it the official close does, so an after-hours
    # move never reads as the day's change.
    quotes = {**stored, **live} if is_open else {**live, **stored}
    asof = max((q["ts"] for q in stored.values()), default=None)
    if live and is_open:
        source = f"{data.feed_label() or 'tastytrade'}, {pd.Timestamp.now(tz=ET):%-I:%M:%S %p} ET"
    elif asof is not None:
        source = f"Close {pd.Timestamp(asof).tz_convert(ET):%b %-d}"
    else:
        source = ""
    st.markdown(
        '<div style="display:flex;align-items:center;gap:24px;min-width:0">'
        f'<div class="tape" style="flex:1;min-width:0">{_tape(quotes)}</div>'
        f'<div class="mkt" style="flex:none"><span class="state">'
        f'<i class="dot{" open" if is_open else ""}"></i>'
        f"{'Market open' if is_open else 'Market closed'}</span><span>{source}</span></div></div>",
        unsafe_allow_html=True,
    )


def bar() -> None:
    """Sticky strip: tape and session state left, the tools and account menus right. Only the
    strip refreshes; the menus and the dialogs they open stay out of the fragment."""
    with st.container(key="marketbar"):
        strip, kit, account = st.columns([8.4, 0.8, 0.9], vertical_alignment="center")
        with strip:
            st.fragment(_strip, run_every=20 if market_open() else None)()
        with kit.popover("Tools", icon=":material/calculate:", width="stretch"):
            st.button(
                "Option pricer",
                on_click=tools.request,
                args=("pricer",),
                type="tertiary",
                width="stretch",
            )
            st.button(
                "Pot odds", on_click=tools.request, args=("odds",), type="tertiary", width="stretch"
            )
        with account.popover("Account", icon=":material/account_circle:", width="stretch"):
            st.caption(f"Signed in as {auth.user()}")
            if st.button("Sign out", width="stretch"):
                auth.sign_out()
                st.rerun()
    tools.open_requested()
