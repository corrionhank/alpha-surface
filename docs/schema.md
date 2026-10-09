# Data schema

Everything lives under the data directory (`ALPHASURFACE_DATA_DIR`, else `[storage] data_dir`,
else `./data`). Parquet under `parquet/<table>/`, DuckDB views in `market.duckdb`. All timestamps
are UTC. Every pull goes through `alphasurface.collector.feed` or `alphasurface.collector.reference`
and is stored as it was returned (`docs/architecture.md`, data flow).

| Table | Source | Layout | Write | Read |
|---|---|---|---|---|
| `ohlcv` | Yahoo | `ohlcv/<interval>/<symbol>.parquet` | upsert, locked | DuckDB view |
| `option_chain` | tastytrade, Yahoo | day partitions, one file per pull | append | DuckDB view, deduplicated |
| `market_metrics` | tastytrade | day partitions, one file per pull | append | `storage.reference` |
| `iv_term` | tastytrade | day partitions, one file per pull | append | `storage.reference` |
| `etf_profile` | Yahoo | day partitions, one file per pull | append | `storage.reference` |
| `etf_holdings` | Yahoo | day partitions, one file per pull | append | `storage.reference` |
| `news` | Yahoo search, Finnhub | day partitions, one file per pull | append | `storage.reference` |
| `econ_calendar` | Yahoo, FRED fallback | day partitions, one file per pull | append | `storage.reference` |

Day partitions are `year=Y/month=M/day=D/`; files are named `<HHMMSSffffff>-<random id>.parquet`
and written to a temp name, then renamed, so a reader never sees half a file and two writers
never share one. A retried pull can leave the same rows twice; reads keep one per key.

## `ohlcv`

Daily (`1d`) and hourly (`1h`) bars. The VIX family is stored here with Yahoo's caret (`^VIX`).

| Column | Type | Notes |
|---|---|---|
| `ts` | TIMESTAMPTZ | bar open |
| `symbol` | VARCHAR | Yahoo symbol |
| `interval` | VARCHAR | `1d` or `1h` |
| `open`, `high`, `low`, `close` | DOUBLE | |
| `volume` | BIGINT | |

Key `(ts, symbol, interval)`. Each series is one file, merged under `ohlcv/.lock` and replaced by
an atomic rename (`storage.writer.write_ohlcv`). `storage.writer.compact_ohlcv` migrates the old
day-partitioned layout.

## `option_chain`

One row per contract per pull, raw quotes only. IV and Greeks are solved at read time from the
stored quote (`derive.option_metrics`, `derive.scan`), so they carry the page's rate and dividend.

| Column | Type | Notes |
|---|---|---|
| `collected_at` | TIMESTAMPTZ | when the quote was captured |
| `source` | VARCHAR | `tastytrade` or `yfinance`; synthetic chains are never stored |
| `symbol`, `expiry`, `strike`, `kind` | | `expiry` is `YYYY-MM-DD`, `kind` is `call` or `put` |
| `bid`, `ask`, `last` | DOUBLE | Yahoo reads 0 bid and ask outside market hours |
| `volume`, `open_interest` | DOUBLE | |
| `underlying` | DOUBLE | spot at capture |
| `underlying_prev` | DOUBLE | the underlying's prior close, when the provider gives it |
| `change` | DOUBLE | the option's last print minus its prior close, vendor-reported |
| `last_trade` | TIMESTAMPTZ | the option's last trade, when given |

Key `(collected_at, source, symbol, expiry, strike, kind)`. The view keeps one row per key:

```sql
CREATE VIEW option_chain AS
SELECT ... FROM read_parquet('.../option_chain/**/*.parquet', hive_partitioning=true, union_by_name=true)
QUALIFY row_number() OVER (PARTITION BY collected_at, source, symbol, expiry, strike, kind) = 1;
```

`storage.reader.previous_chain` returns the latest stored quote of each contract before a time,
which the Screener compares against. A full SPY or QQQ expiry is about 450 rows, 25 KB per pull.

## `market_metrics`

tastytrade `/market-metrics`, one row per symbol per pull, from `make collect` and from the
Dashboard when its copy is older than 15 minutes.

| Column | Unit | From tastytrade |
|---|---|---|
| `collected_at`, `source`, `symbol` | | |
| `ivx` | decimal | `implied-volatility-index`, 30-day constant-maturity IV |
| `ivx_5d_change` | decimal | `implied-volatility-index-5-day-change` |
| `iv_rank` | 0 to 1 | `implied-volatility-index-rank`, the primary rank; `iv_rank_source` says whose |
| `iv_rank_tw`, `iv_rank_tos` | 0 to 1 | the two published ranks |
| `iv_percentile` | 0 to 1 | `implied-volatility-percentile` |
| `iv30`, `hv30`, `hv60`, `hv90` | decimal | published in percent, divided by 100 on write |
| `iv_hv_diff` | vol points | `iv-hv-30-day-difference`, as published |
| `liquidity_rating`, `beta`, `corr_spy_3m` | | |
| `earnings_date`, `earnings_time` | date, BMO or AMC | `earnings.expected-report-date` |
| `dividend_ex_date`, `updated_at` | | |

Every vol and rank is stored as a decimal (`tests/test_tastytrade.py`). SPY's `ivx` matched VIX
on 2026-10-08 (15.4% against 15.41).

## `iv_term`

Same pull as `market_metrics`, one row per symbol and listed expiry from
`option-expiration-implied-volatilities`: `collected_at`, `source`, `symbol`, `expiry`
(`YYYY-MM-DD`), `settlement` (AM or PM), `chain_type`, `iv` (decimal). The per-name IV term
structure, kept so its history exists later.

## Reference tables

Refreshed in the background when the latest copy is older than its window (`docs/dashboard.md`).
Yields, expense ratios and returns are decimals; Yahoo's percent fields are converted on write.

| Table | Columns | Window | Key at read |
|---|---|---|---|
| `etf_profile` | `symbol`, `name`, `trailing_pe`, `forward_pe`, `price_to_book`, `dividend_yield`, `expense_ratio`, `total_assets`, `ytd_return`, `three_year_return`, `beta_3y`, `nav`, `week52_high`, `week52_low`, `category` | 6 h | `symbol` |
| `etf_holdings` | `fund`, `kind` (`holding` or `sector`), `rank`, `key`, `name`, `weight` | 6 h | `fund`, `kind` |
| `news` | `id`, `title`, `publisher`, `link`, `published`, `related`, `query` | 15 min | `id`, normalized title |
| `econ_calendar` | `event`, `region`, `time`, `period`, `actual`, `expected`, `last`, `revised`, `key` | 6 h | `event`, `region`, `time` |

Every row also carries `collected_at` and `source`.

## Local state

| File | Contents |
|---|---|
| `watchlists.json` | per-user watchlists, at most 60 symbols each |
| `alerts/state.json` | Screener alert history: when each hit last notified, each preset's last hit set |

Both are written whole through a temp file and a rename under an exclusive lock.

*2026-10-07: market-data gateway; `option_chain` append-only with read-time dedup; `ohlcv` one file per series, locked.*
*2026-10-08: `market_metrics` and `iv_term` from tastytrade; tastytrade chains stored.*
*2026-10-08: rewritten to the implemented tables; planned tables that were never built removed.*
