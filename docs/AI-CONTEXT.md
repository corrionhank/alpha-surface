# Project Context Handoff

*A self-contained brief to give another AI model full context on this project. Last synced: 2026-06-08.*

---

## 1. What this project is

**`derivative-implied-pricing`** — a personal, always-on market analytics dashboard. It aggregates the options, volatility, and market-expectation metrics the owner cares about into one screen, to support his own discretionary trade decisions.

**It is not a predictor.** It decodes what the options market has *already priced in* (expected moves, IV, skew, term structure, fear gauges), each shown in the context of its own history. It informs decisions; it never emits buy/sell signals, forecasts, or trades.

**Analytical lens:** tastytrade / premium-selling — volatility mechanics, variance risk premium (VRP), and probabilities, not directional prediction. The owner knows options cold (IV rank/percentile, expected move, delta-as-probability, 45-DTE, manage-at-50%); explanations of these basics are not needed.

**Why it's feasible & free:** tastytrade gives funded non-professional accounts free real-time data through its API, including its signature metrics (IVR, IVP, IVx, IV−HV, expected move) pre-computed. That is both the enabler and the reason for the stack choice. Target recurring cost: **~$0/mo**.

---

## 2. Current status (as of 2026-06-08)

**Phase: pre-collector scaffolding.** The repo skeleton, dependencies, and design docs exist. **No functional code is written yet** — the `src/` modules are empty `__init__.py` stubs.

- Git: branch `main`, clean working tree, has a remote (`origin/main`). 2 commits: initial + "Scaffold repo structure, dependencies, and initial docs."
- `src/{collector,storage,derive,present}/` — all empty stubs (0–3 lines each).
- `tests/`, `notebooks/` — only `.gitkeep` placeholders.
- `.venv/` exists (env set up). `data/` is empty and gitignored.
- Config: `config/symbols.toml` populated with the core universe; `config/config.toml` (secrets) not yet created — only `config.example.toml` is committed.

**Immediate next build step:** finalize the DuckDB schema (Open Decision #5), then write the first collector. But two upstream decisions gate it — see §6.

---

## 3. Architecture

Four-layer pipeline:

```
collector  →  storage (DuckDB + Parquet)  →  derive  →  present
```

- **collector** — scheduled pulls (via `systemd` timers); writes Parquet. Modules planned: tastytrade, yfinance, FRED, vix_utils, news.
- **storage** — DuckDB views over date-partitioned Parquet. Schema drafted in `docs/schema.md`.
- **derive** — computes own IVR/IVP, VRP percentile, expected-move cone, skew, regime flags. Cross-validates own metrics against tastytrade's.
- **present** — v1: `rich` terminal / Jupyter against DuckDB. Intermediate: Streamlit on the LAN. Later: web frontend.

**Schedules:** hourly (market hours) for tastytrade chains/metrics + yfinance OHLCV/VIX; EOD (daily) for FRED + vix_utils; periodic for news.

**Hosting target:** Dell OptiPlex 7080, Ubuntu headless, 100 GB partition. Compute is light and I/O-bound — no GPU. `systemd` timers drive collection.

---

## 4. Tech stack

| Area | Tools |
|------|-------|
| Language | Python ≥3.11 |
| Core scientific | `pandas` ≥2.2, `numpy`, `scipy` |
| Data clients | `tastytrade` (tastyware SDK — chains, Greeks via dxFeed, `/market-metrics`), `yfinance`, `fredapi` / `pandas-datareader`, `vix-utils`, `httpx` (async, for news) |
| Technical metrics | `pandas-ta` |
| Storage | `duckdb` ≥0.10, `pyarrow` (Parquet) |
| Scheduling | `systemd` timers |
| Presentation | `rich` + `textual` (TUI), `streamlit` (LAN dashboard); Jupyter (`jupyterlab`, `ipywidgets`, `matplotlib`, `plotly`) for v1 exploration |
| Phase-2 (deferred) | `arch` (GARCH), `pyextremes` (EVT/GPD), `quantstats` |
| Dev tooling | `pytest` + `pytest-cov`, `ruff` (line-length 100), `mypy` |

Install: `pip install -e ".[notebooks,dev]"`

---

## 5. Data sources

**Primary — tastytrade API** (tastyware `tastytrade` Python SDK):
- Option chains, Greeks (dxFeed stream), and `/market-metrics` (IVR, IVP, IVx, IV−HV, beta, liquidity — pre-computed).
- Free real-time for funded non-professional accounts ($0 minimum to fund; ACH free, so the parked deposit is costless/reversible).
- Caveats: SDK is unofficial (well-maintained, no vendor SLA); dxFeed is slow for bulk *historical* backfill — fine for a focused hourly collector, painful for years-at-once. Compute own IVR alongside theirs for validation.

**Free supporting sources:**
- **yfinance** — OHLCV, indices, VIX complex (1h up to ~730 days; no native 4h → resample from 1h).
- **FRED** — rates, curve (T10Y2Y, T10Y3M), HY credit OAS, breakevens (daily).
- **vix_utils** — CBOE VIX-futures + cash term structure (daily settlement).
- **Finnhub** (free) + **Marketaux** (100 req/day free) — news with sentiment.

**Optional one-time:** **Databento** (~$125 free credit, pay-per-use) — one narrow historical options pull (SPY/SPX, bounded window) to seed Phase-2. Keep narrow; OPRA broad pulls burn credit fast.

**Rejected:** Polygon/Massive (now ~$99/mo since Oct 2025 rebrand), Tradier ($10/mo) — both redundant once tastytrade is free. TradingView has no public data API (its Charting Library is a frontend candidate only).

---

## 6. Open decisions (gate the build — in `docs/open-decisions.md`)

All five are still **TBD**. #1 and #5 must be resolved before the collector is written.

1. **Point-in-time correctness** *(decide first — shapes schema + collector).* Append-only with `collected_at` (PIT-correct, backtest-survivable, enables Phase-2 base rates) vs. overwrite-latest snapshot (simpler, history lost forever). **Recommendation: PIT-correct from day one** — costs nothing at this data volume; schema is already drafted this way. Needs upsert (`INSERT OR REPLACE` by `collected_at`+`symbol`) for retry dedup.
2. **Underlying universe.** Core settled: SPY, QQQ, IWM, DIA, /ES, /NQ, /RTY, VIX complex. Single-name slot (`symbols.toml [single_names]`) is empty — pick 4–8 liquid, high-OI names (candidates: AAPL, TSLA, NVDA, AMZN, META, GLD, TLT, XLE).
3. **v1 presentation.** Pure Jupyter vs. `rich`/`textual` TUI vs. early Streamlit. **Recommendation: start Jupyter, promote to Streamlit once data layer is stable.**
4. **Historical seed (Databento).** Buy the one-time pull now vs. wait. **Recommendation: wait until pipeline runs cleanly 2–4 weeks, then spend on a narrow SPY/SPX window covering key stress episodes (Aug 2024 yen unwind, Apr 2025 tariff selloff).**
5. **DuckDB schema** *(immediate next build step).* Draft DDL exists in `docs/schema.md` — review tastytrade field mappings, strike band width (±15% of spot), and `derived_metrics` coverage before finalizing.

---

## 7. Data model (drafted in `docs/schema.md`)

Storage: Parquet at `data/parquet/{table}/year=/month=/day=/`, queried via DuckDB views (hive-partitioned for date pushdown). A `data/market.duckdb` file holds view definitions + the computed `derived_metrics` table. All timestamps UTC (`TIMESTAMPTZ`); `collected_at` on every raw table enables PIT queries.

Raw tables: `market_metrics` (tastytrade IV/EM fields, hourly), `option_chain` (per-strike Greeks + bid/ask, strike band 0.85×–1.15× spot, key expiries: weekly + ~30/45/60 DTE), `ohlcv` (yfinance 1h/1d), `vix_complex` (VIX/VIX1D/VVIX/VIX3M + cross-asset MOVE/GVZ/OVX), `interest_rates` (FRED daily), `vix_term_structure` (vix_utils daily settlement), `news` (Finnhub/Marketaux). Computed: `derived_metrics` (own IVR/IVP, VRP percentile, price vs 50/200-DMA, RV percentile, 25Δ skew, term-structure slope, regime flag).

Footprint: ~250–300 MB/year focused (≈3 GB/year full chains) → 100 GB = decades of runway.

---

## 8. What it displays (the product)

**Per-underlying vol panel (watchlist rows):** IV Rank & IV Percentile (both — IVR distorts after a spike, IVP steadier), IVx per expiration (~30–45 DTE), 30d IV / 30d HV / IV−HV (VRP), expected move (1 SD: daily/weekly/to-catalyst), 25Δ skew, term structure (contango/backwardation), liquidity rating, delta-based probabilities (POP, prob-of-touch).

**Market-state strip — four questions, one per panel:**
1. **Regime** — VIX/VIX3M term structure, VRP, HY credit-spread percentile, curve slope (2s10s / 3m10y).
2. **Stretch** — price vs 50/200-DMA + distance percentile, realized-vol percentile, drawdown/rally percentile.
3. **Priced** — expected-move cone, skew.
4. **Why** — filtered, market-moving news feed.

**Backdrop:** cross-asset vol complex; Fear & Greed composite (drill-down to 7 components, shown as one labeled lens — never a verdict); beta-weighted deltas to SPY (once positions tracked).

**Signature visual:** the expected-move cone (1 SD range from ATM straddle / IVx, projected to next week / next catalyst). **Spine of the whole thing:** the implied-vs-realized gap (VRP / IV−HV).

---

## 9. Phasing

- **Phase 1 (now):** collector + DuckDB + terminal/Jupyter view of the core watchlist (vol panels, four-question strip, cone, news, fear/greed). Background accrual of implied-vol history from day one. ~$0/mo.
- **Phase 2 (deferred, needs accrued history):** conditional base rates ("when the setup looked like X, here's the forward-outcome distribution" — base rates, not predictions; the intended differentiator), tail modeling (EVT peaks-over-threshold + GPD, CVaR, GARCH, fat-tailed Monte Carlo, scenario replay — explicitly **no Gaussian parametric VaR**), full Breeden-Litzenberger risk-neutral density, tastytrade-style empirical studies, percentile-of-swings engine, web frontend.

---

## 10. Development principles (hard rules — from `.claude/Development-Principles.md`)

1. **Keep it simple, from first principles** — least code that solves the real problem; no unjustified abstraction.
2. **Inform, don't predict** — decode what's priced; show context (percentile/regime), never raw numbers or buy/sell signals.
3. **Read-only. Never trade.** The feed is a live brokerage connection. Never touch order entry — placing, cancelling, or altering positions — ever, including in tests, unless explicitly asked in that message.
4. **Don't burn limited data** — paid credit and capped free tiers are finite; no bulk/historical pulls unless told. Scheduled routine reads are fine.
5. **Verify before reporting** — trace every number to its source; if a vendor publishes the same metric, check yours against theirs and flag mismatches.
6. **Seed history early** — store vol series/snapshots from day one; can't be backfilled.
7. **Keep docs and messages short** — dated one-line change logs; 2–3 sentence commits; explanations under 6 lines.
8. **Never self-attribute in commits** — no Co-Authored-By, contributor tags, or Claude/Anthropic attribution of any kind.

---

## 11. Key formulas (reference)

- **IV Rank:** `(IV − 52wk low) / (52wk high − 52wk low)`
- **IV Percentile:** `(# of last 252 trading days with IV < current) / 252`
- **IVx:** VIX-style implied vol per expiration cycle (variance-strip method)
- **Expected move (1 SD, to horizon):** `≈ price × IV × √(DTE/365)`; straddle approx `≈ ATM straddle × ~0.85`. Daily shortcut: `SPX daily expected % ≈ VIX / 16` (√252 ≈ 16)
- **Delta as probability:** `|delta| ≈ P(ITM)`; 16Δ ≈ 1 SD, 5Δ ≈ 2 SD; `P(touch) ≈ 2 × P(ITM)`
- **VRP / IV−HV:** implied minus realized vol — the premium harvested by sellers
- **Risk-neutral density (Breeden-Litzenberger):** `f(K) ∝ e^(rT) · ∂²C/∂K²` (smooth the IV surface before differentiating)

---

## 12. Repo map

```
CLAUDE.md                    architecture + dev orientation
README.md                    setup + what-it-shows summary
Project-Breif.md             full project brief (source of truth)
docs/schema.md               DuckDB table DDL (draft — finalize before collector)
docs/open-decisions.md       5 open architectural decisions
docs/AI-CONTEXT.md           this file
config/config.example.toml   template for secrets/paths (copy → config.toml, gitignored)
config/symbols.toml          tracked universe + FRED series
src/{collector,storage,derive,present}/   empty stubs — not yet implemented
systemd/                     service + timer unit files (Ubuntu host)
tests/ notebooks/            placeholders only
data/                        gitignored — Parquet + market.duckdb (empty)
```
