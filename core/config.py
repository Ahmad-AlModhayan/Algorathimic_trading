"""Environment-based configuration. Loaded from the process env and an optional `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: PostgresDsn = Field(
        default="postgresql://postgres:postgres@localhost:5432/tradelab",
        description="Postgres DSN (Supabase in production).",
    )
    data_dir: Path = Field(
        default=Path("./data"), description="Root of the Parquet candle archive."
    )

    # Read-only market data. V1 never holds trade-permission keys.
    binance_api_key: str | None = None
    binance_api_secret: str | None = None

    @property
    def candles_dir(self) -> Path:
        return self.data_dir / "candles"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
