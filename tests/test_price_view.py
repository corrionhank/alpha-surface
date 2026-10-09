"""The quote header: live in the session, the official close outside it with the extended-hours
mark beside it, and the feed's close when the store has not caught up with the last session."""

from __future__ import annotations

import pandas as pd

from alphasurface import clock
from alphasurface.present import data

ET = "America/New_York"


def _daily(*closes_by_date: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [pd.Timestamp(d).tz_localize(ET).tz_convert("UTC") for d, _ in closes_by_date],
            "close": [c for _, c in closes_by_date],
        }
    )


def _q(last: float, prev: float, close: float = float("nan")) -> dict:
    return {"last": last, "prev": prev, "close": close}


def test_in_session_the_live_mark_against_the_prior_close(monkeypatch):
    monkeypatch.setattr(data, "feed_label", lambda: "tastytrade real-time")
    now = pd.Timestamp("2026-10-08 11:00", tz=ET)
    daily = _daily(("2026-10-06", 100.0), ("2026-10-07", 101.0), ("2026-10-08", 102.5))
    px, ref, label, ext = data.price_view(daily, _q(102.0, 101.0), now)
    assert (px, ref, ext) == (102.0, 101.0, None) and label.startswith("tastytrade real-time")


def test_after_the_close_the_official_close_and_the_after_hours_mark():
    now = pd.Timestamp("2026-10-08 18:30", tz=ET)
    daily = _daily(("2026-10-07", 101.0), ("2026-10-08", 102.0))
    px, ref, label, ext = data.price_view(daily, _q(102.4, 101.0, 102.0), now)
    assert (px, ref, label) == (102.0, 101.0, "At close Oct 8")
    assert ext == ("After hours", 102.4)


def test_before_the_open_the_extended_mark_reads_pre_market():
    now = pd.Timestamp("2026-10-09 08:00", tz=ET)
    daily = _daily(("2026-10-07", 101.0), ("2026-10-08", 102.0))
    *_, ext = data.price_view(daily, _q(103.0, 102.0), now)
    assert ext == ("Pre-market", 103.0)


def test_a_store_behind_the_last_session_takes_the_feed_close():
    now = pd.Timestamp("2026-10-08 18:30", tz=ET)
    stale = _daily(("2026-10-06", 100.0), ("2026-10-07", 101.0))
    # Before the feed rolls over: its day close is Oct 8's close.
    px, ref, label, _ = data.price_view(stale, _q(102.4, 101.0, 102.0), now)
    assert (px, ref, label) == (102.0, 101.0, "At close Oct 8")
    # After it rolls: no day close yet, and its prior close is Oct 8's.
    px, ref, label, _ = data.price_view(stale, _q(102.4, 102.0), now)
    assert (px, ref, label) == (102.0, 101.0, "At close Oct 8")


def test_last_close_skips_weekends_and_holidays():
    assert (
        clock.last_close(pd.Timestamp("2026-10-10 12:00", tz=ET)).date()
        == pd.Timestamp("2026-10-09").date()
    )
    assert (
        clock.last_close(pd.Timestamp("2026-11-27 09:00", tz=ET)).date()
        == pd.Timestamp("2026-11-25").date()
    )
    assert (
        clock.last_close(pd.Timestamp("2026-11-27 13:05", tz=ET)).date()
        == pd.Timestamp("2026-11-27").date()
    )
