# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/); before 1.0 a minor version may change anything.
Open work lives in [TODO.md](TODO.md).

## [Unreleased]

### Added

- Options: a Strikes control (10, 20 or 40 each side of the money, or all) beside the expiry.
- `TODO.md`: open work by priority, with what needs a go-ahead.
- Options: deep in-the-money contracts whose price does not solve for an IV (a wide quote under
  the no-arbitrage bound) take the other side's IV at the same strike, which put-call parity
  makes the same; their Greeks follow from it. Such IVs show in italics on the board, and the
  contract panel names the side the IV came from.
- Options: the board shows when it was pulled and, below 100%, the share of contracts that
  quoted.
- Tests for the market clock, the symbol map, the feed status, candles, chain coverage, the rate,
  dividend, horizon IV and metrics-table helpers, and the Yahoo collector's default universe.

### Changed

- Options: Full screen now lifts the whole chain panel over the page, with its header, expiry
  picker and every strike, instead of Streamlit's table fullscreen, which showed the same few
  rows alone on a blank screen.
- `docs/schema.md` covers the 5-minute interval, session-date keying for daily bars, the new
  `market_metrics` columns and the Research and instrument tables.
- Version 0.2.0 in `pyproject.toml`.
- Research, Fundamentals: the statements panel puts its title and controls on one row, runs oldest
  to newest like the chart beside it, shows one YoY column and the units in the header; filings
  read as what they are (annual, quarterly, current report) and open on click; the next earnings
  report shows its date only (Yahoo's times are placeholders); side-by-side cards end level;
  market cap is no longer repeated under Valuation.
- Research, Economy: the calendar has Upcoming and Released views, fixed number columns, drops
  columns empty in the view, and sits beside the Treasury curve and the 10Y minus 3M spread.
- The Streamlit entry moved from `present/streamlit_app.py` to `src/alphasurface/app.py`, so
  edits anywhere in the package reload the running app; before, a change outside `present/`
  needed a restart and could crash a page with a missing attribute. `make run` is unchanged.
- Market bar: during the session the tape and status refresh every 20 seconds on their own,
  without rerunning the page; the feed reads "tastytrade real-time" or "tastytrade delayed".
- Dashboard: the KPI strip refreshes every 30 seconds in the session; the implied vs realized
  panel reads one row per name through the metrics table; the expected-move cone uses the
  name's implied vol for the horizon (tastytrade IV at the nearest expiry, then IVx), the index
  vol and realized vol as fallbacks; an empty store backfills SPY and VIX history instead of
  stopping with a command to run.
- Options: the board and contract panel refresh every 45 seconds in the session; the rate and
  dividend default to the live risk-free rate and the symbol's dividend yield, not the 13-week
  bill and a fixed 1.2%; a pull is stored at most every 5 minutes per expiry; the picked
  contract survives a refresh or a change of strike count.
- Screener: the rate defaults to the live risk-free rate; the vehicles tab takes the symbol's
  live price, implied vol for a month out and its own dividend yield.
- Charts: a symbol is checked against the providers before it joins the watchlist, without
  backfilling its history; an unknown one reads "No such symbol".
- Yahoo collector: daily bars default to every symbol a page reads (`Config.universe()`), hourly
  bars to the index ETFs and single names, so the scheduled top-up keeps every page current.
- CI secret scan runs a pinned, checksum-verified gitleaks over the full history instead of
  gitleaks-action, which failed on the history rewrite.

### Removed

- Options: the moneyness slider in the sidebar, replaced by the Strikes control.
- Research: the "set FRED_API_KEY" line on the Economy tab.

### Fixed

- Research tables had a full border on every cell and no padding: Streamlit's markdown table
  styles overrode the page's. The page's rules now win.
- Research and Charts headers: outside the session the price is the official close, with the
  after-hours or pre-market mark on its own line, never as the day's change. When the stored
  history is behind the last session (a symbol just added), the close comes from the feed.
- The analyst rating bar did not render; a P/E of zero showed as 0.00.
- tastytrade chains stopped at strikes within 25% of spot, so long-dated 10-delta wings were
  never requested and the Volatility grid showed gaps where Yahoo had data. The band now widens
  with tenor, from about 12% for a weekly to 60% past six months, and the streamer cache holds
  6,000 symbols instead of 4,000.

### Security

- History rewritten: every commit's author email is the GitHub noreply address, and the early
  project brief, requirements log, context handoff and open-decisions docs, which held personal
  details, are gone from history. Gitleaks and GitHub secret scanning find nothing in it.

## [0.2.0] - 2026-10-08

Renamed to Alpha Surface. Commit `7a110ed`.

### Added

- Research page with a Fundamentals tab (statements, valuation and profitability, earnings
  history with surprises, analyst targets, recent SEC filings with links) and an Economy tab
  (economic calendar, Treasury curve today against a month and a year ago, 10Y minus 3M spread,
  FRED macro series when `FRED_API_KEY` is set). Deep links: `/research?tab=fundamentals&symbol=X`
  and `/research?tab=economy`, used by the Dashboard calendar and the Charts stats.
- Tools menu in the market bar: the option pricer (price, Greeks, value against spot today and
  at expiry) and pot odds (breakeven win rate against implied and realized probabilities), as
  dialogs. The selected contract on the Options page opens either one prefilled.
- Charts watchlist as a native list: click to open, right-click or the row menu for open,
  replace, move to top, move up, move down and remove, an add row at the bottom that appends,
  keyboard support. Thirty-day sparklines, live last and change.
- Charts: ranges from 1D to 5Y with intraday bars, an "At close" price with the pre-market or
  after-hours mark beside it, and price, volatility (IVx, IV rank and percentile, realized vol,
  IVx minus realized, one-week expected move) and profile stats.
- Market clock on the NYSE and CME calendars: holidays and 13:00 half days honored everywhere
  the app asks whether the market is open (`alphasurface.clock`).
- One symbol map between the store, Yahoo, the tastytrade streamer and display, for indices
  (SPX, NDX, RUT, the VIX family) and futures roots (`alphasurface.symbols`).
- tastytrade candles for 5-minute and hourly bars, written through to `ohlcv`; Yahoo is the
  fallback. Windows are capped at 5 sessions of 5-minute bars and 30 of hourly.
- Live risk-free rate (tastytrade, then the 13-week bill), dividend yield and horizon-matched
  implied vol for every page that prices an option.
- Feed status from tastytrade: the app says "real-time" or "delayed" instead of the raw token
  level.
- Symbol search and descriptions through tastytrade, stored in a new `instruments` table.
- New stored tables: `fundamentals`, `financials`, `earnings`, `macro_series`, `instruments`;
  more `market_metrics` columns (dividends, market cap, P/E, EPS, borrow rate, liquidity rank).
- Universe in `config/symbols.toml` wired end to end: index ETFs, single names, the vol complex,
  cross-asset vol, macro ETFs, Treasury yields and futures.
- CI on Python 3.11 and 3.13 with lint, format check, a coverage floor, a dependency audit, a
  secret scan, an informational type check, a pull-request image build and the GHCR publish on
  main. Makefile, pre-commit, Dependabot, pinned lockfiles, `.editorconfig`, CONTRIBUTING,
  SECURITY, `docs/architecture.md` and `docs/decisions.md`.
- launchd and systemd schedules in `deploy/` for hourly tastytrade collection and the daily bar
  top-up (not installed).

### Changed

- Package `alphasurface` under `src/alphasurface`, repository `corrionhank/alpha-surface`, image
  `ghcr.io/corrionhank/alpha-surface`, data directory variable `ALPHASURFACE_DATA_DIR`.
- Navigation: Dashboard, Options, Screener, Charts, Research, Volatility, Docs.
- Every secret comes from `.env` (tastytrade, Finnhub, FRED); `config/config.toml` holds settings
  only.
- The market bar shows the official close and the day's change outside the session, so an
  after-hours move never reads as the day's change.
- Screener CLI defaults to tastytrade when connected and reads its universe from config; the
  throttle applies to Yahoo only.
- Chains: the nested chain is cached for an hour, contracts that miss the first quote get a
  second wait, and the result carries its coverage.
- Docs consolidated into the README, `architecture.md`, `decisions.md`, `schema.md`,
  `formulas.md`, `dashboard.md` and `scanner.md`; the Docs page lists those.

### Removed

- Scenarios page, until it is rebuilt with more substance. The simulation engine stays; the
  Screener's comparison uses it.
- Pricer and Odds as pages (now tools).
- Terminal snapshot (`rich`) and its summary module; the one-off day-partition migration; unused
  helpers.
- Unused dependencies: fredapi, pandas-datareader, vix-utils, pandas-ta, textual, rich; the
  `notebooks` and `phase2` extras; the empty `notebooks/` directory.
- Project brief, context handoff, requirements log and open-decisions docs (folded in).

### Fixed

- Daily bars stamped at Chicago midnight and New York midnight for the same session (22 ^VIX
  days) showed VIX at 0.00% and crashed the Dashboard. Daily bars are now keyed by New York
  session date on write and read; the stored files were repaired with a backup kept.
- The implied vs realized panel collapsed to one symbol after any single-symbol metrics pull.
- A `-0.00%` change shown in red.

### Security

- `.env` only for credentials; settings objects never print them; a failed tastytrade sign-in is
  never retried, avoiding the IP block.
- anyio, gitpython, pillow, soupsieve, starlette and urllib3 pinned past known advisories.

## [0.1.0] - 2026-10-08

Everything before the rename, through commit `a0b7486`.

### Added

- Collector and store for Yahoo daily and hourly bars: Parquet with DuckDB views, idempotent
  upserts, UTC timestamps (2026-07-10).
- Multipage Streamlit app with TradingView Lightweight charts and an in-app Docs page
  (2026-07-11).
- Black-Scholes model with Greeks (2026-07-13).
- tastytrade over read-only OAuth: one session and one DXLink streamer per process, chains,
  market metrics and per-expiry IV stored from the first pull (2026-10-08).
- Write-through market-data gateway: every pull is returned to the caller and appended to the
  store in the same step.
- Options page: straddle board per expiry and single-contract metrics (own IV and Greeks,
  intrinsic and extrinsic, extrinsic per day, priced against realized vol, seller yield and APY).
- Screener page and CLI: eight presets, saved scans, the options-or-underlying comparison over
  simulated paths, opt-in macOS and ntfy alerts.
- Dashboard: KPI band, SPY and QQQ charts, implied vol panel and VIX term curve, fear and greed
  lens, fund fundamentals and holdings, economic calendar and news.
- Landing page and a mock sign-in that gates the app pages.
- Protective put study in `studies/`, with a pre-registered protocol.
- CI with lint and tests, and a container image published to GHCR from main.

### Changed

- `ohlcv` stored as one file per series instead of day partitions: a six-series read went from
  about 0.9 s to 0.03 s.
- Light theme with the accent kept to navigation, primary buttons and the logo; sticky market
  bar, hairline panels; sidebars hold page controls only, rails hold feeds and the watchlist.

### Fixed

- DuckDB catalog conflicts when several sessions refreshed views at once.
- Panel rules crossing text, and spacing across panels.

[Unreleased]: https://github.com/corrionhank/alpha-surface/compare/7a110ed...HEAD
[0.2.0]: https://github.com/corrionhank/alpha-surface/compare/a0b7486...7a110ed
[0.1.0]: https://github.com/corrionhank/alpha-surface/commits/a0b7486
