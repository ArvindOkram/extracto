"""Environment-based settings. Secrets and paths come from env vars or `.env`, never config."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_POSTGRES_PREFIXES = ("postgres://", "postgresql://")


def normalize_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain Postgres URLs (as given by Neon, Supabase, Render)."""
    url = url.strip()
    for prefix in _POSTGRES_PREFIXES:
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")
    sites_config: Path = Path("config/sites.yaml")
    # Overrides the default SQLite file, e.g. a Neon/Supabase Postgres URL in the cloud.
    database_url: str | None = None
    # Gzip raw HTML copies on disk. Default: on for SQLite, off for Postgres (cloud disks are
    # usually ephemeral and free database tiers are small).
    keep_raw_html: bool | None = None
    log_level: str = "INFO"
    # Secret: anyone with this URL can post to the channel.
    discord_webhook_url: SecretStr | None = None
    # Required in the X-API-Key header when set (and to serve on a non-local address).
    api_key: SecretStr | None = Field(default=None, validation_alias="EXTRACTO_API_KEY")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return normalize_database_url(self.database_url)
        return f"sqlite:///{(self.data_dir / 'monitor.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.resolved_database_url.startswith("sqlite")

    @property
    def raw_html_enabled(self) -> bool:
        return self.is_sqlite if self.keep_raw_html is None else self.keep_raw_html

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"
