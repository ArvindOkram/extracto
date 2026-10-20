import gzip

from extracto.domain.sitemap import parse_sitemap

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc> https://a.test/pricing </loc><lastmod>2026-10-01</lastmod></url>
  <url><loc>https://a.test/blog/post-1</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://a.test/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://a.test/sitemap-blog.xml.gz</loc></sitemap>
</sitemapindex>"""


def test_urlset() -> None:
    result = parse_sitemap(URLSET)
    assert result.urls == ["https://a.test/pricing", "https://a.test/blog/post-1"]
    assert result.sitemaps == []


def test_index() -> None:
    result = parse_sitemap(INDEX)
    assert result.sitemaps == [
        "https://a.test/sitemap-pages.xml",
        "https://a.test/sitemap-blog.xml.gz",
    ]
    assert result.urls == []


def test_gzip() -> None:
    assert parse_sitemap(gzip.compress(URLSET)).urls == parse_sitemap(URLSET).urls


def test_gzip_bomb_capped() -> None:
    bomb = gzip.compress(b"<urlset>" + b" " * 5_000_000 + b"</urlset>")
    assert parse_sitemap(bomb, max_bytes=1_000_000).urls == []


def test_without_namespace() -> None:
    assert parse_sitemap(b"<urlset><url><loc>https://a.test/x</loc></url></urlset>").urls == [
        "https://a.test/x"
    ]


def test_malformed_returns_empty() -> None:
    result = parse_sitemap(b"<urlset><url><loc>broken")
    assert result.urls == [] and result.sitemaps == []


def test_entities_rejected() -> None:
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b"<urlset><url><loc>&e;</loc></url></urlset>"
    )
    assert parse_sitemap(evil).urls == []
