"""Scanner rules on hand-built frames (no network), the write-through store, alert de-dup, and
the options-versus-underlying arithmetic."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from alphasurface.collector import alerts, feed
from alphasurface.collector import chains as chains_mod
from alphasurface.collector import scan as cscan
from alphasurface.config import Config
from alphasurface.derive import black_scholes as bs
from alphasurface.derive import scan as sc
from alphasurface.derive import vehicles as vh
from alphasurface.storage import reader, schema, writer

NOW = pd.Timestamp("2026-10-07 15:00", tz="UTC")  # 11:00 in New York, a Wednesday


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path)


def _raw(rows: list[dict], spot=100.0, prev=None, ts=NOW) -> pd.DataFrame:
    base = {
        "ts": ts,
        "symbol": "TST",
        "volume": 100.0,
        "open_interest": 1000.0,
        "underlying": spot,
        "underlying_prev": prev if prev is not None else spot,
    }
    return pd.DataFrame([base | r for r in rows])


def _priced(K, kind, days, spot=100.0, vol=0.2, r=0.04, half=0.05, **extra):
    p = bs.price(spot, K, days / 365, r, vol, 0.0, kind)
    expiry = (
        NOW.tz_convert(sc.NY).date() + timedelta(days=days)
    ).isoformat()  # calendar days, DST-proof
    return {
        "expiry": expiry,
        "strike": K,
        "kind": kind,
        "bid": p - half,
        "ask": p + half,
        "last": p,
    } | extra


# --- Normalizing and Greeks -----------------------------------------------------------------


def test_minutes_to_close():
    assert sc.minutes_to_close(NOW) == 300
    assert sc.minutes_to_close(pd.Timestamp("2026-10-07 21:30", tz="UTC")) == 0
    assert sc.minutes_to_close(pd.Timestamp("2026-10-07 12:00", tz="UTC")) == 390
    assert sc.minutes_to_close(pd.Timestamp("2026-10-10 15:00", tz="UTC")) == 0  # Saturday


def test_normalize_marks_and_falls_back_to_last():
    raw = _raw(
        [
            _priced(100, "call", 30),
            {
                "expiry": "2026-10-20",
                "strike": 105,
                "kind": "put",
                "bid": 0.0,
                "ask": 0.0,
                "last": 6.1,
            },
            {
                "expiry": "2026-09-01",
                "strike": 100,
                "kind": "call",
                "bid": 1,
                "ask": 2,
                "last": 1.5,
            },
        ]
    )
    df = sc.normalize(raw, NOW)
    assert len(df) == 2  # the expired row is gone
    assert df.loc[0, "quote"] == "mid" and df.loc[0, "spread"] == pytest.approx(0.10)
    assert (
        df.loc[1, "quote"] == "last" and df.loc[1, "mark"] == 6.1 and np.isnan(df.loc[1, "spread"])
    )
    assert df.loc[1, "distance"] == pytest.approx(0.05) and df.loc[0, "dte"] == 30


def test_greeks_round_trip_and_session_clock():
    df = sc.add_greeks(
        sc.normalize(_raw([_priced(95, "put", 30), _priced(105, "call", 60)]), NOW),
        0.04,
        0.0,
        minutes_left=300,
    )
    assert df["iv"].tolist() == pytest.approx([0.2, 0.2], abs=1e-4)
    assert df.loc[0, "delta"] == pytest.approx(
        bs.greeks(100, 95, 30 / 365, 0.04, 0.2, 0, "put").delta, abs=1e-4
    )
    same_day = _raw(
        [
            {
                "expiry": NOW.tz_convert(sc.NY).strftime("%Y-%m-%d"),
                "strike": 100,
                "kind": "call",
                "bid": 0.40,
                "ask": 0.42,
                "last": 0.41,
            }
        ]
    )
    live = sc.add_greeks(sc.normalize(same_day, NOW), 0.04, 0.0, minutes_left=300)
    closed = sc.add_greeks(sc.normalize(same_day, NOW), 0.04, 0.0, minutes_left=0)
    assert live.loc[0, "iv"] > 0 and np.isnan(closed.loc[0, "iv"])


def test_filters():
    df = sc.add_greeks(
        sc.normalize(_raw([_priced(k, "call", d) for k in (90, 100, 125) for d in (10, 40)]), NOW),
        0.04,
        0.0,
        300,
    )
    f = sc.Filters(dte_min=20, dte_max=45, dist_max=0.15, side="call", delta_min=0.3, delta_max=0.6)
    out = sc.postfilter(sc.prefilter(df, f), f)
    assert out["strike"].tolist() == [100] and out["dte"].tolist() == [40]


def test_reference_prefers_stored_pull_then_prior_close():
    df = sc.normalize(
        _raw(
            [
                _priced(100, "call", 30, change=0.5, last_trade=NOW),
                _priced(105, "call", 30, change=0.3, last_trade=NOW - pd.Timedelta(days=2)),
            ],
            spot=102,
            prev=100,
        ),
        NOW,
    )
    prev = pd.DataFrame(
        [
            {
                "collected_at": NOW - pd.Timedelta(hours=2),
                "source": "x",
                "symbol": "TST",
                "expiry": df.loc[0, "expiry"],
                "strike": 100.0,
                "kind": "call",
                "bid": 2.0,
                "ask": 2.2,
                "last": 2.1,
                "underlying": 101.0,
            }
        ]
    )
    out = sc.attach_reference(df, prev, NOW)
    assert out.loc[0, "ref_source"] == "last stored pull" and out.loc[
        0, "ref_mark"
    ] == pytest.approx(2.1)
    assert out.loc[0, "elapsed_days"] == pytest.approx(2 / 24)
    # No stored quote and no trade today: the last print is the prior close.
    assert out.loc[1, "ref_source"] == "prior close" and out.loc[1, "ref_mark"] == pytest.approx(
        df.loc[1, "last"]
    )
    no_prev = sc.attach_reference(df, None, NOW)
    assert no_prev.loc[0, "ref_mark"] == pytest.approx(df.loc[0, "last"] - 0.5)  # traded today


# --- Rules ----------------------------------------------------------------------------------


def _scannable(rows, spot, prev, prev_rows=None):
    df = sc.add_greeks(sc.normalize(_raw(rows, spot=spot, prev=prev), NOW), 0.04, 0.0, 300)
    df["minutes_left"] = 300.0  # as sc.prepare sets it
    return sc.attach_reference(df, prev_rows, NOW)


def test_stale_after_move_flags_only_real_lags():
    spot0, spot1 = 100.0, 102.0
    before = {k: bs.price(spot0, k, 30 / 365, 0.04, 0.2, 0, "call") for k in (100, 104)}
    rows = [
        # The 100 call still sits at yesterday's price after a 2% rally: stale.
        _priced(100, "call", 30, spot=spot1)
        | {
            "bid": before[100] - 0.05,
            "ask": before[100] + 0.05,
            "last": before[100],
            "change": 0.0,
            "last_trade": NOW - pd.Timedelta(days=1),
        },
        # The 104 call moved with the stock: not stale.
        _priced(104, "call", 30, spot=spot1)
        | {"change": 0.0, "last_trade": NOW - pd.Timedelta(days=1)},
    ]
    rows[1]["last"] = before[104]
    df = _scannable(rows, spot1, spot0)
    hits = sc.stale_after_move(df, None, {}, move_pct=1.0, lag_ratio=0.5, min_spreads=2.0)
    assert hits["strike"].tolist() == [100]
    assert "lag" in hits.loc[0, "reason"].lower() and hits.loc[0, "score"] > 2
    wide = _scannable(
        [rows[0] | {"bid": before[100] - 1.5, "ask": before[100] + 1.5}], spot1, spot0
    )
    assert sc.stale_after_move(wide, None, {}).empty  # the spread swallows the lag


def _ctx(**cols):
    base = {
        "spot": 100.0,
        "prev_close": 100.0,
        "change": 0.0,
        "rv5": 0.2,
        "rv10": 0.2,
        "rv21": 0.2,
        "rv63": 0.2,
        "atm_iv": 0.2,
        "atm_iv_prev": np.nan,
        "atm_expiry": "2026-11-06",
        "atm_strike": 100.0,
        "atm_dte": 30,
    }
    return pd.DataFrame([base | cols], index=pd.Index(["TST"], name="symbol"))


def test_rv_up_iv_asleep():
    assert len(sc.rv_up_iv_asleep(None, _ctx(rv5=0.40, rv21=0.20, atm_iv=0.30), {})) == 1
    assert sc.rv_up_iv_asleep(None, _ctx(rv5=0.40, rv21=0.20, atm_iv=0.45), {}).empty
    fell = sc.rv_up_iv_asleep(None, _ctx(rv5=0.40, rv21=0.20, atm_iv=0.45, atm_iv_prev=0.50), {})
    assert "down from 50.0%" in fell.loc[0, "reason"]
    assert sc.rv_up_iv_asleep(
        None, _ctx(rv5=0.25, rv21=0.20, atm_iv=0.10), {}
    ).empty  # ratio too small


def test_rich_and_cheap():
    df = _scannable(
        [_priced(110, "call", 30, vol=0.30), _priced(90, "put", 30, vol=0.12)], 100, 100
    )
    rich = sc.rich_premium(df, _ctx(rv21=0.20), {}, gap_min=5)
    cheap = sc.cheap_convexity(df, _ctx(rv21=0.20), {}, gap_max=-2)
    assert rich["strike"].tolist() == [110] and rich.loc[0, "score"] == pytest.approx(10, abs=0.1)
    assert cheap["strike"].tolist() == [90] and cheap.loc[0, "score"] == pytest.approx(8, abs=0.1)


def test_unusual_activity():
    df = _scannable(
        [
            _priced(100, "call", 30) | {"volume": 5000, "open_interest": 1000},
            _priced(105, "call", 30) | {"volume": 900, "open_interest": 1000},
        ],
        100,
        100,
    )
    hits = sc.unusual_activity(df, None, {}, ratio_min=2, notional_min=100_000, volume_min=500)
    assert hits["strike"].tolist() == [100] and hits.loc[0, "score"] == 5


def test_price_spike():
    hits = sc.price_spike(None, _ctx(change=0.03, rv21=0.16), {}, z_min=2)
    daily = 0.16 / math.sqrt(252)
    assert hits.loc[0, "score"] == pytest.approx(math.log(1.03) / daily)
    assert sc.price_spike(None, _ctx(change=0.005, rv21=0.16), {}).empty


def _bars(rows):
    ts = pd.date_range("2026-09-01 04:00", periods=len(rows), freq="B", tz="UTC")
    return pd.DataFrame(
        [
            {"ts": t, "open": o, "high": h, "low": low, "close": c}
            for t, (o, h, low, c) in zip(ts, rows, strict=False)
        ]
    )


def test_gap_events_and_open_gaps():
    bars = _bars(
        [
            (100, 101, 99, 100),
            (102, 103, 101.5, 102.5),  # gap up 2%, low stays above 100
            (102, 102.5, 99.8, 100.2),  # fills the next day
            (102.5, 104, 102.2, 103.5),  # gap up 2.3% from 100.2, still open
            (103.6, 104.5, 103, 104),
        ]
    )
    ev = sc.gap_events(bars)
    first = ev.iloc[0]
    assert (
        first["direction"] == "up"
        and first["size"] == pytest.approx(0.02)
        and first["sessions_to_fill"] == 1
    )
    live = sc.open_gaps(None, _ctx(spot=104.0), {"TST": bars}, gap_min=0.5, lookback=10, horizon=1)
    assert len(live) == 1 and "has not filled" in live.loc[0, "reason"]
    rate, n = sc.gap_fill_rate(ev, "up", 0.02, horizon=1)
    assert n >= 1 and 0 <= rate <= 1


def test_zero_dte_straddle_against_realized():
    today = NOW.tz_convert(sc.NY).strftime("%Y-%m-%d")
    rows = [
        {"expiry": today, "strike": 100, "kind": k, "bid": 0.48, "ask": 0.52, "last": 0.5}
        for k in ("call", "put")
    ]
    df = _scannable(rows, 100, 100)
    hits = sc.zero_dte(df, _ctx(rv21=0.16), {}, window=21)
    sd = 100 * 0.16 * math.sqrt(300 / 390 / 252)
    assert hits.loc[0, "mark"] == pytest.approx(1.0)
    assert hits.loc[0, "score"] == pytest.approx(1.0 / (sc.ABS_MOVE * sd))


def test_prepare_end_to_end_on_synthetic():
    chain = chains_mod.SyntheticChains().chain(
        "SPY", chains_mod.SyntheticChains().expirations("SPY")[:3]
    )
    frame, ctx = sc.prepare(
        chain, pd.Timestamp.now(tz="UTC"), 0.04, 0.012, sc.PRESETS["rich"].filters
    )
    assert "SPY" in ctx.index and ctx.loc["SPY", "atm_iv"] > 0
    assert frame["delta"].abs().between(0.10, 0.30).all()


def test_every_preset_runs_on_an_empty_scan():
    chain = chains_mod.SyntheticChains().chain(
        "SPY", chains_mod.SyntheticChains().expirations("SPY")[:2]
    )
    for preset in sc.PRESETS.values():
        frame, ctx = sc.prepare(chain, pd.Timestamp.now(tz="UTC"), 0.04, 0.0, preset.filters)
        assert list(sc.run(preset, frame, ctx, {}).columns) == sc.HIT_COLUMNS


# --- The write-through store ----------------------------------------------------------------


def _pull(ts, bid=1.0):
    return pd.DataFrame(
        [
            {
                "ts": ts,
                "symbol": "TST",
                "expiry": "2026-11-20",
                "strike": 100.0,
                "kind": k,
                "bid": bid,
                "ask": bid + 0.1,
                "last": bid,
                "volume": 1.0,
                "open_interest": 2.0,
                "underlying": 100.0,
            }
            for k in ("call", "put")
        ]
    )


def test_append_only_store_dedups_at_read_time(config):
    t1, t2 = NOW - pd.Timedelta(hours=1), NOW
    writer.append_chain(_pull(t1, 1.0), "yfinance", config)
    writer.append_chain(_pull(t1, 1.0), "yfinance", config)  # a retried write: same rows again
    writer.append_chain(_pull(t2, 2.0), "yfinance", config)
    files = list((config.parquet_dir / "option_chain").rglob("*.parquet"))
    assert len(files) == 3  # one new file per pull, nothing rewritten
    with schema.connect(config, persistent=False) as conn:
        assert conn.execute("SELECT count(*) FROM option_chain").fetchone()[0] == 4
        before = reader.previous_chain(conn, ["TST"], NOW - pd.Timedelta(minutes=1))
        latest = reader.previous_chain(conn, ["TST"], NOW + pd.Timedelta(minutes=1))
        assert (
            conn.execute("SELECT count(DISTINCT collected_at) FROM option_chain").fetchone()[0] == 2
        )
    assert before["bid"].tolist() == [1.0, 1.0] and latest["bid"].tolist() == [2.0, 2.0]


def test_empty_store_has_a_typed_view(config):
    with schema.connect(config, persistent=False) as conn:
        assert reader.previous_chain(conn, ["TST"], NOW).empty


class _Fake:
    name = "fake"

    def expirations(self, symbol):
        return ["2026-11-20"]

    def chain(self, symbol, expiries=None):
        return _pull(NOW)


def test_gateway_stores_real_pulls_not_synthetic(config, monkeypatch):
    monkeypatch.setitem(chains_mod.PROVIDERS, "fake", _Fake)
    out = feed.chain("fake", "TST", config=config)
    assert len(out) == 2  # handed back to the caller
    feed.chain(
        "synthetic", "SPY", chains_mod.SyntheticChains().expirations("SPY")[:1], config=config
    )
    files = list((config.parquet_dir / "option_chain").rglob("*.parquet"))
    assert len(files) == 1 and "TST" in pd.read_parquet(files[0])["symbol"].tolist()


def test_a_failed_write_never_breaks_the_caller(config, monkeypatch):
    monkeypatch.setitem(chains_mod.PROVIDERS, "fake", _Fake)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(writer, "append_chain", boom)
    assert len(feed.chain("fake", "TST", config=config)) == 2


def test_run_scan_on_synthetic_needs_no_network(config):
    res = cscan.run_scan(["SPY"], "rich", source="synthetic", config=config)
    assert res.contracts > 0 and not res.errors
    assert not (config.parquet_dir / "option_chain").exists()  # synthetic is never stored


def test_pick_expiries():
    exp = ["2026-10-07", "2026-10-09", "2026-10-30", "2026-11-20", "2027-01-15"]
    assert cscan.pick_expiries(exp, sc.Filters(dte_min=20, dte_max=45), NOW, 4) == [
        "2026-10-30",
        "2026-11-20",
    ]
    assert cscan.pick_expiries(exp, sc.Filters(zero_dte=True), NOW, 4) == ["2026-10-07"]
    assert cscan.pick_expiries(exp, sc.Filters(dte_min=0, dte_max=400), NOW, 2) == exp[:2]


# --- Alerts ---------------------------------------------------------------------------------


def test_alerts_dedup_and_cooldown(config):
    t0 = datetime(2026, 10, 7, 15, tzinfo=UTC)
    new, due = alerts.update(config, "rich", ["a", "b"], 24, now=t0)
    assert new == {"a", "b"} and due == ["a", "b"]
    new, due = alerts.update(config, "rich", ["a", "b", "c"], 24, now=t0 + timedelta(hours=1))
    assert new == {"c"} and due == ["c"]  # a and b already notified
    new, due = alerts.update(config, "rich", ["a"], 24, now=t0 + timedelta(hours=30))
    assert new == set() and due == ["a"]  # past the cooldown it may notify again


def test_send_is_off_unless_enabled():
    assert alerts.send("t", "m", {"enabled": False, "macos": True, "ntfy_url": "https://x"}) == []


# --- Options or the underlying --------------------------------------------------------------


def test_vehicle_comparison_by_hand():
    S, move, days, exp, iv, r = 100.0, 0.05, 10, 30, 0.2, 0.04
    table, curves = vh.compare(S, move, days, exp, iv, r, 0.0, margin=0.1, n_paths=2000)
    shares = table.set_index("Vehicle").loc["Shares, 100"]
    assert shares["P&L at target"] == pytest.approx(500) and shares["P&L if flat"] == 0
    assert shares["Capital"] == 10_000 and shares["Breakeven"] == pytest.approx(S, abs=0.6)
    delta_one = table.set_index("Vehicle").loc["Delta one, 10% margin"]
    assert delta_one["Capital"] == 1_000 and delta_one["Return at target"] == pytest.approx(0.5)

    atm = table[table["Vehicle"].str.startswith("ATM call")].iloc[0]
    premium = bs.price(S, 100, exp / 252, r, iv, 0, "call") * 100
    at_target = bs.price(S * 1.05, 100, (exp - days) / 252, r, iv, 0, "call") * 100
    assert atm["Capital"] == pytest.approx(premium) and atm["Max loss"] == pytest.approx(premium)
    assert atm["P&L at target"] == pytest.approx(at_target - premium)
    assert atm["P&L if flat"] < 0  # time decay
    assert list(curves.columns) == table["Vehicle"].tolist()
    with pytest.raises(ValueError):
        vh.compare(S, move, 40, 30, iv, r, 0.0)


def test_bearish_vehicles_use_puts_and_short_shares():
    table, _ = vh.compare(100.0, -0.05, 10, 30, 0.2, 0.04, 0.0, n_paths=500)
    assert table["Vehicle"].iloc[0] == "Short shares, 100"
    assert table["Vehicle"].str.contains("put").sum() >= 2
    assert table.iloc[0]["Max loss"] == math.inf
