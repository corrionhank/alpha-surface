"""yfinance OHLCV collector.

Pulls 1h / 1d bars for the tracked index/ETF universe and writes them to the
Parquet lake. This is the first working slice of the collector→storage pipeline;
tastytrade metrics/chains come later. yfinance is free and unmetered, so a modest
seed pull on first run is fine (Principle 6: seed history early).

Run:  python -m collector.yfinance_collector --interval 1h --period 1mo
"""

from __future__ import annotations

import argparse

import pandas as pd
import yfinance as yf

from config import Config, load_config
from storage import schema, writer

# yfinance caps 1h history at ~730d/request; default seed windows kept modest.
DEFAULT_PERIOD = {"1h": "1mo", "1d": "1y"}


def fetch_ohlcv(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """Fetch one symbol from yfinance and normalize to the ohlcv schema (UTC ts)."""
    raw = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if raw.empty:
        return pd.DataFrame(columns=schema.OHLCV_COLUMNS)

    ts = pd.to_datetime(raw.index)
    ts = ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")

    out = pd.DataFrame(
        {
            "ts": ts,
            "symbol": symbol,
            "interval": interval,
            "open": raw["Open"].to_numpy(dtype="float64"),
            "high": raw["High"].to_numpy(dtype="float64"),
            "low": raw["Low"].to_numpy(dtype="float64"),
            "close": raw["Close"].to_numpy(dtype="float64"),
            "volume": raw["Volume"].fillna(0).to_numpy(dtype="int64"),
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def collect(
    config: Config,
    symbols: list[str] | None = None,
    interval: str = "1h",
    period: str | None = None,
) -> dict[str, int]:
    """Fetch each symbol, write to Parquet, refresh views. Returns rows per symbol."""
    symbols = symbols or config.equities()
    period = period or DEFAULT_PERIOD.get(interval, "1mo")

    written: dict[str, int] = {}
    for symbol in symbols:
        df = fetch_ohlcv(symbol, interval, period)
        written[symbol] = writer.write_ohlcv(df, config)

    with schema.connect(config, persistent=True) as conn:
        schema.ensure_views(conn, config)  # register/refresh views in market.duckdb
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect yfinance OHLCV into the Parquet lake.")
    parser.add_argument("--interval", default="1h", help="bar interval: 1h or 1d")
    parser.add_argument("--period", default=None, help="yfinance lookback (e.g. 5d, 1mo, 1y)")
    parser.add_argument(
        "--symbols", default=None, help="comma-separated override, e.g. SPY,QQQ"
    )
    args = parser.parse_args()

    config = load_config()
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    result = collect(config, symbols=symbols, interval=args.interval, period=args.period)

    total = sum(result.values())
    print(f"Collected {args.interval} bars → {config.parquet_dir}/ohlcv")
    for sym, n in result.items():
        print(f"  {sym:6s} {n:>6d} rows")
    print(f"  {'TOTAL':6s} {total:>6d} rows")


if __name__ == "__main__":
    main()
