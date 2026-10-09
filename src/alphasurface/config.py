"""App config and paths. Settings come from config/config.toml if present, else local defaults.
Every secret comes from the environment, loaded from .env at the repo root (real environment
variables win over it). Nothing secret is ever read from config.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Tastytrade:
    client_secret: str = ""
    refresh_token: str = ""
    sandbox: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.client_secret and self.refresh_token)

    def __repr__(self) -> str:  # never print the secrets, even in a traceback
        return f"Tastytrade(ready={self.ready}, sandbox={self.sandbox})"


@dataclass(frozen=True)
class ApiKeys:
    """Optional keys for secondary sources. Empty means the source is skipped."""

    finnhub: str = ""
    fred: str = ""

    def __repr__(self) -> str:
        return f"ApiKeys(finnhub={bool(self.finnhub)}, fred={bool(self.fred)})"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    symbols: dict = field(default_factory=dict)
    db_file: str = "market.duckdb"
    tastytrade: Tastytrade = field(default_factory=Tastytrade)
    keys: ApiKeys = field(default_factory=ApiKeys)

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_file

    def _list(self, section: str, key: str) -> list[str]:
        return [
            str(s).strip().upper()
            for s in self.symbols.get(section, {}).get(key, [])
            if str(s).strip()
        ]

    def equities(self) -> list[str]:
        """Index ETFs, the core of every page."""
        return self._list("indices", "equities") or ["SPY"]

    def futures(self) -> list[str]:
        """Futures roots in tastytrade form, /ES."""
        return self._list("indices", "futures")

    def single_names(self) -> list[str]:
        return self._list("single_names", "equities")

    def vol_complex(self) -> list[str]:
        """The VIX family, Yahoo spelling (^VIX)."""
        return self._list("vol_complex", "vix")

    def cross_asset_vol(self) -> list[str]:
        return self._list("vol_complex", "cross_asset")

    def macro(self) -> list[str]:
        return self._list("macro_etfs", "etfs")

    def rates(self) -> list[str]:
        return self._list("rates", "yields")

    def scan_universe(self) -> list[str]:
        """What the screener scans by default: index ETFs and single names."""
        return list(dict.fromkeys(self.equities() + self.single_names()))

    def metrics_universe(self) -> list[str]:
        """tastytrade market metrics are pulled for these (tastytrade spelling)."""
        return self.scan_universe()

    def universe(self) -> list[str]:
        """Every symbol the pages read daily history for, stored spelling (futures as ES=F).
        The scheduled daily top-up covers exactly this list."""
        from alphasurface.symbols import to_store

        groups = (
            self.equities(),
            self.single_names(),
            self.vol_complex(),
            self.cross_asset_vol(),
            self.macro(),
            self.rates(),
            self.futures(),
        )
        return list(dict.fromkeys(to_store(s) for g in groups for s in g))


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _tastytrade() -> Tastytrade:
    return Tastytrade(
        client_secret=_env("TASTYTRADE_CLIENT_SECRET"),
        refresh_token=_env("TASTYTRADE_REFRESH_TOKEN"),
        sandbox=_env("TASTYTRADE_SANDBOX").lower() in ("1", "true", "yes"),
    )


def load_config() -> Config:
    load_dotenv(REPO_ROOT / ".env", override=False)
    cfg = _read_toml(CONFIG_DIR / "config.toml")
    storage = cfg.get("storage", {})
    raw_dir = os.environ.get("ALPHASURFACE_DATA_DIR") or storage.get(
        "data_dir"
    )  # env wins: CI, containers
    data_dir = Path(raw_dir).expanduser() if raw_dir else REPO_ROOT / "data"
    return Config(
        data_dir=data_dir,
        symbols=_read_toml(CONFIG_DIR / "symbols.toml"),
        db_file=storage.get("db_file", "market.duckdb"),
        tastytrade=_tastytrade(),
        keys=ApiKeys(finnhub=_env("FINNHUB_API_KEY"), fred=_env("FRED_API_KEY")),
    )
