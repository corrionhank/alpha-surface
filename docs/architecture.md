# Architecture

Alpha Surface decodes what the options market has already priced (implied vol, expected moves,
skew, term structure) and sets it against what the market has actually done (realized vol,
ranges, gaps). It informs a decision; it never makes one.

## Principles

- Inform, do not predict. Every number is descriptive and shown in context (a percentile, a
  range, its own history), never as a buy or sell signal.
- Implied against realized is the core comparison: on the Dashboard by name, on the Options page
  by contract, in the Screener across chains.
- Read-only. The tastytrade connection is a live brokerage account. The OAuth app has the read
  scope and no code path places, cancels or changes an order.
- Data thrift. Free tiers and rate limits are finite: top up incrementally, never bulk re-pull.
- Seed history from day one. Implied vol history cannot be backfilled, so every pull is stored,
  append-only, with the time it was collected (point-in-time correct).
- About $0 a month: tastytrade data is free for a funded account, Yahoo is free.

## Layers

```
provider APIs -> collector -> storage (Parquet + DuckDB) -> derive -> present
                     \_____________ returned at once _______/
```

| Package | Role |
|---|---|
| `alphasurface.config` | Settings and secrets: `.env`, `config/config.toml`, `ALPHASURFACE_DATA_DIR` |
| `alphasurface.collector` | Providers and the gateway: `tasty` (session and streamer), `chains` (chain providers), `feed` (write-through gateway), `reference` (fund data, news, calendar), `scan` and `alerts` (Screener CLI), the collector CLIs |
| `alphasurface.storage` | `writer` (ohlcv series files, chain files), `reference` (append-only tables), `schema` (DuckDB views), `reader` |
| `alphasurface.derive` | Black-Scholes and implied vol, contract metrics, expected move, market state and regime, IV panel, sentiment, fund metrics, scanner rules, simulation and the options-or-underlying comparison, pot odds |
| `alphasurface.present` | Streamlit entry point, pages, theme, charts, market bar, data access with caching |

## Data flow

Every pull goes through `collector.feed`. The caller gets the frame back immediately and analyzes
it in memory; the same frame is appended to the store, so the backtest history builds up as a side
effect of using the app. A failed write is logged and never breaks the caller. Synthetic chains
are never stored.

- Bars: `feed.bars` reads the stored series and tops it up from Yahoo (a month for daily bars when
  the series is recent, the full history once for a new symbol), then writes the new bars back.
- Quotes: `feed.quotes` reads the tastytrade streamer's cache; the market bar and pages fall back
  to the last stored close when the streamer is unavailable.
- Chains: `feed.chain` calls the selected provider and appends to `option_chain`.
- Metrics: `feed.metrics` pulls tastytrade market metrics and stores `market_metrics` and
  `iv_term`. The Dashboard repulls when its copy is older than 15 minutes.
- Reference data: fund profiles, holdings, news and the calendar render from the latest stored
  copy and refresh in a background thread when older than their window (`docs/dashboard.md`).
- Schedules: the collectors also run on a timer (`deploy/`), so history accrues when the app is
  closed.

## Data sources

| Source | Data | Notes |
|---|---|---|
| tastytrade API (`tastytrade` SDK) | market metrics (IVx, IV rank and percentile, HV, earnings), per-expiry IV, option chains, live quotes over DXLink | Free real-time for funded accounts. Unofficial SDK, no vendor SLA. The REST quote snapshot returns 403 for this account, so quotes use the streamer. |
| Yahoo Finance (`yfinance`) | daily and hourly bars, the VIX family, fund profiles and holdings, news search, economic calendar, delayed chains | Unofficial and rate limited; hourly bars reach back about 730 days. |
| Finnhub (optional) | general market news | Only with `[news] finnhub_api_key`. |
| FRED (optional) | macro series for the Research page's Economy tab; release dates when Yahoo's calendar is unavailable | Only with `FRED_API_KEY`. |
| ntfy (optional) | Screener alerts to a phone | Only with `[notify] ntfy_url`. |

The Research page's other sources are listed with its tables in `docs/schema.md`.

Considered and not used: Massive (formerly Polygon) and Tradier, paid and redundant with
tastytrade; TradingView, which has no market-data API (its Lightweight Charts library renders the
price charts). A narrow Databento historical options pull remains an option (`docs/decisions.md`).

## Storage

Parquet under `data/parquet/`, queried through DuckDB; `data/market.duckdb` holds the views.
Tables and columns: `docs/schema.md`.

- `ohlcv`: one file per series, `ohlcv/<interval>/<symbol>.parquet`, upserted under a file lock
  and replaced by an atomic rename.
- `option_chain` and the reference tables (`market_metrics`, `iv_term`, `etf_profile`,
  `etf_holdings`, `news`, `econ_calendar`): append-only, one new file per pull in a
  `year=/month=/day=` partition, named by time and a random id. Writers never share a file;
  duplicates from a retry are dropped at read time.
- `data/watchlists.json` (per-user watchlists) and `data/alerts/state.json` (alert cooldowns):
  small JSON files written whole through a temp file under an exclusive lock.

Footprint: a full SPY or QQQ expiry is about 25 KB per pull. The store grows by megabytes a week
at the scheduled cadence.

## Caching and concurrency

- tastytrade: one session per process on a daemon thread that owns an asyncio loop; callers hand
  it work. At most 4 requests in flight; 429, 5xx and network errors back off exponentially with
  jitter, 4 tries at most. A failed sign-in is never retried until the process restarts, since
  repeated failures block the IP for about 8 hours.
- DXLink: one streamer per process with a cache of the latest Quote, Trade and Summary per
  symbol. A request subscribes only to symbols not yet cached, in batches of 500, capped at 4,000
  symbols (DXLink allows 5 sessions and 25,000 subscriptions).
- Streamlit: `st.cache_data` with short TTLs (quotes 15 to 20 s, bars and metrics minutes);
  the Charts view refreshes every 30 s while the market is open.
- DuckDB: the shared page connection refreshes its views at most every 30 s under a lock, so
  concurrent sessions never collide on the catalog. Reference reads use a private in-memory
  connection.

## Page layout

- Signed out: the landing page and the mock sign-in. Signed in: top navigation with Dashboard,
  Options, Screener, Charts, Volatility, Research and Docs. A page link while signed out goes
  through sign-in with `?next=`.
- Market bar, sticky under the nav on every page: index and vol tape, market status and data
  source, the Tools menu, the account menu.
- Tools: option pricer (Black-Scholes price, Greeks, value vs spot) and pot odds (breakeven win
  rate against implied and realized probabilities), opened as dialogs from the Tools menu or from
  the selected contract on the Options page, prefilled from it.
- Collapsible sidebar: page controls only (symbol, expiry, model inputs, filters).
- Fixed rails, never collapsible: the Dashboard's feeds (fear and greed, calendar, news) and the
  Charts watchlist.
- Panels: hairline cards with a header row (title left, as-of and tags right).

## Testing

`pytest` with no network: `tests/conftest.py` blocks tastytrade and Yahoo for every test. Pages
are exercised with Streamlit's `AppTest`. Tests that need stored bars skip on an empty store,
which is how CI runs (`ALPHASURFACE_DATA_DIR` points at an empty directory).
