# DuckDB Schema Design

Storage: Parquet under `data/parquet/{table}/`, queried via DuckDB views. `ohlcv` is one file per series, `ohlcv/{interval}/{symbol}.parquet` (2026-10-07; day partitions made every query open thousands of files). Append-only tables (`option_chain` and the reference tables) are partitioned `year={Y}/month={M}/day={D}/`, one file per pull. A `data/market.duckdb` file holds the view definitions and the `derived_metrics` table (computed, not raw data).

All timestamps are UTC (`TIMESTAMPTZ`). The `collected_at` column on every raw table enables point-in-time querying (see Open Decision #1).

---

## Table: `market_metrics` (implemented 2026-10-08)

Source: tastytrade `/market-metrics`, through `collector.feed.metrics()`. Written by
`python -m collector.tastytrade_collector` and by the overview page when its copy is older than
15 minutes. Append-only, one file per pull under `data/parquet/market_metrics/year=/month=/day=/`,
read with `storage.reference`.

| Column | Unit | From tastytrade |
|---|---|---|
| `collected_at`, `source` | UTC, `tastytrade` | |
| `symbol` | | |
| `ivx` | decimal | `implied-volatility-index`: 30-day constant-maturity IV |
| `ivx_5d_change` | decimal | `implied-volatility-index-5-day-change` |
| `iv_rank` | 0 to 1 | `implied-volatility-index-rank`, the primary rank; `iv_rank_source` says whose |
| `iv_rank_tw`, `iv_rank_tos` | 0 to 1 | tastytrade's two published ranks |
| `iv_percentile` | 0 to 1 | `implied-volatility-percentile` |
| `iv30`, `hv30`, `hv60`, `hv90` | decimal | published in percent (15.41), divided by 100 here |
| `iv_hv_diff` | vol points | `iv-hv-30-day-difference`, kept in points as published |
| `liquidity_rating`, `beta`, `corr_spy_3m` | | |
| `earnings_date`, `earnings_time` | date, BMO/AMC | `earnings.expected-report-date` |
| `dividend_ex_date`, `updated_at` | | |

Units are normalized on write (tests/test_tastytrade.py): every vol and rank is a decimal. SPY's
`ivx` was checked against VIX on 2026-10-08 (15.4% against 15.41).

## Table: `iv_term`

Same source and pull as `market_metrics`: one row per symbol and listed expiry from
`option-expiration-implied-volatilities`. Columns `collected_at`, `source`, `symbol`, `expiry`
(YYYY-MM-DD), `settlement` (AM/PM), `chain_type`, `iv` (decimal). The per-name IV term structure,
kept from day one so its history exists later.

---

## Data flow: the market-data gateway

```
provider (collector/chains.py, yfinance bars)
    -> collector/feed.py
         -> caller, at once: pages and scans analyze the frame in memory
         -> Parquet + DuckDB: option_chain (append-only), ohlcv (upsert)
```

Every pull goes through `collector.feed`: the chain and surface pages, the scanner page and
`python -m collector.scan` alike. The caller gets the frame back immediately; the same frame is
stored for backtests. A failed write is logged and never breaks the caller. Synthetic chains are
never stored. A tastytrade provider plugs in behind `feed.chain()` with no caller changing.

Concurrency (several Streamlit sessions plus the CLI): `option_chain` writes each pull as its own
new file (`HHMMSSffffff-<uuid>.parquet` in the day partition, written to a temp name and renamed),
so writers never share a file and nothing is re-read on write; duplicates from a retry are
dropped at read time by the view. `ohlcv` keeps its read-modify-write upsert, now under an
exclusive file lock (`ohlcv/.lock`) and a temp-file rename.

---

## Table: `option_chain`

Source: any chain provider through `collector.feed` (yfinance today, tastytrade later). One row per
contract per pull, raw quotes only. Implied vol and Greeks are solved at read time from the stored
quote (`derive.scan`, `derive.option_metrics`), so they carry our rate and dividend assumptions.
Implemented 2026-10-07 (`storage/schema.py`, `storage/writer.append_chain`).

```sql
-- Parquet: data/parquet/option_chain/year=Y/month=M/day=D/<HHMMSSffffff>-<uuid>.parquet
CREATE VIEW option_chain AS
SELECT collected_at, source, symbol, expiry, strike, kind, bid, ask, last, volume,
       open_interest, underlying, underlying_prev, change, last_trade
FROM read_parquet('.../option_chain/**/*.parquet', hive_partitioning=true, union_by_name=true)
QUALIFY row_number() OVER (
    PARTITION BY collected_at, source, symbol, expiry, strike, kind) = 1;
```

| Column | Type | Meaning |
|---|---|---|
| `collected_at` | TIMESTAMPTZ | when the quote was captured (the provider's `ts`), UTC |
| `source` | VARCHAR | provider name, e.g. `yfinance` |
| `symbol`, `expiry`, `strike`, `kind` | | the contract; `expiry` is `YYYY-MM-DD`, `kind` is `call` or `put` |
| `bid`, `ask`, `last` | DOUBLE | as quoted; yfinance reads 0 bid and ask outside market hours |
| `volume`, `open_interest` | DOUBLE | as quoted |
| `underlying` | DOUBLE | spot at capture |
| `underlying_prev` | DOUBLE | the underlying's prior session close, when the provider gives it |
| `change` | DOUBLE | the option's last print minus its prior close, vendor-reported |
| `last_trade` | TIMESTAMPTZ | the option's last trade time, when given |

Primary key `(collected_at, source, symbol, expiry, strike, kind)`. The chain page stores one expiry
per pull, the surface page up to ten, a scan the expiries its date filter allows (at most
`max_expiries`). `storage.reader.previous_chain` returns the latest stored quote of every contract
before a time, which is what scans compare against. Footprint: a full SPY or QQQ expiry is about 450
rows, about 25 KB of Parquet per pull (measured 2026-10-07).

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

-- option_chain view: see the table section above (read-time dedup with QUALIFY)

-- etc.
```

Hive partitioning by `year`/`month`/`day` lets DuckDB push down date filters without scanning all files.

---

## Open questions on schema (from Open Decision #1)

- **PIT-correct**: the `collected_at` column on all raw tables enables "what did we know at time T?" queries. This is the recommended design even for v1 — it costs nothing extra to collect and enables Phase-2 conditional base rates.
- **Deduplication**: the tastytrade collector runs hourly; if a run fails and retries, ensure upsert semantics (`INSERT OR REPLACE` / `ON CONFLICT DO UPDATE`) so duplicates don't accumulate in the Parquet files.
- **Partition granularity**: day-level partitioning is right for the hourly and daily series. Finer (hourly) partitioning isn't needed at this data volume.

*2026-10-07: market-data gateway (`collector/feed.py`); `option_chain` implemented as append-only files with read-time dedup; `ohlcv` writes locked.*
*2026-10-08: `market_metrics` and `iv_term` implemented from tastytrade; `option_chain` now also holds `source = 'tastytrade'` pulls (DXLink streamer quotes).*
