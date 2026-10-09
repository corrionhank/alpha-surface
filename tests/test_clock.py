"""The market clock: regular sessions on the NYSE calendar, holidays and 13:00 half days honored."""

from __future__ import annotations

import pandas as pd
import pytest

from alphasurface import clock

ET = "America/New_York"


def at(stamp: str) -> pd.Timestamp:
    return pd.Timestamp(stamp, tz=ET)


@pytest.mark.parametrize(
    "stamp,open_",
    [
        ("2026-10-07 09:29", False),  # Wednesday, before the bell
        ("2026-10-07 09:30", True),
        ("2026-10-07 15:59", True),
        ("2026-10-07 16:00", False),
        ("2026-10-10 12:00", False),  # Saturday
        ("2026-11-26 11:00", False),  # Thanksgiving
        ("2026-11-27 12:59", True),  # the day after: closes at 13:00
        ("2026-11-27 13:00", False),
        ("2026-12-25 11:00", False),  # Christmas
    ],
)
def test_is_open(stamp, open_):
    assert clock.is_open(at(stamp)) is open_


def test_session_bounds_and_half_days():
    open_, close = clock.session(at("2026-11-27 08:00"))
    assert open_.tz_convert(ET) == at("2026-11-27 09:30")
    assert close.tz_convert(ET) == at("2026-11-27 13:00")
    assert clock.session(at("2026-11-26 10:00")) is None


def test_next_open_skips_the_weekend_and_holidays():
    assert clock.next_open(at("2026-10-09 17:00")).tz_convert(ET) == at("2026-10-12 09:30")
    assert clock.next_open(at("2026-11-25 17:00")).tz_convert(ET) == at("2026-11-27 09:30")


def test_minutes_to_close():
    assert clock.minutes_to_close(at("2026-10-07 08:00")) == pytest.approx(390)
    assert clock.minutes_to_close(at("2026-10-07 15:30")) == pytest.approx(30)
    assert clock.minutes_to_close(at("2026-10-07 17:00")) == 0
    assert clock.minutes_to_close(at("2026-11-27 08:00")) == pytest.approx(210)  # half day
    assert clock.minutes_to_close(at("2026-11-26 10:00")) == 0


def test_sessions_back_bounds_an_intraday_window():
    # Monday morning: five sessions back is the Monday before, not a weekend day.
    assert clock.sessions_back(1, at("2026-10-12 10:00")).tz_convert(ET) == at("2026-10-12 09:30")
    assert clock.sessions_back(5, at("2026-10-12 10:00")).tz_convert(ET) == at("2026-10-06 09:30")
