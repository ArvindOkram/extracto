"""sitemap.xml and sitemap index parsing. Pure; fetching happens in the crawl service."""

from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

DEFAULT_MAX_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SitemapContent:
    urls: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)


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
    locs = [
        loc.text.strip()
        for entry in root
        if _local(entry.tag) == child
        for loc in entry
        if _local(loc.tag) == "loc" and loc.text and loc.text.strip()
    ]
    return SitemapContent(urls=locs) if kind == "urlset" else SitemapContent(sitemaps=locs)
