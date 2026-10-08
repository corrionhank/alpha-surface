# derivative-implied-pricing

Personal market analytics dashboard. A custom watchlist aggregating options pricing, implied volatility, expected moves, VRP, regime signals, and cross-asset vol. Decodes what the options market has already priced in to inform trade decisions. Built on the **tastytrade API** (free real-time data for funded non-professional accounts).

---

## What it shows

1. **Regime**: VIX term structure, VRP, HY credit-spread percentile, yield-curve slope
2. **Stretch**: price vs. 50/200-DMA, realized-vol percentile
3. **Priced**: expected-move cone, put-call skew
4. **Why**: filtered, market-moving news feed

Per-underlying panel: IV Rank, IV Percentile, IVx, IV−HV (VRP), expected move, skew, term structure, delta-based probabilities.

---

## Setup

```bash
git clone <repo>
cd derivative-implied-pricing
python -m venv .venv && source .venv/bin/activate
pip install -e ".[notebooks,dev]"
cp config/config.example.toml config/config.toml
# Edit config/config.toml with tastytrade credentials and FRED API key
```

---

## Run (yfinance slice)

Collector, storage, and present layers on free yfinance OHLCV. No `config.toml` needed; it
defaults to the gitignored `data/` dir.

```bash
# 1. Collect bars into Parquet (hive-partitioned by day, idempotent)
python -m collector.yfinance_collector --interval 1d --period 10y   # daily, 10 years
python -m collector.yfinance_collector --interval 1h --period 2y    # hourly, Yahoo caps 1h at ~730d

# 2a. Terminal snapshot
python -m present.terminal --symbol SPY --interval 1h --tail 12

# 2b. Browser dashboard
streamlit run src/present/streamlit_app.py
```

With tastytrade credentials (copy `.env.example` to `.env` and fill in the client secret and
refresh token from a read-only OAuth app), the pages default to live tastytrade data and the
collector stores it:

```bash
python -m collector.tastytrade_collector     # market metrics for the universe, SPY and QQQ chains
```

The site opens on a landing page. Sign-in is a mock: any email and password, or "Continue with
the demo account", gets you into the app. A browser refresh signs you out.

Storage model: `docs/schema.md` (`ohlcv` table). tastytrade metrics/chains and the derive
layer (IVR/IVP/VRP/regime) build on this shape later.

*2026-07-10: yfinance OHLCV slice. Config loader, storage, collector, terminal and Streamlit frontends.*

---

## Docs

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Architecture, layout, dev orientation |
| `docs/schema.md` | DuckDB table DDL |
| `docs/open-decisions.md` | 5 open architectural decisions |
| `Project-Breif.md` | Full project brief, formulas, data sources |
