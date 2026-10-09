# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install          # editable install with dev tools, then the pre-commit hooks
make check            # lint, type check, tests
```

`make install-locked` installs the exact versions CI uses from `requirements-dev.lock`.

## Workflow

- Branch from `main` (`feature/<topic>`, `fix/<topic>`); open a pull request; CI must pass.
- Commit messages: two or three plain sentences saying what changed and why. No AI or tool
  attribution lines (`Co-Authored-By` and similar).
- Before a pull request: `make lint` and `make test` pass, and new behavior has a test. Tests
  never touch the network: `tests/conftest.py` blocks tastytrade and Yahoo. A test that must hit a
  real provider is marked `@pytest.mark.live` and runs only with `pytest -m live`.
- When behavior changes, update the doc that describes it and add a line to `CHANGELOG.md`.

## Rules

- Read-only. Nothing may place, cancel or change an order, including in tests.
- Data thrift. No bulk or historical pulls from metered or capped sources; top up incrementally.
- Secrets live only in `.env` (gitignored). Never print, log or commit them.
- Writing style: `docs/ai-policy.md`. The UI style guide (`.claude/STYLE_GUIDE.md`) is kept
  locally and not in the repository.

## Adding a data provider

Option chains: implement a class in `src/alphasurface/collector/chains.py` with
`expirations(symbol)`, `spot(symbol)`, `quote(symbol)` and `chain(symbol, expirations)` returning
`CHAIN_COLUMNS` (raw quotes only; implied vol and Greeks are solved in `alphasurface.derive`),
then register it in `PROVIDERS`. Pages and the Screener reach it through the gateway in
`src/alphasurface/collector/feed.py`, which returns each pull to the caller and appends it to
`option_chain`, so no page changes.

Other data (bars, metrics, reference tables) also enters through `alphasurface.collector.feed`
or `alphasurface.collector.reference`, which store every pull. Document a new table in
`docs/schema.md`.
