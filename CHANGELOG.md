# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Nothing has been tagged yet, so
everything is under Unreleased, with the date each piece landed.

## [Unreleased]

### Added

- Collector and store for Yahoo daily and hourly bars: Parquet files with DuckDB views,
  idempotent upserts, UTC timestamps (2026-07-10).
- Multipage Streamlit app with TradingView Lightweight charts and an in-app docs page
  (2026-07-11).
- Black-Scholes model with Greeks, and pot odds (2026-07-13).
- Write-through market-data gateway, `collector.feed`: every pull is returned to the caller and
  appended to the store in the same step (2026-10-07).
- Options page: straddle board per expiry and single-contract metrics (own IV and Greeks,
  intrinsic and extrinsic, extrinsic per day, priced vs realized vol, seller yield and APY)
  (2026-10-07).
- Screener page and CLI: eight presets, saved scans, the options-or-underlying comparison over
  simulated paths, opt-in macOS and ntfy alerts (2026-10-07).
- Dashboard: KPI band, SPY and QQQ charts, implied vol panel and VIX term curve, fear and greed
  lens, fund fundamentals and holdings, economic calendar and news, stored write-through
  (2026-10-07).
- Landing page and a mock sign-in that gates the app pages (2026-10-07).
- Protective put study in `studies/`, exploratory, with a pre-registered protocol (2026-10-08).
- tastytrade over read-only OAuth: one session and one DXLink streamer per process, chains,
  market metrics and per-expiry IV stored from the first pull (`market_metrics`, `iv_term`),
  live quotes in the market bar and on every page (2026-10-08).
- Implied vs realized vol by name on the Dashboard, from tastytrade metrics (2026-10-08).
- Charts page with a saved per-user watchlist, key stats, and the live mark folded into the
  day's candle (2026-10-08).
- Research page: a Fundamentals tab (statements, valuation, earnings history, recent SEC filings
  with links) and an Economy tab (economic calendar, Treasury curve, FRED macro panel when
  `FRED_API_KEY` is set).
- CI on every push and pull request, and a container image published to GHCR from main
  (2026-10-08). CI now also runs Python 3.11 and 3.13, a coverage floor, a type check, a
  dependency audit, a secret scan and a pull-request image build.
- Makefile, pre-commit hooks, Dependabot, pinned lockfiles, `.editorconfig`, CONTRIBUTING,
  SECURITY, `docs/architecture.md` and `docs/decisions.md`.
- launchd and systemd schedules in `deploy/` for hourly tastytrade collection and the daily bar
  top-up.

### Changed

- Renamed to Alpha Surface: package `alphasurface`, image `ghcr.io/corrionhank/alpha-surface`,
  data directory variable `ALPHASURFACE_DATA_DIR`.
- Navigation: Dashboard, Options, Screener, Charts, Volatility, Research, Docs.
- Pricer and Odds moved into a Tools menu in the top bar: option pricer (Black-Scholes price,
  Greeks, value vs spot) and pot odds (breakeven win rate against implied and realized
  probabilities) open as dialogs, also from the selected contract on the Options page, prefilled
  from it.
- Theme: light, with the indigo accent kept to the nav underline, primary buttons and the logo;
  sticky market bar, hairline panels, more spacing; collapsible sidebars hold page controls only,
  fixed rails hold the feeds and the watchlist; filler copy removed (2026-10-07 to 2026-10-08).
- `ohlcv` stored as one file per series instead of day partitions: a six-series read went from
  about 0.9 s to 0.03 s (2026-10-07).
- Docs consolidated: `schema.md` covers only implemented tables; the project brief, context
  handoff, requirements log and open decisions were folded into the README, `architecture.md`,
  `decisions.md` and this file.

### Removed

- Scenarios page (simulated paths, position P&L, hedged option, sizing, replay), until later.
  The simulation engine stays; the Screener's comparison uses it.
- Terminal snapshot (`rich`) and its summary module.
- Unused dependencies: fredapi, pandas-datareader, vix-utils, pandas-ta, textual, rich; the
  `notebooks` and `phase2` extras and the empty `notebooks/` directory.
- Dark theme and its toggle (2026-10-07).
- Stale systemd units that called a collector entry point that no longer existed.

### Fixed

- DuckDB catalog conflicts when several sessions refreshed views at once (2026-10-08).
- Header rules crossing text, and spacing across panels (2026-10-08).
- CI data directory set at step level (2026-10-08).

### Security

- tastytrade credentials only in `.env`; the settings object never prints them; a failed sign-in
  is never retried, avoiding the IP block.
- anyio, gitpython, pillow, soupsieve, starlette and urllib3 pinned past known advisories.
