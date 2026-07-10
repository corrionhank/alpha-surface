"""rich terminal snapshot of stored OHLCV — a fast eyeball check on the data.

Run:  python -m present.terminal --symbol SPY --interval 1h --tail 12
"""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from config import load_config
from present.summary import summarize
from storage import reader, schema


def render(symbol: str = "SPY", interval: str = "1h", tail: int = 12) -> None:
    config = load_config()
    console = Console()

    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, symbol, interval, tail=tail)

    if df.empty:
        console.print(
            f"[yellow]No {interval} data for {symbol}.[/] "
            f"Run: [bold]python -m collector.yfinance_collector --interval {interval}[/]"
        )
        return

    s = summarize(df)
    arrow = "▲" if s["change_abs"] >= 0 else "▼"
    color = "green" if s["change_abs"] >= 0 else "red"
    console.print(
        f"\n[bold]{s['symbol']}[/] {s['interval']}   "
        f"[{color}]{s['last']:.2f} {arrow} {s['change_abs']:+.2f} "
        f"({s['change_pct']:+.2f}%)[/]   "
        f"window {s['window_change_pct']:+.2f}%   "
        f"RV≈{s['rv_annualized_pct']:.1f}%   "
        f"[dim]{s['bars']} bars[/]"
    )

    table = Table(title=f"Last {len(df)} bars (UTC)")
    table.add_column("ts", style="cyan", no_wrap=True)
    for col in ("open", "high", "low", "close"):
        table.add_column(col, justify="right")
    table.add_column("volume", justify="right", style="dim")

    for _, r in df.iterrows():
        table.add_row(
            r["ts"].strftime("%Y-%m-%d %H:%M"),
            f"{r['open']:.2f}",
            f"{r['high']:.2f}",
            f"{r['low']:.2f}",
            f"{r['close']:.2f}",
            f"{int(r['volume']):,}",
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="rich terminal view of stored OHLCV.")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--tail", type=int, default=12)
    args = parser.parse_args()
    render(args.symbol.upper(), args.interval, args.tail)


if __name__ == "__main__":
    main()
