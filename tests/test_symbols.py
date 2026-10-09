"""One symbol, three spellings: the store's, tastytrade's and the one a page shows."""

from __future__ import annotations

import pytest

from alphasurface import symbols as sy


@pytest.mark.parametrize(
    "typed,store,shown,kind",
    [
        ("spy", "SPY", "SPY", "equity"),
        ("VIX", "^VIX", "VIX", "index"),
        ("^vix", "^VIX", "VIX", "index"),
        ("SPX", "^GSPC", "SPX", "index"),
        ("^SPX", "^GSPC", "SPX", "index"),
        ("^GSPC", "^GSPC", "SPX", "index"),
        ("/ES", "ES=F", "/ES", "future"),
        ("/ESZ26", "ES=F", "/ES", "future"),
        ("/ESZ26:XCME", "ES=F", "/ES", "future"),
        ("ES=F", "ES=F", "/ES", "future"),
    ],
)
def test_every_spelling_lands_on_one_store_symbol(typed, store, shown, kind):
    assert sy.to_store(typed) == store
    assert sy.display(typed) == shown
    assert sy.to_tasty(typed) == shown
    assert sy.kind(store) == kind


def test_descriptions_for_built_ins_only():
    assert sy.describe("SPX") == "S&P 500 Index"
    assert sy.describe("/ES") == "E-mini S&P 500"
    assert sy.describe("AAPL") == ""


def test_streamer_symbols(monkeypatch):
    assert sy.to_streamer("^VIX") == "VIX"
    assert sy.to_streamer("spx") == "SPX"
    assert sy.to_streamer("AAPL") == "AAPL"
    sy._front.clear()
    # Without tastytrade a future has no front month, so no live symbol.
    assert sy.to_streamer("/ES") is None
    sy._front.clear()

    from alphasurface.collector import tasty

    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(tasty, "front_month", lambda code: f"/{code}Z26:XCME")
    assert sy.to_streamer("ES=F") == "/ESZ26:XCME"
    sy._front.clear()


def test_front_month_failure_is_cached_briefly_not_for_a_day(monkeypatch):
    from alphasurface.collector import tasty

    sy._front.clear()
    calls = []
    monkeypatch.setattr(tasty, "ready", lambda: True)

    def boom(code):
        calls.append(code)
        raise RuntimeError("down")

    monkeypatch.setattr(tasty, "front_month", boom)
    assert sy.front_month("/ES") is None
    assert sy.front_month("/ES") is None
    assert calls == ["ES"]  # the failure is cached
    stamp, value = sy._front["/ES"]
    sy._front["/ES"] = (stamp - 3601, value)  # an hour later it asks again
    assert sy.front_month("/ES") is None and calls == ["ES", "ES"]
    sy._front.clear()
