"""Consistent, compressed SQLite backups (safe while the crawler is writing)."""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from extracto.adapters.storage.orm import utcnow

BACKUP_GLOB = "monitor-*.db.gz"


def sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        raise ValueError(f"backups support file-based SQLite only, got {url.get_backend_name()}")
    return Path(url.database)


def backup_sqlite(database_url: str, dest_dir: Path, *, now: datetime | None = None) -> Path:
    """Copy the database with SQLite's online backup API, gzip it, and return the path."""
    src_path = sqlite_path(database_url)
    if not src_path.exists():
        raise FileNotFoundError(src_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or utcnow()).strftime("%Y%m%dT%H%M%SZ")
    tmp = dest_dir / f"monitor-{stamp}.db"
    out = dest_dir / f"monitor-{stamp}.db.gz"

    with closing(sqlite3.connect(src_path)) as src, closing(sqlite3.connect(tmp)) as dst:
        src.backup(dst)
    with tmp.open("rb") as f_in, gzip.open(out, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.unlink()
    return out


def prune_backups(dest_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups. Returns the deleted paths."""
    backups = sorted(dest_dir.glob(BACKUP_GLOB))  # timestamped names sort chronologically
    stale = backups[:-keep] if keep > 0 else backups
    for path in stale:
        path.unlink()
    return stale
