# derivative-implied-pricing

Personal market analytics dashboard — a custom watchlist aggregating options pricing, implied volatility, expected moves, VRP, regime signals, and cross-asset vol. Decodes what the options market has already priced in to inform trade decisions. Built on the **tastytrade API** (free real-time data for funded non-professional accounts).

---

## What it shows

1. **Regime** — VIX term structure, VRP, HY credit-spread percentile, yield-curve slope
2. **Stretch** — price vs. 50/200-DMA, realized-vol percentile
3. **Priced** — expected-move cone, put-call skew
4. **Why** — filtered, market-moving news feed

Per-underlying panel: IV Rank, IV Percentile, IVx, IV−HV (VRP), expected move, skew, term structure, delta-based probabilities.

---

## Setup

```bash
git clone <repo>
cd derivative-implied-pricing
python -m venv .venv && source .venv/bin/activate
pip install -e ".[notebooks,dev]"
cp config/config.example.toml config/config.toml
# Edit config/config.toml — tastytrade credentials, FRED API key
```

---

## Docs

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Architecture, layout, dev orientation |
| `docs/schema.md` | DuckDB table DDL |
| `docs/open-decisions.md` | 5 open architectural decisions |
| `Project-Breif.md` | Full project brief, formulas, data sources |
