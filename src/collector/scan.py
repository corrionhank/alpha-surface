"""Scan many option chains through the market-data gateway, then report and alert.

    python -m collector.scan --preset rich --symbols SPY,QQQ,IWM
    python -m collector.scan --saved index_rich           # a scan from config/scans.toml
    python -m collector.scan --list                       # presets and saved scans

Every chain and daily bar fetched goes through collector.feed, so it is returned for the scan
and stored for history in the same step. The scan compares against the latest stored quote of
each contract from before this run. New hits are notified only if [notify] is enabled in
config/config.toml. Rules and thresholds: docs/scanner.md.
"""

from __future__ import annotations

import argparse
import logging
import time
import tomllib
from dataclasses import dataclass, field, replace

import pandas as pd

from collector import alerts, feed
from config import CONFIG_DIR, Config, load_config
from derive import scan as sc
from storage import reader, schema

log = logging.getLogger(__name__)

UNIVERSE = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "AMZN", "META", "MSFT"]


@dataclass
class Result:
    preset: sc.Preset
    scanned_at: pd.Timestamp
    hits: pd.DataFrame
    frame: pd.DataFrame
    context: pd.DataFrame
    new: set[str] = field(default_factory=set)
    due: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    contracts: int = 0


def pick_expiries(expiries: list[str], f: sc.Filters, now: pd.Timestamp, cap: int) -> list[str]:
    """Only the expiries the filter can use, nearest first, at most cap: no point pulling a
    two-year LEAP for a 20 to 45 day scan."""
    today = sc._ny_date(now)
    out = []
    for e in expiries:
        dte = (pd.Timestamp(e) - today).days
        if (dte == 0) if f.zero_dte else (f.dte_min <= dte <= f.dte_max):
            out.append(e)
    return out[:cap]


def stored_rate(conn) -> float:
    bar = reader.latest_bar(conn, "^IRX", "1d")
    return float(bar["close"]) / 100 if bar is not None else 0.04


def run_scan(symbols: list[str], preset_key: str, source: str = "yfinance",
             filters: sc.Filters | None = None, params: dict | None = None,
             r: float | None = None, q: float = 0.0, max_expiries: int = 4,
             config: Config | None = None, conn=None, throttle: float = 0.4,
             record: bool = True, background: bool = False) -> Result:
    """Fetch every symbol's chain and history through the gateway, run one preset, record the
    hits for alerting. Synthetic chains read history from the store only, never the network.
    background=True lets a page return before a first-time history backfill finishes writing."""
    config = config or load_config()
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    preset = sc.PRESETS[preset_key]
    f = filters or preset.filters
    started = pd.Timestamp.now(tz="UTC")
    r = stored_rate(conn) if r is None else r

    chains, history, errors = [], {}, {}
    for i, symbol in enumerate(symbols):
        if i and throttle and source != "synthetic":
            time.sleep(throttle)  # be gentle with a free, rate-limited vendor
        try:
            wanted = pick_expiries(feed.expirations(source, symbol), f, started, max_expiries)
            if not wanted:
                errors[symbol] = "no expiries in the date range"
                continue
            chains.append(feed.chain(source, symbol, wanted, config=config))
        except Exception as exc:  # one dead symbol must not end the scan
            errors[symbol] = str(exc) or type(exc).__name__
            continue
        if source == "synthetic":
            history[symbol] = reader.get_ohlcv(conn, symbol, "1d")
        else:
            history[symbol] = feed.daily(symbol, config=config, conn=conn, background=background)

    try:
        if not chains:
            empty = pd.DataFrame(columns=sc.HIT_COLUMNS)
            return Result(preset, started, empty, pd.DataFrame(), pd.DataFrame(), errors=errors)
        chain = pd.concat(chains, ignore_index=True)
        prev = reader.previous_chain(conn, symbols, started, source=source)
        frame, ctx = sc.prepare(chain, started, r, q, f, prev, history)
        hits = sc.run(preset, frame, ctx, history, params)
    finally:
        if own:
            conn.close()

    result = Result(preset, started, hits, frame, ctx, errors=errors, contracts=len(chain))
    if record and source != "synthetic":
        ids = [sc.hit_id(preset.key, h) for _, h in hits.iterrows()]
        result.new, result.due = alerts.update(config, preset.key, ids,
                                               float(alerts.settings()["cooldown_hours"]))
    return result


def saved_scans() -> dict:
    for name in ("scans.toml", "scans.example.toml"):
        path = CONFIG_DIR / name
        if path.exists():
            return tomllib.loads(path.read_text())
    return {}


def _parse_range(text: str) -> tuple[int, int]:
    lo, _, hi = text.partition("-")
    return int(lo), int(hi or lo)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Scan option chains for setups; store every pull.")
    ap.add_argument("--preset", choices=list(sc.PRESETS), default="rich")
    ap.add_argument("--symbols", default=",".join(UNIVERSE))
    ap.add_argument("--source", default="yfinance")
    ap.add_argument("--saved", help="name of a scan in config/scans.toml")
    ap.add_argument("--dte", help="days to expiry range, e.g. 20-45; 0 for same-day only")
    ap.add_argument("--max-expiries", type=int, default=4)
    ap.add_argument("--dividend", type=float, default=0.0, help="dividend yield, percent")
    ap.add_argument("--no-notify", action="store_true", help="never notify, even if enabled")
    ap.add_argument("--list", action="store_true", help="list presets and saved scans")
    args = ap.parse_args()

    if args.list:
        for p in sc.PRESETS.values():
            print(f"{p.key:9s} {p.name}: {p.about}")
        for name, s in saved_scans().items():
            print(f"saved     {name}: {s.get('preset')} on {', '.join(s.get('symbols', []))}")
        return

    spec = saved_scans().get(args.saved, {}) if args.saved else {}
    if args.saved and not spec:
        raise SystemExit(f"no saved scan {args.saved!r} in config/scans.toml")
    preset = sc.PRESETS[spec.get("preset", args.preset)]
    filters = replace(preset.filters, **spec.get("filters", {}))
    if args.dte:
        lo, hi = _parse_range(args.dte)
        filters = replace(filters, zero_dte=hi == 0, dte_min=lo, dte_max=hi)
    symbols = spec.get("symbols") or [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    res = run_scan(symbols, preset.key, spec.get("source", args.source), filters,
                   spec.get("params"), q=args.dividend / 100,
                   max_expiries=int(spec.get("max_expiries", args.max_expiries)), throttle=0.4)

    print(f"{preset.name}: {len(res.hits)} hit(s) over {res.contracts:,} contracts, "
          f"{len(symbols) - len(res.errors)} of {len(symbols)} symbols, {res.scanned_at:%Y-%m-%d %H:%M} UTC")
    for sym, err in res.errors.items():
        print(f"  skipped {sym}: {err}")
    for _, h in res.hits.head(25).iterrows():
        tag = "new " if sc.hit_id(preset.key, h) in res.new else "    "
        print(f"  {tag}{sc.describe(h):28s} {h['score']:7.2f}  {h['reason']}")

    if res.due and not args.no_notify:
        due = res.hits[[sc.hit_id(preset.key, h) in res.due for _, h in res.hits.iterrows()]]
        lines = [f"{sc.describe(h)}: {h['reason']}" for _, h in due.head(3).iterrows()]
        used = alerts.send(f"{preset.name}: {len(due)} new hit{'s' * (len(due) != 1)}", "\n".join(lines))
        if used:
            print(f"notified via {', '.join(used)}")


if __name__ == "__main__":
    main()
