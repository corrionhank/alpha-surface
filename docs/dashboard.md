# Overview dashboard

The cockpit page, `src/present/overview.py`. Most critical numbers first, then charts, implied
vol, sentiment, fund data, news, the calendar and the watchlist. Everything is context, not a
forecast or a signal.

## Data flow

```
provider (yfinance) -> collector.reference fetch -> { returned to the page now,
                                                      appended to Parquet for later }
```

- Market series (prices, the VIX family, TLT/IEF/HYG/GLD) are read from the `ohlcv` store in one
  batched query per 5 minutes. Seed with `python -m collector.yfinance_collector --interval 1d`.
- Fund profiles, holdings, news and the calendar are write-through. The page shows the latest
  stored copy immediately; when that copy is older than its window it refreshes in a background
  thread and the new copy appears on the next read (within a minute). Only an empty store waits,
  up to 8 seconds, for the first fetch. A failed fetch or write is logged and never breaks the page.

| Table | Source | Refresh window | Key |
|---|---|---|---|
| `etf_profile` | `yf.Ticker.info`, `funds_data.fund_operations` | 6 h | symbol |
| `etf_holdings` | `funds_data.top_holdings`, `sector_weightings` | 6 h | fund, kind (holding or sector) |
| `news` | `yf.Search` for S&P 500, Nasdaq 100, stock market, Federal Reserve; Finnhub general if `[news] finnhub_api_key` is set | 15 min | id, normalized headline |
| `econ_calendar` | `yf.Calendars` economic events, 3 days back to 10 ahead, paged 100 at a time; FRED release dates only if Calendars is unavailable and `[fred] api_key` is set | 6 h | event, region, time |

Each table is hive-partitioned Parquet under `data/parquet/<table>/year=/month=/day=/`, one new
file per fetch (time plus random id), `collected_at` and `source` on every row, duplicates
dropped at read time (`storage/reference.py`). `Ticker.news` returns nothing in yfinance 1.4.1,
so news uses search.

Units as stored: yields, expense ratios and returns are decimals. Yahoo reports `ytdReturn` and
`netExpenseRatio` in percent; both are converted.

## KPI band

| Tile | Definition |
|---|---|
| SPY, QQQ | last close; change over 1, 5, 21 sessions |
| VIX, VXN | level; point change over 1, 5, 21 sessions |
| Priced move today | VIX1D / sqrt(252), the one-day 1 SD move in %; VIX / sqrt(252) when VIX1D is missing |
| Regime | `derive.market_state.regime` (VIX level, term slope, VRP), formulas section 12 |
| Fear and greed lens | below |
| Implied minus realized | VIX minus SPY 21-day realized; VXN minus QQQ 21-day realized; percentile of own history |
| Term structure | VIX3M / VIX; above 1 is contango |
| SPY vs 200-day | % from the 200-day average, its percentile, % off the 52-week high |
| SKEW | level and point changes |

## Implied vol panel

VIX, VXN, VIX1D, VIX9D, VIX3M, VIX6M, VVIX, SKEW: level, point change over 1 / 5 / 21 sessions,
and the percentile of today's level within the last 252 sessions (`derive/iv_panel.py`).

Term curve: VIX1D (1 day), VIX9D (9), VIX (30), VIX3M (93), VIX6M (186) on the last date every
tenor printed, against 5 and 21 sessions earlier. Upward sloping is contango.

## Fear and greed lens

Our own composite from stored prices (`derive/sentiment.py`), not CNN's index. Six components,
each the percentile of today's value within its own history up to today (expanding, no
look-ahead, at least 252 sessions), oriented so 100 is greed, then averaged with equal weight:

| Component | Value | Greed when |
|---|---|---|
| VIX vs 50-day | VIX / 50-day average of VIX - 1 | low (inverted) |
| SPY vs 125-day | SPY / 125-day average - 1 | high |
| Term structure | VIX3M / VIX | high (contango) |
| Safe-haven demand | SPY 20-day return - TLT 20-day return | high |
| Junk-bond demand | HYG 20-day return - IEF 20-day return | high |
| Realized vol | SPY 21-day close-to-close vol | low (inverted) |

Bands: under 25 extreme fear, 25 to 45 fear, 45 to 55 neutral, 55 to 75 greed, 75 and up extreme
greed. Status color only at the extremes and the fear/greed bands, always with the word.

## Fund cards

Trailing P/E, price to book, dividend yield, expense ratio, assets, year to date, 3-year average
return, and where the last close sits in the 52-week range. Top 10 holdings with weights, their
combined weight, and effective names = 1 / sum of squared shares within the top 10
(`derive/funds.py`). The six largest sectors.

## News and calendar

News: last 48 hours across every stored pull, deduplicated by id and by normalized headline,
newest first, linked to the source. Calendar: US events, times Eastern, from two days back.
Key releases (default view) match CPI, PPI, PCE, payrolls, claims, GDP, retail sales, ISM, FOMC,
fed funds, JOLTS, sentiment and durable goods.

*2026-10-07: dashboard rebuilt: KPI band, SPY/QQQ charts, IV panel and term curve, fear and greed lens, fund cards, news, calendar.*
