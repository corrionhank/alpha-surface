# DuckDB Schema Design

Storage: Parquet files at `data/parquet/{table}/year={Y}/month={M}/day={D}/`, queried via DuckDB views. A `data/market.duckdb` file holds the view definitions and the `derived_metrics` table (computed, not raw data).

All timestamps are UTC (`TIMESTAMPTZ`). The `collected_at` column on every raw table enables point-in-time querying (see Open Decision #1).

---

## Table: `market_metrics`

Source: tastytrade `/market-metrics` endpoint. Collected hourly during market hours.

```sql
CREATE TABLE market_metrics (
    collected_at        TIMESTAMPTZ NOT NULL,
    symbol              VARCHAR     NOT NULL,
    -- Implied volatility (tastytrade pre-computed)
    iv                  DOUBLE,     -- 30-day constant-maturity IVx
    iv_rank             DOUBLE,     -- IVR: (current - 52w_low) / (52w_high - 52w_low)
    iv_percentile       DOUBLE,     -- IVP: fraction of last 252d with IV < current
    iv_5d_change        DOUBLE,     -- 5-day IV change (annualized)
    hv_30d              DOUBLE,     -- 30-day historical (realized) volatility
    iv_minus_hv         DOUBLE,     -- VRP proxy (IV − HV); positive = vol rich
    -- Expected move (pre-computed by tastytrade, in underlying price units)
    em_up               DOUBLE,     -- 1 SD expected move up
    em_down             DOUBLE,     -- 1 SD expected move down
    em_pct              DOUBLE,     -- expected move as % of spot
    -- Context
    beta_to_spy         DOUBLE,
    liquidity_rating    VARCHAR,    -- 'A', 'B', 'C', 'D'
    -- Spot price at collection time
    spot                DOUBLE,
    PRIMARY KEY (collected_at, symbol)
);
```

**Notes:**
- Compute own IVR in `derived_metrics` alongside tastytrade's for validation; they should agree within noise.
- `iv` = IVx (VIX-style variance-strip for the 30-day constant-maturity expiry). Tastytrade calls this "implied-volatility-index."

---

## Table: `option_chain`

Source: tastytrade option chains (dxFeed stream). Collected hourly. **Store only a strike band around spot** (~3 strikes each side per expiry for the key expirations), not full chains.

Key expirations to capture: weekly nearest + ~30 DTE + ~45 DTE + ~60 DTE.

```sql
CREATE TABLE option_chain (
    collected_at    TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR     NOT NULL,
    expiration      DATE        NOT NULL,
    dte             SMALLINT,               -- calendar days to expiry at collection
    strike          DOUBLE      NOT NULL,
    option_type     CHAR(1)     NOT NULL,   -- 'C' or 'P'
    -- Greeks (from dxFeed)
    iv              DOUBLE,                 -- per-strike implied vol (annualized)
    delta           DOUBLE,
    gamma           DOUBLE,
    theta           DOUBLE,
    vega             DOUBLE,
    rho             DOUBLE,
    -- Market
    bid             DOUBLE,
    ask             DOUBLE,
    mid             DOUBLE,                 -- (bid + ask) / 2
    last            DOUBLE,
    volume          INTEGER,
    open_interest   INTEGER,
    PRIMARY KEY (collected_at, symbol, expiration, strike, option_type)
);
```

**Notes:**
- Strike band: keep strikes between 0.85× and 1.15× spot (adjustable). This captures the core skew and covers typical 1–2 SD moves.
- Footprint: ~250–300 MB/year for the focused set; full chains ~3 GB/year (still within budget).
- The 25-delta risk reversal and put-call skew are derived: query IV at ~25Δ put vs. ~25Δ call.

---

## Table: `ohlcv`

Source: yfinance. Collected hourly (1h bars, up to 730d lookback) and daily.

```sql
CREATE TABLE ohlcv (
    ts          TIMESTAMPTZ NOT NULL,
    symbol      VARCHAR     NOT NULL,
    interval    VARCHAR     NOT NULL,   -- '1h', '1d'
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    PRIMARY KEY (ts, symbol, interval)
);
```

**Notes:**
- yfinance has no native 4h interval; resample from 1h if needed.
- Use `close` for HV computation (close-to-close log returns).
- 200-DMA and 50-DMA require ~200 daily bars; ensure the 1d series goes back far enough before computing.

---

## Table: `vix_complex`

Source: yfinance (`^VIX`, `^VIX1D`, `^VVIX`, `^VIX3M`). Also MOVE (bonds), GVZ (gold), OVX (oil) if yfinance carries them; otherwise from dedicated endpoints.

```sql
CREATE TABLE vix_complex (
    ts          TIMESTAMPTZ NOT NULL,
    series      VARCHAR     NOT NULL,   -- 'VIX', 'VIX1D', 'VVIX', 'VIX3M', 'MOVE', 'GVZ', 'OVX'
    value       DOUBLE      NOT NULL,
    interval    VARCHAR     NOT NULL,   -- '1h', '1d'
    PRIMARY KEY (ts, series, interval)
);
```

**Notes:**
- VIX3M − VIX term structure slope: positive = contango (normal, risk-on); negative = backwardation (fear, short-VIX unwind risk).
- VVIX: vol-of-vol; spikes signal hedging demand and fragile positioning.

---

## Table: `interest_rates`

Source: FRED API. Collected daily (EOD).

```sql
CREATE TABLE interest_rates (
    date        DATE    NOT NULL,
    series_id   VARCHAR NOT NULL,   -- FRED series ID (see config/symbols.toml)
    value       DOUBLE,             -- NULL on non-reporting days
    PRIMARY KEY (date, series_id)
);
```

Key series (see `config/symbols.toml` for full list):

| Series ID | Description |
|-----------|-------------|
| `T10Y2Y` | 10Y − 2Y yield spread (curve steepness) |
| `T10Y3M` | 10Y − 3M spread (Estrella recession indicator) |
| `BAMLH0A0HYM2EY` | ICE BofA HY OAS (credit stress) |
| `DFF` | Fed Funds Effective Rate |
| `DFII10` | 10Y TIPS yield (real rate) |
| `T10YIE` | 10Y breakeven inflation |

---

## Table: `vix_term_structure`

Source: `vix_utils` library (CBOE VIX-futures daily settlement). Collected daily (EOD).

```sql
CREATE TABLE vix_term_structure (
    date            DATE    NOT NULL,
    contract        VARCHAR NOT NULL,   -- e.g. 'F1' (front), 'F2', 'F3', ...
    settlement      DOUBLE,             -- futures settlement price
    expiry_date     DATE,               -- contract expiration date
    dte             SMALLINT,           -- calendar days to expiry
    contango_pct    DOUBLE,             -- (F2 - F1) / F1 × 100 (only on F1 row)
    PRIMARY KEY (date, contract)
);
```

**Notes:**
- Term structure shape (contango vs. backwardation) is a regime signal.
- VIX cash vs. F1 basis captures roll cost for short-vol strategies.

---

## Table: `news`

Source: Finnhub (free) + Marketaux (100 req/day). Collected periodically (every 30–60 min during market hours).

```sql
CREATE TABLE news (
    published_at    TIMESTAMPTZ NOT NULL,
    collected_at    TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR,                -- NULL for market-wide stories
    source          VARCHAR     NOT NULL,   -- 'finnhub', 'marketaux'
    headline        TEXT,
    summary         TEXT,
    sentiment       DOUBLE,                 -- provider sentiment: -1 (bearish) to +1 (bullish)
    url             VARCHAR,
    PRIMARY KEY (published_at, source, url)
);
```

---

## Table: `derived_metrics`

Computed by the `derive` layer and stored for trend-tracking. Written to the native DuckDB file (not Parquet).

```sql
CREATE TABLE derived_metrics (
    computed_at         TIMESTAMPTZ NOT NULL,
    symbol              VARCHAR     NOT NULL,
    -- Own-computed vol metrics (cross-validate against tastytrade)
    own_ivr             DOUBLE,     -- own IVR from stored IV history
    own_ivp             DOUBLE,     -- own IVP from stored IV history
    -- VRP in context
    vrp                 DOUBLE,     -- IV − HV (same as market_metrics.iv_minus_hv; cross-check)
    vrp_percentile      DOUBLE,     -- VRP in its own trailing history
    -- Price regime
    price_vs_50dma      DOUBLE,     -- % above/below 50-DMA
    price_vs_200dma     DOUBLE,     -- % above/below 200-DMA
    rv_percentile       DOUBLE,     -- 30d realized vol vs. last 252 trading days
    -- Skew (from option_chain: 25Δ put IV − 25Δ call IV)
    skew_25d            DOUBLE,
    -- Term structure
    term_structure_slope DOUBLE,    -- back IV − front IV (contango > 0)
    -- Regime flag (derived from VIX level + TS slope + VRP)
    regime              VARCHAR,    -- 'low_vol', 'normal', 'elevated', 'stress'
    PRIMARY KEY (computed_at, symbol)
);
```

---

## DuckDB views (in `market.duckdb`)

After writing Parquet files, register them as views:

```sql
-- market_metrics view
CREATE OR REPLACE VIEW market_metrics AS
SELECT * FROM read_parquet('data/parquet/market_metrics/**/*.parquet', hive_partitioning=true);

-- option_chain view
CREATE OR REPLACE VIEW option_chain AS
SELECT * FROM read_parquet('data/parquet/option_chain/**/*.parquet', hive_partitioning=true);

-- etc.
```

Hive partitioning by `year`/`month`/`day` lets DuckDB push down date filters without scanning all files.

---

## Open questions on schema (from Open Decision #1)

- **PIT-correct**: the `collected_at` column on all raw tables enables "what did we know at time T?" queries. This is the recommended design even for v1 — it costs nothing extra to collect and enables Phase-2 conditional base rates.
- **Deduplication**: the tastytrade collector runs hourly; if a run fails and retries, ensure upsert semantics (`INSERT OR REPLACE` / `ON CONFLICT DO UPDATE`) so duplicates don't accumulate in the Parquet files.
- **Partition granularity**: day-level partitioning is right for the hourly and daily series. Finer (hourly) partitioning isn't needed at this data volume.
