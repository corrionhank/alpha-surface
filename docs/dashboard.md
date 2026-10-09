# Dashboard

The first page after sign-in (`alphasurface.present.overview`). Most critical numbers first,
then charts, implied vol, fund data and the index table, with the feeds in a fixed right rail.
Everything is context, not a forecast or a signal.

## Data

- Market series (index ETFs, the VIX family, TLT, IEF, HYG, GLD) come from the `ohlcv` store
  through `present.data`, topped up live and read in one batched query every 5 minutes. Seed with
  `make collect-bars`. During the session the header shows live tastytrade marks.
- Implied vs realized by name uses the latest stored `market_metrics`; when that copy is older
  than 15 minutes and credentials are set, the page pulls again through the gateway, which stores
  it, so page views add to the IV history.
- Fund profiles, holdings, news and the calendar are write-through. The page shows the latest
  stored copy at once; when it is older than its window it refreshes in a background thread and the
  new copy appears on the next read. Only an empty store waits, up to 8 seconds, for the first
  fetch. A failed fetch or write is logged and never breaks the page.

| Table | Source | Refresh window |
|---|---|---|
| `etf_profile` | `yf.Ticker.info`, `funds_data.fund_operations` | 6 h |
| `etf_holdings` | `funds_data.top_holdings`, `sector_weightings` | 6 h |
| `news` | `yf.Search` for S&P 500, Nasdaq 100, stock market, Federal Reserve; Finnhub general news if `[news] finnhub_api_key` is set | 15 min |
| `econ_calendar` | `yf.Calendars` economic events, 3 days back to 10 ahead; FRED release dates only if Yahoo's calendar is unavailable | 6 h |

Columns and storage: `docs/schema.md`. `Ticker.news` returns nothing in yfinance 1.4.1, so news
uses search.

## KPI band

| Tile | Definition |
|---|---|
| SPY, QQQ | last; change over 1, 5, 21 sessions |
| VIX, VXN | level; point change over 1, 5, 21 sessions |
| Priced move today | VIX1D / sqrt(252), the one-day 1 SD move in %; VIX / sqrt(252) when VIX1D is missing |
| Regime | `derive.market_state.regime` (VIX level, term slope, VRP), formulas section 12 |
| Fear and greed | the lens below, its label and its reading a week ago |
| SPY, QQQ implied minus realized | VIX minus SPY 21-day realized; VXN minus QQQ 21-day realized; percentile of own history |
| Term structure | VIX3M / VIX; above 1 is contango |
| SPY vs 200-day | % from the 200-day average, its percentile, % off the 52-week high |
| SKEW | level and point changes (VVIX when SKEW is missing) |

## Charts

SPY and QQQ daily candles over six months, with 1, 3 and 6-month changes and 21-day realized vol
in the header.

## Implied vs realized vol

One row per name from tastytrade metrics: a dumbbell on a shared vol axis from 30-day realized
(hollow) to IVx (filled), then IVx, HV30, IV / HV, IV rank and earnings within 60 days. Sorted by
IV / HV, richest first; a dotted segment marks implied below realized.

## Implied vol panel and term curve

VIX, VXN, VIX1D, VIX9D, VIX3M, VIX6M, VVIX, SKEW: level, point change over 1, 5 and 21 sessions,
and the percentile of today's level within the last 252 sessions (`derive.iv_panel`).

Term curve: VIX1D (1 day), VIX9D (9), VIX (30), VIX3M (93), VIX6M (186) on the last date every
tenor printed, against 5 and 21 sessions earlier. Upward sloping is contango.

## Expected move

The 1 and 2 SD cone for a universe symbol over 1W, 2W, 1M or 2M (`derive.expected_move`, formulas
section 5), from VIX for SPY, VXN for QQQ, and 21-day realized vol for the rest.

## Fund cards

Trailing P/E, price to book, dividend yield, expense ratio, assets, year to date, 3-year average
return, and where the last close sits in the 52-week range. Top 10 holdings with weights, their
combined weight, and effective names = 1 / sum of squared shares within the top 10
(`derive.funds`). The six largest sectors.

## Index and cross-asset ETFs

The universe plus TLT, IEF, HYG and GLD: last, change over 1 day, 1 week and 1 month, distance
from the 50 and 200-day averages, 21-day realized vol and its 1-year percentile, drawdown.

## Right rail

**Fear and greed.** Our own composite from stored prices (`derive.sentiment`), not CNN's index.
Six components, each the percentile of today's value within its own history up to today
(expanding, no look-ahead, at least 252 sessions), oriented so 100 is greed, then averaged with
equal weight:

| Component | Value | Greed when |
|---|---|---|
| VIX vs 50-day | VIX / 50-day average of VIX - 1 | low (inverted) |
| SPY vs 125-day | SPY / 125-day average - 1 | high |
| Term structure | VIX3M / VIX | high (contango) |
| Safe-haven demand | SPY 20-day return - TLT 20-day return | high |
| Junk-bond demand | HYG 20-day return - IEF 20-day return | high |
| Realized vol | SPY 21-day close-to-close vol | low (inverted) |

Bands: under 25 extreme fear, 25 to 45 fear, 45 to 55 neutral, 55 to 75 greed, 75 and up extreme
greed. Status color only at the extremes and the fear and greed bands, always with the word.

**Economic calendar.** US events, times Eastern, from two days back. Key releases (default view)
match CPI, PPI, PCE, payrolls, claims, GDP, retail sales, ISM, FOMC, fed funds, JOLTS, sentiment
and durable goods. The Research page's Economy tab carries the calendar too.

**Market news.** Last 48 hours across every stored pull, deduplicated by id and by normalized
headline, newest first, linked to the source.

*2026-10-07: dashboard rebuilt: KPI band, SPY and QQQ charts, IV panel and term curve, fear and greed lens, fund cards, news, calendar.*
*2026-10-08: implied vs realized by name from tastytrade metrics; feeds moved to a fixed right rail.*
