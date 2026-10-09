# Decisions

One entry per architectural decision: the question, what was decided, and when. Newest last.
Add an entry when a decision changes how data is collected, stored or shown.

## Streamlit for the interface

- Context: Jupyter, a terminal UI and a browser app were all candidates for the first view.
- Decision: a multipage Streamlit app, reachable on the LAN. The terminal snapshot was later
  removed; notebooks were never needed.
- Date: 2026-07-11.

## Own implied vol, not the vendor's

- Context: vendors publish IV from their own model and assumptions; Yahoo reports near-zero IV
  for illiquid contracts.
- Decision: providers return raw quotes only. IV and Greeks are solved in `derive` from the mark
  with the rate and dividend shown on the page, at read time, so stored quotes stay raw.
- Date: 2026-07-11.

## Point-in-time storage

- Context: overwrite the latest snapshot, or keep every pull with the time it was collected.
- Decision: append-only with `collected_at` for chains, metrics and reference data, deduplicated
  at read time. Bars are upserted, since a closed bar does not change.
- Date: 2026-10-07.

## Write-through gateway

- Context: analyze on the spot for the user, or store first and analyze from the store.
- Decision: both, in one step. Every pull goes through `collector.feed`, which returns the frame
  to the caller and appends it to the store.
- Date: 2026-10-07.

## Bars as one file per series

- Context: day partitions left `ohlcv` at 6,348 files and about 0.9 s per query.
- Decision: one Parquet file per symbol and interval, rewritten under a lock. The same six-series
  read takes about 0.03 s.
- Date: 2026-10-07.

## Mock sign-in

- Context: the product needs a signed-in experience; real accounts are out of scope.
- Decision: a session-only mock. Nothing is verified or stored; the app is not exposed publicly.
  Real authentication would replace `alphasurface.present.auth` alone.
- Date: 2026-10-07.

## Universe

- Context: which names beyond the index core to track.
- Decision: the core in `config/symbols.toml` (SPY, QQQ, IWM, DIA, the VIX family, TLT, IEF,
  HYG, GLD), seven liquid single names for tastytrade metrics (AAPL, NVDA, MSFT, AMZN, META, TSLA,
  GOOGL), and any symbol a user opens or adds to a watchlist, fetched and stored on demand.
- Date: 2026-10-08.

## Quotes from the DXLink streamer

- Context: tastytrade's REST quote snapshot returns 403 for this account.
- Decision: one DXLink streamer per process with a quote cache; REST only for metrics, chains and
  metadata.
- Date: 2026-10-08.

## Host and scheduling

- Context: the planned Linux server is not available.
- Decision: run on the Mac with launchd; keep systemd units for Linux and a Docker image for
  either (`deploy/`).
- Date: 2026-10-08.

## Name and package

- Context: generic top-level packages (`config`, `collector`, ...) risked import collisions.
- Decision: the project is Alpha Surface, one package `alphasurface` under `src/`.
- Date: 2026-10-08.

## Scenarios page withdrawn

- Context: the Scenarios page (Monte Carlo paths, position P&L, sizing, replay) is set aside for now.
- Decision: removed until later. The simulation engine stays because the Screener's
  options-or-underlying comparison uses it.
- Date: 2026-10-08.

## Pricer and pot odds as tools

- Context: both are calculators used alongside a contract, not destinations.
- Decision: dialogs opened from the Tools menu in the market bar and from the selected contract
  on the Options page, prefilled from it.
- Date: 2026-10-08.

## Open: historical options seed

- Context: Databento offers a one-time historical OPRA pull on free credit. Broad pulls burn
  credit fast.
- Decision: not yet. Revisit once the scheduled collector has run cleanly for a few weeks, and
  keep any pull narrow (SPY or SPX, a bounded window around known stress episodes).
