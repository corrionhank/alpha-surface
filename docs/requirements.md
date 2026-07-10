# Requirements — derivative-implied-pricing

Software requirements for a personal market-analytics dashboard. Companion to
`Project-Breif.md` (narrative brief) and `docs/schema.md` (data model). Each
requirement is tagged **[done]**, **[partial]**, or **[planned]** against the
current build.

---

## 1. Purpose & scope

Aggregate the options-, volatility-, and market-expectation metrics the owner cares
about into one terminal/browser view, to support discretionary trade decisions. The
system **decodes what the options market has already priced in** (expected moves, IV,
skew, term structure, fear gauges), each shown against its own history. It **informs**;
it never predicts, signals, or trades.

- **In scope (Phase 1):** scheduled collection of vol/price/macro data, a DuckDB+Parquet
  store, derived vol/regime metrics, and terminal + LAN dashboard presentation, at ~$0/mo.
- **Out of scope:** order entry of any kind; price/direction prediction; conditional base
  rates and tail modeling (Phase 2); a public web frontend.

---

## 2. Actors & environment

- Single user (owner) — non-professional, funded trader; knows options mechanics cold.
- Dev host: macOS. Production host: headless Ubuntu OptiPlex, `systemd` timers, 100 GB.
- Consumers: `rich` terminal, Streamlit LAN dashboard, Jupyter.

---

## 3. Functional requirements

### 3.1 Collection

| ID | Req | Status |
|----|-----|--------|
| FR-C1 | Collect OHLCV (1h, 1d) for the tracked index/ETF universe from yfinance; normalize to UTC; write to the Parquet lake. | **done** |
| FR-C2 | Collect tastytrade `/market-metrics` (IVR, IVP, IVx, IV−HV, EM, beta, liquidity) hourly in market hours. | planned |
| FR-C3 | Collect a strike-band option chain (Greeks + bid/ask) around spot for key expiries (weekly, ~30/45/60 DTE), hourly. | planned |
| FR-C4 | Collect the VIX complex (VIX/VIX1D/VVIX/VIX3M + cross-asset MOVE/GVZ/OVX). | planned |
| FR-C5 | Collect FRED macro series (curve, credit OAS, real rates, breakevens) daily. | planned |
| FR-C6 | Collect VIX-futures term structure via `vix_utils` daily. | planned |
| FR-C7 | Collect filtered news + sentiment (Finnhub, Marketaux) periodically. | planned |
| FR-C8 | Collection is idempotent — re-runs upsert (dedup on primary key), never accumulate duplicates. | **done** |
| FR-C9 | Collection runs on schedule via `systemd` timers: hourly in market hours, EOD daily, periodic news. | planned |

### 3.2 Storage

| ID | Req | Status |
|----|-----|--------|
| FR-S1 | Persist raw data as hive-partitioned Parquet (`year/month/day`), queried via DuckDB views. | **done** |
| FR-S2 | PIT-correct: raw records carry their collection/observation timestamp; append-only, never destructively overwritten (Open Decision #1). | **done** |
| FR-S3 | Conform to `docs/schema.md`. `ohlcv` implemented; remaining tables planned. | partial |
| FR-S4 | Reads take no write-lock, so they can't contend with a running collector. | **done** |

### 3.3 Derivation

| ID | Req | Status |
|----|-----|--------|
| FR-D1 | Compute own IVR & IVP from stored IV history; cross-validate against tastytrade's. | planned |
| FR-D2 | Compute VRP (IV−HV) and its percentile. | planned |
| FR-D3 | Compute the expected-move cone (1 SD to horizon / next catalyst). | planned |
| FR-D4 | Compute 25Δ skew and term-structure slope. | planned |
| FR-D5 | Compute price vs 50/200-DMA and realized-vol percentile. | planned |
| FR-D6 | Assign a regime flag (low_vol / normal / elevated / stress) from VIX level + TS slope + VRP. | planned |
| FR-D7 | Basic descriptive display stats (last, change, hi/lo, realized vol). | **done** |

### 3.4 Presentation

| ID | Req | Status |
|----|-----|--------|
| FR-P1 | Terminal snapshot (`rich`) of a stored series with summary stats. | **done** |
| FR-P2 | Streamlit LAN dashboard: symbol/interval selection, price + volume charts, stat tiles, raw bars. | **done** |
| FR-P3 | Per-underlying vol panel: IVR, IVP, IVx, IV−HV, expected move, skew, term structure, liquidity, delta-based probabilities. | planned |
| FR-P4 | Market-state strip — four questions: **Regime**, **Stretch**, **Priced**, **Why**. | planned |
| FR-P5 | Expected-move cone visual; cross-asset vol backdrop; Fear/Greed lens (a labeled lens, never a verdict). | planned |
| FR-P6 | Every figure shown in context (percentile/regime); no raw-number-only or buy/sell framing. | required |

---

## 4. Non-functional requirements

| ID | Req |
|----|-----|
| NFR-1 | **Cost** ~$0/mo recurring — free tiers only (tastytrade funded data, yfinance, FRED, Finnhub/Marketaux). |
| NFR-2 | **Read-only / never trade** — no code path touches order entry, ever, including tests, unless explicitly instructed in that message. |
| NFR-3 | **Data thrift** — no bulk/historical pulls on metered or capped sources unless instructed; scheduled routine reads only. |
| NFR-4 | **Verifiability** — every displayed number traces to its source; vendor-published metrics are cross-checked and mismatches flagged. |
| NFR-5 | **Seed history early** — store vol series/snapshots from day one; it cannot be backfilled. |
| NFR-6 | **Footprint** — ~250–300 MB/yr focused (~3 GB/yr full chains); fits the 100 GB host with decades of runway. |
| NFR-7 | **Portability** — runs with no `config.toml` (local `data/` defaults); host path set via `config.toml` on the OptiPlex. |
| NFR-8 | **Simplicity** — least code that solves the real problem; no unjustified abstraction. |
| NFR-9 | **Time** — all timestamps UTC (`TIMESTAMPTZ`). |
| NFR-10 | **Reliability** — collector retries are safe (idempotent upsert); a failed run never corrupts the store. |

---

## 5. Data sources & constraints

| Source | Data | Cadence | Limit / caveat |
|--------|------|---------|----------------|
| tastytrade SDK | chains, Greeks (dxFeed), `/market-metrics` | hourly | unofficial SDK, no SLA; dxFeed slow for bulk history |
| yfinance | OHLCV, VIX complex | hourly / daily | 1h ≤ ~730d per request; no native 4h → resample |
| FRED | rates, curve, credit, breakevens | daily | free API key |
| vix_utils | VIX-futures term structure | daily | settlement only |
| Finnhub / Marketaux | news + sentiment | periodic | Marketaux 100 req/day |
| Databento *(optional, Phase 2)* | narrow historical OPRA seed | one-time | ~$125 credit; keep the window narrow |

---

## 6. Hard rules (from `.claude/Development-Principles.md`)

These constrain every requirement above:

1. Keep it simple, from first principles. 2. Inform, don't predict. 3. Read-only — never
trade. 4. Don't burn limited data. 5. Verify before reporting. 6. Seed history early.
7. Keep docs and messages short. 8. Never self-attribute in commits.

---

## 7. Phasing

- **Phase 1 (now):** collector + store + terminal/Streamlit view of the core watchlist;
  background accrual of implied-vol history from day one.
- **Phase 2 (deferred — needs accrued history):** conditional base rates; EVT/GPD tail
  modeling, GARCH, fat-tailed Monte Carlo, scenario replay; Breeden-Litzenberger
  risk-neutral density; percentile-of-swings engine; web frontend. **No Gaussian
  parametric VaR.**
- **Never in scope:** trading / order entry; buy/sell signals or price-direction forecasts.

Open architectural decisions that still gate work are tracked in
`docs/open-decisions.md` (#1 PIT and #5 schema resolved-as-drafted by the current build;
#2 universe, #3 v1 UI, #4 Databento still open).

---

## 8. Acceptance criteria (Phase 1 slice)

| ID | Criterion | Status |
|----|-----------|--------|
| AC-1 | A fresh clone + `pip install -e .` collects and displays SPY hourly data with no `config.toml`. | met |
| AC-2 | Re-running the collector leaves row counts unchanged for an unchanged window (idempotent). | met |
| AC-3 | Terminal and Streamlit both render stored data, and an empty-state when none exists. | met |
| AC-4 | Storage tests (round-trip, dedup, empty view) pass; `ruff` clean. | met |
| AC-5 | Own IVR/IVP agree with tastytrade within noise. | pending FR-D1 |

---

*2026-07-10 — initial requirements spec; reflects the yfinance OHLCV slice as done.*
