import gzip
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from extracto.adapters.storage.backup import backup_sqlite, prune_backups
from tests.conftest import sqlite_only

pytestmark = sqlite_only


def test_backup_is_a_restorable_copy(db_url: str, tmp_path: Path) -> None:
    out = backup_sqlite(db_url, tmp_path / "backups", now=datetime(2026, 10, 20, tzinfo=UTC))

    assert out.name == "monitor-20261020T000000Z.db.gz"
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(out.read_bytes()))
    with closing(sqlite3.connect(restored)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sites", "pages", "snapshots"} <= tables
    assert not list((tmp_path / "backups").glob("*.db"))  # temp file cleaned up


def test_backup_rejects_non_sqlite(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        backup_sqlite("postgresql://u@h/db", tmp_path)


def test_prune_keeps_newest(db_url: str, tmp_path: Path) -> None:
    dest = tmp_path / "backups"
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    paths = [backup_sqlite(db_url, dest, now=t0 + timedelta(days=i)) for i in range(5)]

    deleted = prune_backups(dest, keep=2)

    assert deleted == paths[:3]
    assert sorted(dest.glob("*.gz")) == paths[3:]
