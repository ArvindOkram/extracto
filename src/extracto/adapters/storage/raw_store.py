"""Gzip raw HTML on disk, keyed by URL hash. Keeps the newest N per page for debugging."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path


class RawStore:
    def __init__(self, base_dir: Path, keep: int = 3) -> None:
        self.base_dir = base_dir
        self.keep = keep

    def save(self, url_hash: str, fetched_at: datetime, body: bytes) -> str:
        """Write a snapshot and prune old ones. Returns the path relative to `base_dir`."""
        page_dir = self.base_dir / url_hash[:2] / url_hash
        page_dir.mkdir(parents=True, exist_ok=True)
        stamp = fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = page_dir / f"{stamp}.html.gz"
        path.write_bytes(gzip.compress(body))

        for old in sorted(page_dir.glob("*.html.gz"))[: -self.keep or None]:
            old.unlink()
        return path.relative_to(self.base_dir).as_posix()

    def load(self, relative_path: str) -> bytes:
        return gzip.decompress((self.base_dir / relative_path).read_bytes())
