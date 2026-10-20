from datetime import UTC, datetime, timedelta
from pathlib import Path

from extracto.adapters.storage.raw_store import RawStore

HASH = "ab" + "c" * 62


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    rel = store.save(HASH, datetime(2026, 10, 20, 6, 0, tzinfo=UTC), b"<html>hi</html>")

    assert not Path(rel).is_absolute()
    assert rel.endswith(".html.gz")
    assert store.load(rel) == b"<html>hi</html>"


def test_keeps_only_newest_per_page(tmp_path: Path) -> None:
    store = RawStore(tmp_path, keep=3)
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    saved = [store.save(HASH, t0 + timedelta(days=i), f"v{i}".encode()) for i in range(5)]

    remaining = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.html.gz"))
    assert remaining == saved[2:]


def test_pages_are_isolated(tmp_path: Path) -> None:
    store = RawStore(tmp_path, keep=1)
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    store.save(HASH, t0, b"a")
    store.save("ff" + "0" * 62, t0, b"b")
    assert len(list(tmp_path.rglob("*.html.gz"))) == 2
