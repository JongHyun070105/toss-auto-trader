from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://openapi.tossinvest.com"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    account_seq: Optional[str] = None
    db_path: str = "data/toss_lab.sqlite3"
    dry_run: bool = True
    live_trading: bool = False

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "Settings":
        load_dotenv(dotenv_path)
        return cls(
            base_url=os.getenv("TOSS_BASE_URL", "https://openapi.tossinvest.com"),
            client_id=os.getenv("TOSS_CLIENT_ID") or None,
            client_secret=os.getenv("TOSS_CLIENT_SECRET") or os.getenv("TOSS_API_KEY") or None,
            account_seq=os.getenv("TOSS_ACCOUNT_SEQ") or None,
            db_path=os.getenv("TOSS_DB_PATH", "data/toss_lab.sqlite3"),
            dry_run=env_bool("TOSS_DRY_RUN", True),
            live_trading=env_bool("TOSS_LIVE_TRADING", False),
        )

    def require_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "TOSS_CLIENT_ID and TOSS_CLIENT_SECRET are required. "
                "Put them in .env, never in source code."
            )
