# Requirements

Software requirements for the dashboard. Companion to `Project-Breif.md` (narrative brief)
and `docs/schema.md` (data model). Each requirement is tagged done, partial, or planned
against the current build.

---

## 1. Purpose and scope

Aggregate the options, volatility, and market-expectation metrics the owner cares about into
one terminal/browser view, to support discretionary trade decisions. The system decodes what
the options market has already priced (expected moves, IV, skew, term structure, fear gauges),
each shown against its own history. It informs. It never predicts, signals, or trades.

- In scope (Phase 1): scheduled collection of vol/price/macro data, a DuckDB and Parquet
  store, derived vol/regime metrics, and terminal plus LAN dashboard presentation, at ~$0/mo.
- Out of scope: order entry of any kind, price/direction prediction, conditional base rates and
  tail modeling (Phase 2), a public web frontend.

---

## 2. Actors and environment

- Single user (owner). Non-professional, funded trader who knows options mechanics.
- Dev host: macOS. Production host: headless Ubuntu OptiPlex, systemd timers, 100 GB.
- Consumers: rich terminal, Streamlit LAN dashboard, Jupyter.

---

## 3. Functional requirements

### 3.1 Collection

| ID | Req | Status |
|----|-----|--------|
| FR-C1 | Collect OHLCV (1h, 1d) for the tracked index/ETF universe from yfinance, normalize to UTC, write to Parquet. | done |
| FR-C2 | Collect tastytrade `/market-metrics` (IVR, IVP, IVx, IV-HV, EM, beta, liquidity) hourly in market hours. | done (collector; schedule pending) |
| FR-C3 | Collect a strike-band option chain (Greeks plus bid/ask) around spot for key expiries (weekly, ~30/45/60 DTE), hourly. | done: bid/ask/last/volume/OI via DXLink, IV and Greeks solved in derive; schedule pending |
| FR-C4 | Collect the VIX complex (VIX/VIX1D/VVIX/VIX3M plus cross-asset MOVE/GVZ/OVX). | planned |
| FR-C5 | Collect FRED macro series (curve, credit OAS, real rates, breakevens) daily. | planned |
| FR-C6 | Collect VIX-futures term structure via vix_utils daily. | planned |
| FR-C7 | Collect filtered news plus sentiment (Finnhub, Marketaux) periodically. | planned |
| FR-C8 | Collection is idempotent: re-runs upsert (dedup on primary key), never accumulate duplicates. | done |
| FR-C9 | Collection runs on schedule via systemd timers: hourly in market hours, EOD daily, periodic news. | planned |

### 3.2 Storage

| ID | Req | Status |
|----|-----|--------|
| FR-S1 | Persist raw data as hive-partitioned Parquet (`year/month/day`), queried via DuckDB views. | done |
| FR-S2 | Point-in-time correct: raw records carry their timestamp, append-only, never destructively overwritten (Open Decision 1). | done |
| FR-S3 | Conform to `docs/schema.md`. `ohlcv` implemented, remaining tables planned. | partial |
| FR-S4 | Reads take no write-lock, so they cannot contend with a running collector. | done |

### 3.3 Derivation

| ID | Req | Status |
|----|-----|--------|
| FR-D1 | Compute own IVR and IVP from stored IV history, cross-validate against tastytrade's. | planned |
| FR-D2 | Compute VRP (IV-HV) and its percentile. | done |
| FR-D3 | Compute the expected-move cone (1 SD to horizon / next catalyst). | done |
| FR-D4 | Compute 25-delta skew and term-structure slope. | done |
| FR-D5 | Compute price vs. 50/200-DMA and realized-vol percentile. | done |
| FR-D6 | Assign a regime flag (low_vol / normal / elevated / stress) from VIX level plus TS slope plus VRP. | done |
| FR-D7 | Basic descriptive display stats (last, change, high/low, realized vol). | done |

### 3.4 Presentation

| ID | Req | Status |
|----|-----|--------|
| FR-P1 | Terminal snapshot (rich) of a stored series with summary stats. | done |
| FR-P2 | Streamlit LAN dashboard: symbol/interval selection, TradingView candlestick plus volume, stat tiles, raw bars, docs portal. | done |
| FR-P3 | Per-underlying vol panel: IVR, IVP, IVx, IV-HV, expected move, skew, term structure, liquidity, delta-based probabilities. | partial: overview "implied vs realized, by name" (IVx, IVR, IVP, HV30, IV/HV, earnings); chain page per contract |
| FR-P4 | Market-state strip, four questions: Regime, Stretch, Priced, Why. | partial: first three done; Why needs the news collector |
| FR-P5 | Expected-move cone visual, cross-asset vol backdrop, Fear/Greed lens (a labeled lens, never a verdict). | partial: cone done; vol backdrop limited to stored VIX complex; Fear/Greed planned |
| FR-P6 | Every figure shown in context (percentile/regime), no raw-number-only or buy/sell framing. | required |

---

## 4. Non-functional requirements

| ID | Req |
|----|-----|
| NFR-1 | Cost ~$0/mo recurring, free tiers only (tastytrade funded data, yfinance, FRED, Finnhub/Marketaux). |
| NFR-2 | Read-only, never trade. No code path touches order entry, ever, including tests, unless explicitly instructed in that message. |
| NFR-3 | Data thrift. No bulk/historical pulls on metered or capped sources unless instructed. Scheduled routine reads only. |
| NFR-4 | Verifiability. Every displayed number traces to its source. Vendor-published metrics are cross-checked and mismatches flagged. |
| NFR-5 | Seed history early. Store vol series/snapshots from day one. It cannot be backfilled. |
| NFR-6 | Footprint ~250-300 MB/yr focused (~3 GB/yr full chains), fits the 100 GB host with decades of runway. |
| NFR-7 | Portability. Runs with no `config.toml` (local `data/` defaults). Host path set via `config.toml` on the OptiPlex. |
| NFR-8 | Simplicity. Least code that solves the problem, no unjustified abstraction. |
| NFR-9 | Time. All timestamps UTC (`TIMESTAMPTZ`). |
| NFR-10 | Reliability. Collector retries are safe (idempotent upsert), a failed run never corrupts the store. |

---

## 5. Data sources and constraints

| Source | Data | Cadence | Limit / caveat |
|--------|------|---------|----------------|
| tastytrade SDK | chains, Greeks (dxFeed), `/market-metrics` | hourly | unofficial SDK, no SLA. dxFeed slow for bulk history |
| yfinance | OHLCV, VIX complex | hourly / daily | 1h limited to ~730 days per request. No native 4h, resample |
| FRED | rates, curve, credit, breakevens | daily | free API key |
| vix_utils | VIX-futures term structure | daily | settlement only |
| Finnhub / Marketaux | news plus sentiment | periodic | Marketaux 100 req/day |
| Databento (optional, Phase 2) | narrow historical OPRA seed | one-time | ~$125 credit, keep the window narrow |

---

## 6. Hard rules

Constrain every requirement above. See `.claude/Development-Principles.md` and `docs/ai-policy.md`.

Keep it simple. Inform, don't predict. Read-only, never trade. Don't burn limited data. Verify
before reporting. Seed history early. Keep docs and messages short. No self-attribution in commits.

---

## 7. Phasing

- Phase 1 (now): collector plus store plus terminal/Streamlit view of the core watchlist,
  background accrual of implied-vol history from day one.
- Phase 2 (deferred, needs accrued history): conditional base rates, EVT/GPD tail modeling,
  GARCH, fat-tailed Monte Carlo, scenario replay, Breeden-Litzenberger risk-neutral density,
  percentile-of-swings engine, web frontend. No Gaussian parametric VaR.
- Never in scope: trading / order entry, buy/sell signals or price-direction forecasts.

Open architectural decisions that still gate work are in `docs/open-decisions.md` (1 PIT and 5
schema resolved-as-drafted by the current build, 2 universe, 3 v1 UI, 4 Databento still open).

---

## 8. Acceptance criteria (Phase 1 slice)

| ID | Criterion | Status |
|----|-----------|--------|
| AC-1 | A fresh clone plus `pip install -e .` collects and displays SPY data with no `config.toml`. | met |
| AC-2 | Re-running the collector leaves row counts unchanged for an unchanged window (idempotent). | met |
| AC-3 | Terminal and Streamlit both render stored data, and an empty state when none exists. | met |
| AC-4 | Storage tests (round-trip, dedup, empty view) pass, ruff clean. | met |
| AC-5 | Own IVR/IVP agree with tastytrade within noise. | pending FR-D1 |

---

*2026-07-10: initial requirements spec, reflects the yfinance OHLCV slice as done.*
*2026-08-09: overview page (state strip, cone, vol complex, watchlist); FR-D2 to D6 done, FR-P3 to P5 partial.*
*2026-08-10: site chrome: branded top bar, ticker strip on every page, theme switch moved to the header row, overview controls inline.*
*2026-10-07: light monochrome restyle per `.claude/STYLE_GUIDE.md` (Newsreader and Inter, white cards, color only for status); dark theme and toggle removed.*
*2026-10-07: landing page (hero, solutions, how it works, data, CTA) and a mock sign-in that gates the app pages; `present/landing.py`, `login.py`, `auth.py`, `routes.py`.*
*2026-10-07: options chain page: straddle board per expiry, single-contract metrics (IV, intrinsic and extrinsic, vs realized vol, seller yield); synthetic chains quote both sides; formulas section 13.*
*2026-10-07: scenarios page (Monte Carlo paths under GBM, jump diffusion or historical bootstrap; position P&L profile, delta-hedged vol edge, Kelly sizing, historical replay); `derive/simulate.py`, `derive/positions.py`, `present/scenarios.py`.*
*2026-10-07: market-data gateway (`collector/feed.py`): every pull returned to the caller and stored (`option_chain`, append-only); options scanner page and `python -m collector.scan` with eight presets, opt-in alerts, options-or-underlying comparison; `docs/scanner.md`.*
*2026-10-07: overview rebuilt as a trader cockpit (KPI band, SPY/QQQ charts, implied vol panel and VIX term curve, fear and greed lens, SPY/QQQ fundamentals and holdings, news, economic calendar); reference data stored write-through; `docs/dashboard.md`.*
*2026-10-07: dashboard revision: full-width shell with a sticky market bar, hairline panels with header rows, stat strips, overview grid with a sticky right rail (fear and greed meter, calendar, news), linear meters instead of rings, tighter radii; style guide section 13.*
*2026-10-08: tastytrade connected (OAuth from .env, read scope): one shared session and DXLink streamer per process (`collector/tasty.py`), chain provider, market metrics and per-expiry IV stored; live tape; feed level currently 'demo'.*
*2026-10-08: everything live: any symbol on every page (bars topped up and written through, live tastytrade marks in session); Charts page with a saved per-user watchlist; chart axes, overview tables and spacing fixed; filler copy removed (style guide copy rules).*
