"""The Yahoo collector's default universe: every daily series a page reads, intraday only where
pages read intraday bars."""

from __future__ import annotations

import dataclasses

import pandas as pd

from alphasurface.collector import yfinance_collector as yc
from alphasurface.config import load_config


def test_daily_defaults_to_the_config_universe(monkeypatch, tmp_path):
    cfg = dataclasses.replace(load_config(), data_dir=tmp_path)
    asked = []
    monkeypatch.setattr(yc, "fetch_ohlcv", lambda s, i, p: asked.append(s) or pd.DataFrame())
    yc.collect(cfg, interval="1d", period="5d")
    assert asked == cfg.universe()
    assert {"SPY", "^VIX", "TLT"} <= set(asked)


def test_hourly_defaults_to_index_etfs_and_single_names(monkeypatch, tmp_path):
    cfg = dataclasses.replace(load_config(), data_dir=tmp_path)
    asked = []
    monkeypatch.setattr(yc, "fetch_ohlcv", lambda s, i, p: asked.append(s) or pd.DataFrame())
    yc.collect(cfg, interval="1h", period="5d")
    assert asked == list(dict.fromkeys(cfg.equities() + cfg.single_names()))
    assert not any(s.startswith("^") for s in asked)


def test_an_explicit_list_wins(monkeypatch, tmp_path):
    cfg = dataclasses.replace(load_config(), data_dir=tmp_path)
    asked = []
    monkeypatch.setattr(yc, "fetch_ohlcv", lambda s, i, p: asked.append(s) or pd.DataFrame())
    yc.collect(cfg, symbols=["XOM"], interval="1d", period="5d")
    assert asked == ["XOM"]
