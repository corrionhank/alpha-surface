"""yfinance OHLCV collector. Pulls 1h/1d bars for the tracked universe into Parquet.

Daily bars default to every symbol a page reads (Config.universe(): index ETFs, single names,
the vol complex, cross-asset vol, macro ETFs, Treasury yields, futures), so the scheduled top-up
keeps every page current. Hourly bars default to the index ETFs and single names, the only
series pages read intraday.

Run: python -m alphasurface.collector.yfinance_collector --interval 1d --period 5d
"""

from __future__ import annotations

import argparse

import pandas as pd
import yfinance as yf

from alphasurface.config import Config, load_config
from alphasurface.storage import schema, writer

# 1h is capped at ~730 days by Yahoo; daily goes back decades.
DEFAULT_PERIOD = {"1h": "2y", "1d": "10y"}


def fetch_ohlcv(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """Fetch one symbol and normalize to the ohlcv schema with UTC timestamps."""
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
    out = schema.normalize_daily(out)  # Yahoo stamps Cboe indices at Chicago midnight
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def default_symbols(config: Config, interval: str) -> list[str]:
    if interval == "1d":
        return config.universe()
    return list(dict.fromkeys(config.equities() + config.single_names()))


def collect(
    config: Config,
    symbols: list[str] | None = None,
    interval: str = "1h",
    period: str | None = None,
) -> dict[str, int]:
    """Fetch each symbol, write once, refresh views. Returns rows per symbol."""
    symbols = symbols or default_symbols(config, interval)
    period = period or DEFAULT_PERIOD.get(interval, "1mo")

    written: dict[str, int] = {}
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        df = fetch_ohlcv(symbol, interval, period)
        written[symbol] = len(df)
        if not df.empty:
            frames.append(df)
    if frames:
        writer.write_ohlcv(pd.concat(frames, ignore_index=True), config)

    with schema.connect(config, persistent=True) as conn:
        schema.ensure_views(conn, config)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect yfinance OHLCV into Parquet.")
    parser.add_argument("--interval", default="1h", help="1h or 1d")
    parser.add_argument("--period", default=None, help="yfinance lookback, e.g. 5d, 1mo, 10y")
    parser.add_argument("--symbols", default=None, help="comma-separated override, e.g. SPY,QQQ")
    args = parser.parse_args()

    config = load_config()
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    result = collect(config, symbols=symbols, interval=args.interval, period=args.period)

    total = sum(result.values())
    print(f"Collected {args.interval} bars into {config.parquet_dir}/ohlcv")
    for sym, n in result.items():
        print(f"  {sym:6s} {n:>6d} rows")
    print(f"  {'TOTAL':6s} {total:>6d} rows")


if __name__ == "__main__":
    main()
