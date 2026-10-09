"""Scan alerts: which hits are new, and telling you about them.

State is one small JSON file, data/alerts/state.json, kept under a file lock:
  runs      per preset, the hit ids of its last run, so a page can show what is new since then
  notified  per hit id, when it last raised a notification, so a standing hit does not notify
            on every run (it can again once cooldown_hours have passed)

Notification is opt-in through [notify] in config/config.toml. When enabled the default channel
is a local macOS notification. An ntfy.sh topic is used only if you set ntfy_url. Nothing leaves
the machine unless configured to.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tomllib
from datetime import UTC, datetime, timedelta

from alphasurface.config import CONFIG_DIR, Config
from alphasurface.storage.writer import locked

log = logging.getLogger(__name__)

DEFAULTS = {"enabled": False, "macos": True, "ntfy_url": "", "cooldown_hours": 24.0}


def settings() -> dict:
    path = CONFIG_DIR / "config.toml"
    cfg = tomllib.loads(path.read_text()) if path.exists() else {}
    return DEFAULTS | cfg.get("notify", {})


def _path(config: Config):
    return config.data_dir / "alerts" / "state.json"


def update(
    config: Config, preset: str, ids: list[str], cooldown_hours: float, now: datetime | None = None
) -> tuple[set[str], list[str]]:
    """Record this run's hits. Returns (new since this preset's last run, due to notify now).
    A hit is due if it has never notified or last did more than cooldown_hours ago."""
    now = now or datetime.now(UTC)
    path = _path(config)
    with locked(path.with_suffix(".lock")):
        state = json.loads(path.read_text()) if path.exists() else {}
        runs, notified = state.setdefault("runs", {}), state.setdefault("notified", {})
        before = set(runs.get(preset, {}).get("ids", []))
        new = set(ids) - before
        cutoff = now - timedelta(hours=cooldown_hours)
        due = [i for i in ids if i not in notified or datetime.fromisoformat(notified[i]) < cutoff]
        runs[preset] = {"at": now.isoformat(), "ids": list(ids)}
        for i in due:
            notified[i] = now.isoformat()
        # Forget notifications old enough that they would be due again anyway.
        state["notified"] = {
            k: v for k, v in notified.items() if datetime.fromisoformat(v) >= cutoff
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(path)
    return new, due


def send(title: str, message: str, opts: dict | None = None) -> list[str]:
    """Deliver one notification on every enabled channel. Returns the channels used. Failures
    are logged, never raised: an alert must not take the scan down with it."""
    opts = opts or settings()
    if not opts.get("enabled"):
        return []
    used = []
    if opts.get("macos", True) and sys.platform == "darwin":
        script = [
            "-e",
            "on run argv",
            "-e",
            "display notification (item 2 of argv) with title (item 1 of argv)",
            "-e",
            "end run",
        ]
        try:  # title and message travel as arguments, never spliced into the script
            subprocess.run(
                ["osascript", *script, title, message[:240]],
                check=True,
                timeout=10,
                capture_output=True,
            )
            used.append("macos")
        except Exception:
            log.warning("macOS notification failed", exc_info=True)
    url = opts.get("ntfy_url", "")
    if url:
        try:
            import httpx

            httpx.post(url, content=message.encode(), headers={"Title": title}, timeout=10)
            used.append("ntfy")
        except Exception:
            log.warning("ntfy notification failed", exc_info=True)
    return used
