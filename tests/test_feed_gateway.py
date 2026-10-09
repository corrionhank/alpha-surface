"""The live-data gateway (collector.feed) offline: tastytrade is faked function by function, the
store is a temporary directory, and every fallback is exercised."""

from __future__ import annotations

import dataclasses
import math
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from alphasurface import clock
from alphasurface.collector import chains, feed, tasty
from alphasurface.config import load_config
from alphasurface.storage import reference, writer

ET = "America/New_York"
NOW = pd.Timestamp("2026-10-08 15:00", tz=ET).tz_convert("UTC")


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(load_config(), data_dir=tmp_path)


def _daily(cfg, symbol: str, closes: list[float], end: str = "2026-10-08") -> None:
    days = pd.bdate_range(end=end, periods=len(closes))
    writer.write_ohlcv(
        pd.DataFrame(
            {
                "ts": [pd.Timestamp(d).tz_localize(ET).tz_convert("UTC") for d in days],
                "symbol": symbol,
                "interval": "1d",
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": 1,
            }
        ),
        cfg,
    )


def _metrics(cfg, rows: list[dict], at: pd.Timestamp = NOW) -> None:
    reference.append(
        pd.DataFrame([{"collected_at": at, "source": "tastytrade", **r} for r in rows]),
        "market_metrics",
        cfg,
    )


# --- Units and feed status ------------------------------------------------------------------


def test_as_fraction_reads_percent_or_decimal():
    assert feed.as_fraction(4.2) == pytest.approx(0.042)
    assert feed.as_fraction(0.042) == pytest.approx(0.042)
    assert feed.as_fraction(4.2, reference=0.041) == pytest.approx(0.042)
    assert feed.as_fraction(0.2, reference=0.002) == pytest.approx(0.002)  # 0.2% stated as 0.2
    assert math.isnan(feed.as_fraction(float("nan")))


@pytest.mark.parametrize(
    "delayed,label",
    [(True, "tastytrade delayed"), (False, "tastytrade real-time"), (None, "tastytrade")],
)
def test_feed_label(monkeypatch, delayed, label):
    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(tasty, "feed_status", lambda: {"delayed": delayed, "level": "demo"})
    assert feed.feed_label() == label


def test_feed_label_without_credentials_or_on_error(monkeypatch):
    assert feed.feed_label() == ""  # conftest: not ready
    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(tasty, "feed_status", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert feed.feed_label() == ""


# --- Candles --------------------------------------------------------------------------------


def _candle(t: pd.Timestamp, px: float) -> NS:
    return NS(time=int(t.timestamp() * 1000), open=px, high=px + 1, low=px - 1, close=px, volume=10)


def test_candles_are_bounded_and_stored_under_the_store_symbol(monkeypatch):
    seen = {}

    def fake(streamer, interval, start):
        seen.update(streamer=streamer, interval=interval, start=start)
        return [_candle(NOW - pd.Timedelta(minutes=5 * i), 6000.0 + i) for i in range(3)]

    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(tasty, "candles", fake)
    df = feed.candles("SPX", "5m", now=NOW)
    assert seen["streamer"] == "SPX" and seen["interval"] == "5m"
    # Never further back than five sessions: no historical pull without a go-ahead.
    assert pd.Timestamp(seen["start"]) >= clock.sessions_back(5, NOW)
    assert list(df.columns) == [
        "ts",
        "symbol",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    assert set(df["symbol"]) == {"^GSPC"} and len(df) == 3


def test_candles_start_from_the_last_stored_bar_when_current(monkeypatch):
    seen = {}
    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(
        tasty, "candles", lambda s, i, start: seen.setdefault("start", start) and []
    )
    last = NOW - pd.Timedelta(minutes=10)
    feed.candles("SPY", "5m", stored=pd.DataFrame({"ts": [last]}), now=NOW)
    assert pd.Timestamp(seen["start"]) == last


def test_candles_without_credentials_or_for_daily_never_ask(monkeypatch):
    monkeypatch.setattr(tasty, "candles", lambda *a, **k: pytest.fail("no candle request expected"))
    assert feed.candles("SPY", "5m", now=NOW).empty  # conftest: not ready
    monkeypatch.setattr(tasty, "ready", lambda: True)
    assert feed.candles("SPY", "1d", now=NOW).empty


# --- Chains ---------------------------------------------------------------------------------


def _nested():
    strikes = [
        NS(
            strike_price=Decimal(k),
            call_streamer_symbol=f".SPYC{k}",
            put_streamer_symbol=f".SPYP{k}",
        )
        for k in (95, 100, 105)
    ]
    return [
        NS(
            expirations=[
                NS(expiration_date=date(2026, 10, 16), settlement_type="PM", strikes=strikes)
            ]
        )
    ]


def _q(bid, ask):
    return {
        "bid": bid,
        "ask": ask,
        "last": (bid + ask) / 2,
        "prev_close": bid,
        "day_close": math.nan,
        "volume": 1.0,
        "open_interest": 1.0,
        "last_time": None,
    }


def test_chain_coverage_and_second_pass(monkeypatch):
    calls = []

    def quotes(symbols, wait=3.0, retry_missing=False):
        calls.append((list(symbols), retry_missing))
        out = {"SPY": _q(99.9, 100.1)}
        for s in symbols:
            if s.startswith(".") and s != ".SPYP95":  # one contract never quotes
                out[s] = _q(1.0, 1.1)
        return out

    monkeypatch.setattr(tasty, "nested_chain", lambda symbol: _nested())
    monkeypatch.setattr(tasty, "stream_quotes", quotes)
    df = chains.TastytradeChains().chain("SPY")
    assert len(df) == 5
    assert df.attrs["coverage"] == pytest.approx(5 / 6) and df.attrs["subscribed"] == 6
    assert calls[-1] == ([".SPYP95"], True)  # the missing contract got one more, flagged wait


def test_chain_without_a_live_spot_refuses(monkeypatch):
    monkeypatch.setattr(tasty, "nested_chain", lambda symbol: _nested())
    monkeypatch.setattr(tasty, "stream_quotes", lambda symbols, wait=3.0, retry_missing=False: {})
    with pytest.raises(chains.ChainUnavailable):
        chains.TastytradeChains().chain("SPY")


# --- Rate, dividends, metrics, horizon IV ----------------------------------------------------


def test_risk_free_rate_order(monkeypatch, cfg):
    assert feed.risk_free_rate(config=cfg) == (0.04, "default")
    _daily(cfg, "^IRX", [4.0, 4.1])
    rate, src = feed.risk_free_rate(config=cfg)
    assert rate == pytest.approx(0.041) and src == "13-week T-bill"
    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(tasty, "risk_free_rate", lambda: 4.2)  # percent, checked against ^IRX
    rate, src = feed.risk_free_rate(config=cfg)
    assert rate == pytest.approx(0.042) and src == "tastytrade"


def test_latest_metrics_is_one_row_per_symbol(cfg):
    _metrics(
        cfg,
        [{"symbol": "SPY", "ivx": 0.15}, {"symbol": "QQQ", "ivx": 0.20}],
        NOW - pd.Timedelta(hours=2),
    )
    _metrics(cfg, [{"symbol": "SPY", "ivx": 0.16}])  # a later single-symbol pull
    df = feed.latest_metrics(["SPY", "QQQ"], config=cfg).set_index("symbol")
    assert df.loc["SPY", "ivx"] == pytest.approx(0.16)
    assert df.loc["QQQ", "ivx"] == pytest.approx(0.20)  # not hidden by SPY's newer pull


def test_latest_metrics_pulls_only_missing_or_stale(monkeypatch, cfg):
    _metrics(cfg, [{"symbol": "SPY", "ivx": 0.15}], pd.Timestamp.now(tz="UTC"))
    asked = []

    def live(symbols, *, config=None, store=True):
        asked.append(symbols)
        return pd.DataFrame(
            [{"collected_at": pd.Timestamp.now(tz="UTC"), "symbol": s, "ivx": 0.3} for s in symbols]
        ), pd.DataFrame()

    monkeypatch.setattr(tasty, "ready", lambda: True)
    monkeypatch.setattr(feed, "metrics", live)
    df = feed.latest_metrics(["SPY", "NVDA"], config=cfg)
    assert asked == [["NVDA"]] and set(df["symbol"]) == {"SPY", "NVDA"}


def test_dividend_yield_units_follow_the_dividend_per_share(cfg):
    assert feed.dividend_yield("SPY", config=cfg) == 0.0
    _daily(cfg, "SPY", [560.0, 560.0])
    _metrics(cfg, [{"symbol": "SPY", "dividend_yield": 1.25, "dividend_rate_per_share": 7.0}])
    assert feed.dividend_yield("SPY", config=cfg) == pytest.approx(0.0125)


def test_horizon_iv_prefers_the_nearest_expiry_then_falls_back(cfg):
    today = NOW.tz_convert(ET).tz_localize(None).normalize()
    reference.append(
        pd.DataFrame(
            {
                "collected_at": NOW,
                "source": "tastytrade",
                "symbol": "SPY",
                "expiry": [f"{today + pd.Timedelta(days=d):%Y-%m-%d}" for d in (7, 30)],
                "iv": [0.12, 0.16],
            }
        ),
        "iv_term",
        cfg,
    )
    iv, src = feed.horizon_iv("SPY", 28, config=cfg, now=NOW)
    assert iv == pytest.approx(0.16) and src.startswith("tastytrade IV")

    # Two days later the stored term structure is too old; no metrics either: VIX for SPY.
    later = NOW + pd.Timedelta(days=2)
    _daily(cfg, "^VIX", [15.0, 16.0])
    iv, src = feed.horizon_iv("SPY", 28, config=cfg, now=later)
    assert iv == pytest.approx(0.16) and src == "VIX"

    # A name with no IV anywhere: its own realized vol, else nothing.
    assert feed.horizon_iv("XOM", 30, config=cfg, now=later) == (
        pytest.approx(math.nan, nan_ok=True),
        "",
    )
    _daily(cfg, "XOM", [100 + (i % 3) for i in range(40)])
    iv, src = feed.horizon_iv("XOM", 30, config=cfg, now=later)
    assert iv > 0 and src == "realized vol, 21D"
