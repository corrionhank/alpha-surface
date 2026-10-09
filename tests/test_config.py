"""Credentials load from the environment and never show up in a repr."""

from __future__ import annotations

from alphasurface import config


def test_env_wins_and_repr_hides(monkeypatch):
    monkeypatch.setenv("TASTYTRADE_CLIENT_SECRET", "s3cret-value")
    monkeypatch.setenv("TASTYTRADE_REFRESH_TOKEN", "r3fresh-value")
    monkeypatch.setenv("TASTYTRADE_SANDBOX", "true")
    tt = config.load_config().tastytrade
    assert tt.ready and tt.sandbox and tt.client_secret == "s3cret-value"
    assert "s3cret" not in repr(tt) and "r3fresh" not in repr(config.load_config())


def test_not_ready_without_both(monkeypatch):
    monkeypatch.setenv("TASTYTRADE_CLIENT_SECRET", "x")
    monkeypatch.setenv("TASTYTRADE_REFRESH_TOKEN", "")
    assert not config._tastytrade().ready


def test_api_keys_from_env_and_hidden(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "fh-key-value")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    keys = config.load_config().keys
    assert keys.finnhub == "fh-key-value" and keys.fred == ""
    assert "fh-key-value" not in repr(keys)
