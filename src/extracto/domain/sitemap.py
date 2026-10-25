"""sitemap.xml and sitemap index parsing. Pure; fetching happens in the crawl service."""

from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime

DEFAULT_MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SitemapContent:
    urls: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    lastmod: dict[str, datetime] = field(default_factory=dict)  # page URL -> <lastmod>


def _decompress(data: bytes, max_bytes: int) -> bytes | None:
    if not data.startswith(b"\x1f\x8b"):
        return data
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
            out = f.read(max_bytes + 1)
    except (OSError, EOFError):
        return None
    return None if len(out) > max_bytes else out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(value: str | None) -> datetime | None:
    """W3C datetime (e.g. 2024-05-01 or 2024-05-01T10:00:00+05:30), as aware UTC."""
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return when.replace(tzinfo=when.tzinfo or UTC).astimezone(UTC)


def parse_sitemap(data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> SitemapContent:
    """Extract page URLs (urlset) or child sitemaps (sitemapindex). Never raises."""
    xml = _decompress(data, max_bytes)
    # Untrusted input: refuse DTDs/entities outright (XXE, entity expansion).
    if xml is None or b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        return SitemapContent()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return SitemapContent()

    kind = _local(root.tag)
    child = {"urlset": "url", "sitemapindex": "sitemap"}.get(kind)
    if child is None:
        return SitemapContent()
    locs: list[str] = []
    lastmod: dict[str, datetime] = {}
    for entry in root:
        if _local(entry.tag) != child:
            continue
        fields = {_local(el.tag): (el.text or "").strip() for el in entry}
        if loc := fields.get("loc"):
            locs.append(loc)
            if (when := _parse_date(fields.get("lastmod"))) is not None:
                lastmod[loc] = when
    if kind == "sitemapindex":
        return SitemapContent(sitemaps=locs)
    return SitemapContent(urls=locs, lastmod=lastmod)
