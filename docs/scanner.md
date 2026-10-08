# Options scanner

Scans many option chains at once for the setups usually checked by hand. Every hit carries a
sentence saying why, with the numbers in it. A hit is a place to look, not a trade.

Code: rules in `src/derive/scan.py`, the options-or-underlying comparison in
`src/derive/vehicles.py`, fetching and alerts in `src/collector/scan.py` and
`src/collector/alerts.py`, the page in `src/present/scanner.py`.

## Data flow

```
provider -> collector/feed.py -> scan (in memory, on the spot)
                              -> option_chain / ohlcv in Parquet + DuckDB (for history)
```

Every chain and daily bar a scan fetches goes through the market-data gateway, so it is analyzed
right away and stored in the same step (`docs/schema.md`, "Data flow"). A scan compares against
the latest stored quote of each contract from before the run (`storage.reader.previous_chain`,
up to 4 days back); where there is none, against the vendor's prior close. Synthetic chains are
scanned but never stored or alerted on.

Each scan fetches only the expiries its date filter can use, nearest first, at most
`max_expiries` per symbol, and pauses 0.4 s between symbols. yfinance quotes are delayed about
15 minutes, and bid and ask read zero outside market hours; marks then fall back to the last
trade and anything that needs a spread is skipped.

## Normalizing

For each contract: mark = (bid + ask) / 2 when the market is two-sided, else the last print.
Spread = ask - bid, spread % = spread / mark, distance = K / S - 1. dte is calendar days from
today in New York. IV is our own Black-Scholes inversion of the mark (`derive.implied_vol`) with
the page's rate and dividend; delta, gamma and theta follow at that IV. Tenor is dte / 365 except
for same-day expiries, which use the session clock, minutes left / 390 / 252, so a 0DTE IV is
annualized over trading time like realized vol. Realized vol is close-to-close over 5, 10, 21 and
63 sessions of daily bars, with today's price appended while the session is open. ATM IV is the
call and put at the strike nearest spot, at the expiry nearest 30 days with at least 5 left.

Filters (sidebar, or `filters` in a saved scan): `dte_min`, `dte_max`, `zero_dte`, `dist_max`
(|K/S - 1|), `delta_min`/`delta_max` (absolute), `min_oi`, `min_volume`, `max_spread` ($),
`max_spread_pct`, `min_premium`, `side`. Everything except delta is applied before IV is solved.

## Presets

| Key | Name | Rule | Default thresholds | Default filters |
|---|---|---|---|---|
| `stale` | Stale after a move | underlying moved, option did not | move >= 1%, option moved <= 0.5 x expected, lag >= 2 spreads | 0 to 45 DTE, within 10%, delta >= 0.15, OI >= 100 |
| `rv_up` | Realized up, IV asleep | short RV / long RV >= ratio and ATM IV < short RV, or ATM IV fell since the last stored pull | ratio 1.5, 5 vs 21 sessions | 5 to 60 DTE, within 5% |
| `rich` | Rich premium | IV - RV >= gap | 5 vol pts over 21-day RV | 20 to 45 DTE, delta 0.10 to 0.30, spread <= 10%, OI >= 500 |
| `cheap` | Cheap convexity | OTM, IV - RV <= gap | -2 vol pts vs 21-day RV | 7 to 60 DTE, delta 0.05 to 0.35, spread <= 15%, OI >= 100 |
| `unusual` | Unusual activity | volume / OI and premium traded | ratio >= 2, premium >= $250,000, volume >= 500 | 0 to 60 DTE, within 20% |
| `spike` | Price spikes | today's move in daily RV units | abs(z) >= 2, 21-day RV | |
| `gaps` | Open gaps | gaps not yet filled, with base rate | gap >= 0.5%, last 10 sessions, 5-session base rate | |
| `zero_dte` | 0DTE map | straddle vs realized move to the close | 21-day RV | same-day only, within 3% |

### Stale after a move

With dS = S - S_ref since the reference (last stored quote, else prior close) and t the days
elapsed:

    expected = delta dS + gamma dS^2 / 2 + theta t
    actual   = mark - mark_ref
    lag      = expected - actual

A hit needs |dS / S_ref| >= move, |actual| <= lag_ratio x |expected|, lag on the same side as
expected, and |lag| >= min_spreads x spread, so a lag the spread would swallow is never shown.
Score: |lag| / spread. Prior-close reference: an option that has not traded today still sits at
its last print, so that print is its prior close; one that has traded uses last - change.

### Realized up, IV asleep

Per symbol: RV_short / RV_long >= ratio, and either ATM IV < RV_short or ATM IV below its value at
the last stored pull. Score: RV_short / RV_long. The second test needs stored history, so it
starts working from the second scan of a symbol.

### Rich premium, cheap convexity

Gap = (IV - RV_window) x 100 vol points, per contract. Rich: gap >= gap_min. Cheap: out of the
money only, gap <= gap_max; score -gap.

### Unusual activity

ratio = volume / max(OI, 1), premium traded = volume x mark x 100. All three thresholds must hold.
Open interest is as of the prior close, so a high ratio means today's volume opened new
positions or turned over the whole open interest. Score: the ratio.

### Price spikes

z = ln(S / prior close) / (RV_window / sqrt(252)). Score: |z|.

### Open gaps

A gap is a session whose open differs from the prior close. A gap up fills when a later low (the
same session counts) trades back to the prior close; a gap down when a high does. Hits are gaps
from the last `lookback` sessions still open. The base rate counts past gaps in the same direction
sized between half and twice this one, across all stored daily history, that filled within
`horizon` sessions, leaving out gaps too recent to have had the full horizon. It is a
frequency, not a forecast. Score: the base rate.

### 0DTE map

Per symbol with a same-day expiry while the session is open, m minutes left: the ATM straddle S_d
(call + put at the strike nearest spot) against realized vol's

    sd_rv = S x RV x sqrt(m / 390 / 252),   fair straddle = sqrt(2 / pi) x sd_rv ~ 0.8 sd_rv

Score: S_d / fair, the multiple of realized the market is charging for the rest of the day. The
reason also gives the straddle's own 1 SD, S_d / 0.8.

## Options or the underlying

For a target move m over h trading days, each vehicle is marked at the target, at an unchanged
price and over 4,000 GBM paths (`derive.vehicles.compare`):

- Shares, 100 (short shares for a bearish move, capital at 50% Reg T).
- Delta one at a margin: the same exposure for margin x notional, standing in for a future.
  Basis, roll and financing are left out.
- Calls (puts when bearish) in the money by m / 2, at the money, halfway to the target and at
  the target, one contract each, capital = premium. Options are valued with implied vol held at
  its entry level, h days later, with expiry - h days left.

Columns: capital, delta in shares, P&L and return on capital at the target, P&L if the price is
unchanged, max loss, breakeven at the horizon, then simulated EV, P(profit) and 95% VaR. Paths
drift at r - q by default (the market's neutral world) or, toggled, so the median path ends at the
target: mu = ln(1 + m) / t + sigma^2 / 2. Time is in trading days, 252 a year.

## Running it

```bash
python -m collector.scan --list                          # presets and saved scans
python -m collector.scan --preset rich --symbols SPY,QQQ,IWM
python -m collector.scan --preset stale --dte 0-21 --max-expiries 2
python -m collector.scan --preset zero_dte --dte 0 --symbols SPY,QQQ
python -m collector.scan --saved index_rich              # from config/scans.toml
```

Saved scans: copy `config/scans.example.toml` to `config/scans.toml`; the CLI reads it when it
exists, else the example. Each entry sets `preset`, `symbols`, optional `source`, `max_expiries`,
`[name.filters]` and `[name.params]`.

## Alerts

Off by default. In `config/config.toml`:

```toml
[notify]
enabled = true
macos = true            # local notification via osascript
ntfy_url = ""           # set e.g. "https://ntfy.sh/<private-topic>" to also push to a phone
cooldown_hours = 24
```

The CLI notifies on hits due for a notification: never notified before, or last notified more
than `cooldown_hours` ago. State is `data/alerts/state.json` under a file lock; it also records
each preset's last hit set, which is how the page shows "new since the last run". Nothing is sent
anywhere unless enabled; ntfy only when a URL is set. To scan on a schedule, run the CLI from
launchd or systemd like the collectors.

*2026-10-07: scanner, eight presets, write-through storage, opt-in alerts, options or the underlying.*
