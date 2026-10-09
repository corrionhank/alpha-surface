"""One symbol, three spellings: the store's, the tastytrade streamer's, and the one people read.

    store      what bars are saved under and what Yahoo understands: SPY, ^VIX, ^GSPC, ES=F
    tasty      the tastytrade instrument symbol for REST calls: SPY, VIX, SPX, /ES
    streamer   the DXLink symbol for live events: SPY, VIX, SPX, /ESZ26:XCME (front month)
    display    what a page shows: SPY, VIX, SPX, /ES

Every page and collector converts through here, so an index or a future typed in any of its
spellings lands on the same stored series and the same live quote. Futures resolve to the
front month on tastytrade, looked up once a day; Yahoo's continuous contract backs their history.
"""

from __future__ import annotations

import logging
import re
import threading
import time

log = logging.getLogger(__name__)

# Store symbol -> (display and tastytrade symbol, description). The streamer uses the display
# name for indices; one it does not carry simply has no live quote.
INDICES = {
    "^GSPC": ("SPX", "S&P 500 Index"),
    "^NDX": ("NDX", "Nasdaq-100 Index"),
    "^RUT": ("RUT", "Russell 2000 Index"),
    "^DJI": ("DJI", "Dow Jones Industrial Average"),
    "^VIX": ("VIX", "Cboe Volatility Index"),
    "^VIX1D": ("VIX1D", "Cboe 1-Day Volatility Index"),
    "^VIX9D": ("VIX9D", "Cboe 9-Day Volatility Index"),
    "^VIX3M": ("VIX3M", "Cboe 3-Month Volatility Index"),
    "^VIX6M": ("VIX6M", "Cboe 6-Month Volatility Index"),
    "^VVIX": ("VVIX", "Cboe VIX of VIX Index"),
    "^VXN": ("VXN", "Cboe Nasdaq-100 Volatility Index"),
    "^SKEW": ("SKEW", "Cboe S&P 500 Skew Index"),
    "^MOVE": ("MOVE", "ICE BofA MOVE Index"),
    "^GVZ": ("GVZ", "Cboe Gold Volatility Index"),
    "^OVX": ("OVX", "Cboe Crude Oil Volatility Index"),
    "^IRX": ("IRX", "13-Week Treasury Bill Yield"),
    "^TNX": ("TNX", "10-Year Treasury Yield"),
}
_ALIASES = {"SPX": "^GSPC", "^SPX": "^GSPC", "GSPC": "^GSPC", "DJX": "^DJI"}
_BY_DISPLAY = {display: store for store, (display, _) in INDICES.items()}

# Futures root -> description. Store form is Yahoo's continuous contract, ES=F.
FUTURES = {
    "/ES": "E-mini S&P 500",
    "/NQ": "E-mini Nasdaq-100",
    "/RTY": "E-mini Russell 2000",
    "/YM": "E-mini Dow",
    "/CL": "Crude Oil",
    "/NG": "Natural Gas",
    "/GC": "Gold",
    "/SI": "Silver",
    "/ZN": "10-Year T-Note",
    "/ZB": "30-Year T-Bond",
}
_MONTH = re.compile(r"^/([A-Z0-9]{1,3}?)[FGHJKMNQUVXZ]\d{1,2}(?::\w+)?$")  # /ESZ26, /ESZ6:XCME


def _norm(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _root(sym: str) -> str | None:
    """The futures root of /ES, /ESZ26, /ESZ26:XCME or ES=F, else None."""
    if sym.endswith("=F"):
        sym = "/" + sym[:-2]
    if not sym.startswith("/"):
        return None
    if sym.split(":")[0] in FUTURES:
        return sym.split(":")[0]
    m = _MONTH.match(sym)
    return f"/{m.group(1)}" if m and f"/{m.group(1)}" in FUTURES else sym.split(":")[0]


def kind(symbol: str) -> str:
    """equity, index or future."""
    sym = _norm(symbol)
    if sym.startswith("/") or sym.endswith("=F"):
        return "future"
    if sym.startswith("^") or sym in _ALIASES or sym in _BY_DISPLAY:
        return "index"
    return "equity"


def to_store(symbol: str) -> str:
    """The stored (Yahoo) spelling of any input: vix -> ^VIX, SPX -> ^GSPC, /ES -> ES=F."""
    sym = _norm(symbol)
    if not sym:
        return ""
    if sym in _ALIASES:
        return _ALIASES[sym]
    if sym in _BY_DISPLAY:
        return _BY_DISPLAY[sym]
    if kind(sym) == "future":
        root = _root(sym)
        return f"{root[1:]}=F" if root else sym
    return sym


def display(symbol: str) -> str:
    """What a page shows: ^VIX -> VIX, ^GSPC -> SPX, ES=F -> /ES."""
    sym = to_store(symbol)
    if sym in INDICES:
        return INDICES[sym][0]
    if sym.endswith("=F"):
        return "/" + sym[:-2]
    return sym.lstrip("^")


def to_tasty(symbol: str) -> str:
    """The tastytrade instrument symbol for REST calls (metrics, chains, search): SPX, /ES."""
    return display(symbol)


def describe(symbol: str) -> str:
    """A built-in name for indices and futures roots; empty for anything else."""
    sym = to_store(symbol)
    if sym in INDICES:
        return INDICES[sym][1]
    return FUTURES.get(display(sym), "")


def to_streamer(symbol: str) -> str | None:
    """The DXLink symbol for live data. A future resolves to its front month through tastytrade
    (cached a day); None when that lookup is unavailable."""
    sym = to_store(symbol)
    if kind(sym) != "future":
        return display(sym)
    return front_month(display(sym))


_front: dict[str, tuple[float, str | None]] = {}
_front_lock = threading.Lock()
FRONT_TTL = 24 * 3600


def front_month(root: str) -> str | None:
    """The active contract's streamer symbol for a futures root (/ES -> /ESZ26:XCME), or None
    without tastytrade or when the root is unknown. Failures are cached for an hour, not a day,
    so a feed outage does not hide futures until tomorrow."""
    now = time.monotonic()
    with _front_lock:
        hit = _front.get(root)
        if hit and now - hit[0] < (FRONT_TTL if hit[1] else 3600):
            return hit[1]
    from alphasurface.collector import tasty

    value = None
    if tasty.ready():
        try:
            value = tasty.front_month(root.lstrip("/"))
        except Exception:
            log.warning("front month for %s unavailable", root, exc_info=True)
    with _front_lock:
        _front[root] = (now, value)
    return value
