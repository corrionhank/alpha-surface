"""Watchlists, one per signed-in user, saved to data/watchlists.json.

Small and local on purpose: a JSON map of user to symbol list, written whole through a temp file
and a rename under an exclusive lock, so two sessions saving at once never leave half a file.
"""

from __future__ import annotations

import fcntl
import json
from pathlib import Path

from alphasurface.config import Config

DEFAULT = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "NVDA", "MSFT", "AMZN", "META", "TSLA", "GLD", "TLT"]
MAX = 60


def _path(config: Config) -> Path:
    return config.data_dir / "watchlists.json"


def _read(config: Config) -> dict[str, list[str]]:
    path = _path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def load(user: str, config: Config) -> list[str]:
    return list(_read(config).get(user) or DEFAULT)


def save(user: str, symbols: list[str], config: Config) -> list[str]:
    """Store the list (deduplicated, upper-case, at most MAX) and return what was stored."""
    clean = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))[:MAX]
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            lists = _read(config)
            lists[user] = clean
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(lists, indent=2))
            tmp.replace(path)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return clean
