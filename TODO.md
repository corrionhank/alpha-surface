# TODO

Open work, highest value first. Finished items move to [CHANGELOG.md](CHANGELOG.md). Items marked
**needs OK** wait on an explicit go-ahead (bulk or historical data pulls, installing schedules,
anything outward-facing).

## Now

- [ ] Volatility: the live rate, dividend and `data.implied_vol()`; remove the remaining hardcoded
      rate default (the page is being rebuilt).
- [ ] Confirm against one live response whether tastytrade reports the risk-free rate and
      dividend yield as decimals or percents (`feed.as_fraction` guesses today).
- [ ] Throttle chain storage in the gateway itself, not only on the Options page: the scheduled
      scan and other callers still store every pull.

## Next

- [ ] Real-time quotes: the account reports delayed quotes. Check funding and the market-data
      agreements in the tastytrade account.
- [ ] Futures: front-month quotes, a futures options chain (`NestedFutureOptionChain`),
      Black-76 pricing, the CME calendar.
- [ ] Strategy studies: average, median, quartiles, swing, high and low, tail risk and hit rate
      for a rule, starting with 0DTE strangles opened 60 against 30 minutes before expiry.
- [ ] Scenarios, rebuilt with more substance before it returns to the nav.
- [ ] Type check: clear the mypy backlog, then make the CI step blocking.
- [ ] Coverage: page tests for the Dashboard, Charts and Research; raise the floor from 55%.
- [ ] Theme: drop dead CSS and helpers in `present/theme.py` (`.dtable`, `cell_bar`, unused
      serif and mono fonts). An earlier edit was refused by the permission check.
- [ ] Install the launchd schedule on the Mac (**needs OK**).
- [ ] Intraday history beyond 5 sessions of 5-minute bars and 30 of hourly (**needs OK**).

## Later

- [ ] Greeks and TheoPrice events from the streamer as a cross-check on the in-house model.
- [ ] Time and sales for the unusual-activity scan; put/call volume from `Underlying` events.
- [ ] Earnings and dividend markers on charts.
- [ ] Read-only import of tastytrade watchlists.
- [ ] Pricer and Scenarios priced from the chain's skew instead of one flat IV.
- [ ] Compact the per-pull reference Parquet files; show quote age; evict dead streamer symbols.
- [ ] Real authentication in place of the mock sign-in.
- [ ] Move collection to a Linux host when one is available.

## Decisions

- [ ] Delete the old public image `ghcr.io/corrionhank/derivative-implied-pricing`: its
      `sha-bf10437` tag was built from a tree that held the removed personal docs.
- [ ] License.
- [ ] Dependabot pull requests (the GitHub Actions bump, tastytrade `<14`): their branches went
      with the history rewrite; Dependabot reopens them on its next weekly run.
