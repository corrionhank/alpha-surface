"""App config and paths. Reads config/config.toml if present, else uses local defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    symbols: dict = field(default_factory=dict)
    db_file: str = "market.duckdb"

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


def load_config() -> Config:
    cfg = _read_toml(CONFIG_DIR / "config.toml")
    storage = cfg.get("storage", {})
    raw_dir = storage.get("data_dir")
    data_dir = Path(raw_dir).expanduser() if raw_dir else REPO_ROOT / "data"
    return Config(
        data_dir=data_dir,
        symbols=_read_toml(CONFIG_DIR / "symbols.toml"),
        db_file=storage.get("db_file", "market.duckdb"),
    )
