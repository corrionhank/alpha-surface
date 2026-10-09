# CLAUDE.md

Alpha Surface: an options and volatility analytics dashboard on live tastytrade data, with Yahoo
Finance for history. Shows implied against realized vol by name and by contract, chains, a
screener, and stores every pull in DuckDB over Parquet for backtests. Informs trade decisions;
never predicts or trades.

## Architecture

```
provider APIs -> collector.feed (gateway) -> caller, at once
                                          -> storage (Parquet + DuckDB), append-only
derive (pure functions) <- pages and CLIs
```

Details: `docs/architecture.md`. Tables: `docs/schema.md`. Formulas: `docs/formulas.md`.
Decisions: `docs/decisions.md`.

## Layout

```
src/alphasurface/
  config.py         settings; secrets from .env, paths from config/config.toml or ALPHASURFACE_DATA_DIR
  collector/        tasty (session, DXLink streamer), chains (providers), feed (gateway),
                    reference (fund data, news, calendar), scan and alerts, collector CLIs
  storage/          writer, reader, reference tables, DuckDB views
  derive/           Black-Scholes, implied vol, contract metrics, market state, scanner rules,
                    simulation, sentiment, pot odds
  present/          streamlit_app.py (entry), one module per page, theme, header, data access
tests/              pytest, no network (conftest blocks tastytrade and Yahoo)
studies/            standalone research, run with make study
config/             symbols.toml, *.example.toml (config.toml and scans.toml are gitignored)
deploy/             launchd and systemd schedules, deploy/README.md
docs/               architecture, schema, formulas, dashboard, scanner, decisions, ai-policy
data/               gitignored: Parquet, market.duckdb, watchlists, alert state
```

## Commands

`make` lists every target. Common: `make install`, `make run`, `make check` (lint, types,
tests), `make cov`, `make collect`, `make collect-bars`, `make scan ARGS="--list"`.

## Rules

`.claude/Development-Principles.md`, `docs/ai-policy.md`, `CONTRIBUTING.md`. Read-only: never
touch order entry. Secrets only in `.env`.
