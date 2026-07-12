# CLAUDE.md

Personal market analytics dashboard. Aggregates options vol, expected moves, VRP, regime, and cross-asset vol from the tastytrade API (free real-time for funded accounts) into one terminal/browser view. Informs trade decisions; never predicts or trades.

## Architecture

```
collector  →  storage (DuckDB + Parquet)  →  derive  →  present
```

- **collector**: scheduled pulls, writes Parquet. Modules: tastytrade, yfinance, FRED, vix_utils, news.
- **storage**: DuckDB views over Parquet, schema in `docs/schema.md`.
- **derive**: own IVR/IVP, VRP percentile, expected-move cone, regime flags.
- **present**: `rich` terminal and Streamlit LAN dashboard.

Schedules: hourly (market hours) plus EOD via `systemd` timers, see `systemd/README.md`.

## Layout

```
src/{collector,storage,derive,present}/
config/config.toml          secrets + paths (gitignored; copy from config.example.toml)
config/symbols.toml         tracked universe + FRED series
data/                       gitignored, Parquet + market.duckdb
docs/schema.md              DuckDB table DDL, finalize before first collector run
docs/open-decisions.md      5 architectural decisions, resolve #1 and #5 first
systemd/                    service + timer unit files (Ubuntu / Linux host host)
notebooks/
```

Install: `pip install -e ".[notebooks,dev]"`

## Rules

`.claude/Development-Principles.md`, `docs/ai-policy.md`

## References

Full project brief, formulas, data sources, storage strategy: `Project-Breif.md`
