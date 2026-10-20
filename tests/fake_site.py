"""An in-memory website for crawl tests, served through httpx.MockTransport.

Tests mutate `pages` between runs to simulate edits, additions, and removals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

BASE = "https://site.test"
FILLER = (
    "This paragraph exists so the page has enough real text to pass the short-text check. "
    "It describes the product in plain language for marketing readers."
)


@dataclass
class Page:
    status: int = 200
    body: str | bytes = ""
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


def html(title: str, body: str, links: list[str] | None = None) -> Page:
    nav = "".join(f'<a href="{href}">{href}</a> ' for href in links or [])
    return Page(
        body=(
            f"<html><head><title>{title}</title></head><body>"
            f"<nav>{nav} SITE NAVIGATION</nav>"
            f"<main><article><h1>{title}</h1><p>{body}</p><p>{FILLER}</p></article></main>"
            "<footer>SITE FOOTER</footer></body></html>"
        )
    )


def sitemap(*paths: str) -> Page:
    urls = "".join(f"<url><loc>{BASE}{p}</loc></url>" for p in paths)
    return Page(
        body=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        content_type="application/xml",
    )


class FakeSite:
    def __init__(self, pages: dict[str, Page]) -> None:
        self.pages = pages
        self.requests: list[httpx.Request] = []

    @property
    def paths_requested(self) -> list[str]:
        return [_path(r.url) for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        page = self.pages.get(_path(request.url))
        if page is None:
            return httpx.Response(404, text="not found")
        etag = page.headers.get("etag")
        if etag and request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(
            page.status,
            headers={"content-type": page.content_type, **page.headers},
            content=page.body,
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _path(url: httpx.URL) -> str:
    return url.raw_path.decode()
