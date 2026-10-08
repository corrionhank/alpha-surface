"""tastytrade collector: market metrics and option chains into the store.

    python -m collector.tastytrade_collector                 # metrics for the universe, chains for SPY, QQQ
    python -m collector.tastytrade_collector --chains SPY --expiries 6
    python -m collector.tastytrade_collector --no-chains     # metrics only

Market metrics (IV rank and percentile, IVx, 30/60/90-day HV, per-expiry IV) go to the
market_metrics and iv_term tables; chains go through collector.feed into option_chain. Every row
is stamped with when it was collected, append-only, so IV history builds up from today: it
cannot be backfilled later. Read-only: nothing here can place or change an order.
"""

from __future__ import annotations

import argparse
import logging
import math

import pandas as pd

from config import Config, load_config

log = logging.getLogger(__name__)

SOURCE = "tastytrade"
SINGLE_NAMES = ["AAPL", "NVDA", "MSFT", "AMZN", "META", "TSLA", "GOOGL"]


def _f(x) -> float:
    return math.nan if x is None or x == "" else float(x)


def _pct(x) -> float:
    """tastytrade quotes some vols in percent (15.41); store everything as a decimal (0.1541)."""
    v = _f(x)
    return v / 100 if v == v else v


def metrics_frames(items: list, collected_at: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per symbol for market_metrics, one per symbol and expiry for iv_term.

    Units, normalized: every vol and rank is a decimal (0.15 = 15%); iv_hv_diff stays in vol
    points as tastytrade reports it. Two IV ranks are kept because tastytrade publishes two
    (its own, and one sourced from TOS); iv_rank is the one it marks as primary.
    """
    rows, term = [], []
    for m in items:
        earn = m.earnings
        rows.append({
            "collected_at": collected_at, "source": SOURCE, "symbol": m.symbol,
            "ivx": _f(m.implied_volatility_index),
            "ivx_5d_change": _f(m.implied_volatility_index_5_day_change),
            "iv_rank": _f(m.implied_volatility_index_rank),
            "iv_rank_source": m.implied_volatility_index_rank_source,
            "iv_rank_tw": _f(m.tw_implied_volatility_index_rank),
            "iv_rank_tos": _f(m.tos_implied_volatility_index_rank),
            "iv_percentile": _f(m.implied_volatility_percentile),
            "iv30": _pct(m.implied_volatility_30_day),
            "hv30": _pct(m.historical_volatility_30_day),
            "hv60": _pct(m.historical_volatility_60_day),
            "hv90": _pct(m.historical_volatility_90_day),
            "iv_hv_diff": _f(m.iv_hv_30_day_difference),
            "liquidity_rating": _f(m.liquidity_rating),
            "beta": _f(m.beta),
            "corr_spy_3m": _f(m.corr_spy_3month),
            "earnings_date": pd.Timestamp(earn.expected_report_date)
            if earn is not None and earn.expected_report_date else pd.NaT,
            "earnings_time": earn.time_of_day if earn is not None else None,
            "dividend_ex_date": pd.Timestamp(m.dividend_ex_date) if m.dividend_ex_date else pd.NaT,
            "updated_at": pd.Timestamp(m.updated_at),
        })
        for e in m.option_expiration_implied_volatilities or []:
            term.append({
                "collected_at": collected_at, "source": SOURCE, "symbol": m.symbol,
                "expiry": e.expiration_date.isoformat(), "settlement": e.settlement_type,
                "chain_type": e.option_chain_type, "iv": _f(e.implied_volatility),
            })
    return pd.DataFrame(rows), pd.DataFrame(term)


def collect_metrics(symbols: list[str], config: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    from collector import feed

    return feed.metrics(symbols, config=config)


def collect_chains(symbols: list[str], expiries: int, config: Config) -> dict[str, int]:
    from collector import feed

    out = {}
    for sym in symbols:
        listed = feed.expirations(SOURCE, sym)
        # Skip a same-day expiry after the close: nothing left to price.
        wanted = [e for e in listed if pd.Timestamp(e).date() >= pd.Timestamp.now(tz="America/New_York").date()]
        frame = feed.chain(SOURCE, sym, wanted[:expiries], config=config)
        out[sym] = len(frame)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect tastytrade market metrics and chains.")
    parser.add_argument("--symbols", default=None, help="metrics universe, comma-separated")
    parser.add_argument("--chains", default="SPY,QQQ", help="chains to store, comma-separated")
    parser.add_argument("--expiries", type=int, default=6, help="nearest expiries per chain")
    parser.add_argument("--no-chains", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = load_config()
    universe = ([s.strip().upper() for s in args.symbols.split(",")] if args.symbols
                else list(dict.fromkeys(config.equities() + SINGLE_NAMES)))
    metrics, term = collect_metrics(universe, config)
    print(f"market_metrics: {len(metrics)} symbols, iv_term: {len(term)} expiries")
    if not args.no_chains:
        for sym, n in collect_chains([s.strip().upper() for s in args.chains.split(",")],
                                     args.expiries, config).items():
            print(f"option_chain: {sym} {n} contracts")


if __name__ == "__main__":
    main()
