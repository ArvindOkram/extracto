"""Main-content extraction with trafilatura; links and metadata via selectolax."""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.parse import urljoin, urlsplit

import trafilatura
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from extracto.domain.models import ExtractedPage
from extracto.domain.text import content_hash, is_short_text, normalize_text, strip_cookie_lines


def _links(tree: HTMLParser, base_url: str) -> list[str]:
    seen: dict[str, None] = {}
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme in ("http", "https"):
            seen.setdefault(absolute, None)
    return list(seen)


def _first_text(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    text = normalize_text(node.text()) if node is not None else ""
    return text or None


def _meta(tree: HTMLParser, selector: str) -> str | None:
    node = tree.css_first(selector)
    value = normalize_text(node.attributes.get("content") or "") if node is not None else ""
    return value or None


class TrafilaturaExtractor:
    def __init__(self, noise_selectors: Sequence[str] = ()) -> None:
        self.noise_selectors = tuple(noise_selectors)

    def extract(self, html: str, url: str) -> ExtractedPage:
        tree = HTMLParser(html)
        # Links come from the full page (nav and footer included) for discovery.
        links = _links(tree, url)
        title = _first_text(tree, "title")
        description = _meta(tree, 'meta[name="description"]')

        for selector in self.noise_selectors:
            for node in tree.css(selector):
                node.decompose()
        headings = [h for n in tree.css("h1, h2, h3") if (h := normalize_text(n.text()))]

        raw = trafilatura.extract(
            tree.html or "",
            url=url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=True,
        )
        data = json.loads(raw) if raw else {}
        text = normalize_text(strip_cookie_lines(data.get("text") or ""))

        return ExtractedPage(
            text=text,
            content_hash=content_hash(text),
            short_text=is_short_text(text),
            title=title or data.get("title"),
            description=description or data.get("excerpt"),
            headings=headings,
            published=data.get("date"),
            links=links,
        )
