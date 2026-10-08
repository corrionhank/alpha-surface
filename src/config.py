"""App config and paths. Reads config/config.toml if present, else uses local defaults.
Secrets come from .env at the repo root (or the real environment, which wins)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Tastytrade:
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    sandbox: bool = False

    @property
    def ready(self) -> bool:
        """The SDK needs the client secret and a refresh token; the client ID is kept for reference."""
        return bool(self.client_secret and self.refresh_token)

    def __repr__(self) -> str:  # never print the secrets, even in a traceback
        return f"Tastytrade(ready={self.ready}, sandbox={self.sandbox})"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    symbols: dict = field(default_factory=dict)
    db_file: str = "market.duckdb"
    tastytrade: Tastytrade = field(default_factory=Tastytrade)

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_file

    def equities(self) -> list[str]:
        eq = self.symbols.get("indices", {}).get("equities", [])
        return list(eq) if eq else ["SPY"]


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _tastytrade(toml: dict) -> Tastytrade:
    """.env first (real environment variables win over it), then config.toml as a fallback."""
    load_dotenv(REPO_ROOT / ".env", override=False)

    def pick(env: str, key: str) -> str:
        return (os.environ.get(env) or str(toml.get(key, ""))).strip()

    return Tastytrade(
        client_id=pick("TASTYTRADE_CLIENT_ID", "client_id"),
        client_secret=pick("TASTYTRADE_CLIENT_SECRET", "provider_secret"),
        refresh_token=pick("TASTYTRADE_REFRESH_TOKEN", "refresh_token"),
        sandbox=pick("TASTYTRADE_SANDBOX", "is_test").lower() in ("1", "true", "yes"),
    )


def load_config() -> Config:
    cfg = _read_toml(CONFIG_DIR / "config.toml")
    storage = cfg.get("storage", {})
    raw_dir = os.environ.get("DIP_DATA_DIR") or storage.get("data_dir")  # env wins: CI, containers
    data_dir = Path(raw_dir).expanduser() if raw_dir else REPO_ROOT / "data"
    return Config(
        data_dir=data_dir,
        symbols=_read_toml(CONFIG_DIR / "symbols.toml"),
        db_file=storage.get("db_file", "market.duckdb"),
        tastytrade=_tastytrade(cfg.get("tastytrade", {})),
    )
