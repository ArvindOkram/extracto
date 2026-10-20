from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.extractors.trafilatura_extractor import TrafilaturaExtractor
from extracto.adapters.fetchers.http_fetcher import HttpFetcher, fetcher_for_site
from extracto.adapters.storage.orm import Fetch, Page, Snapshot
from extracto.adapters.storage.raw_store import RawStore
from extracto.adapters.storage.repositories import RunRepository
from extracto.config import SiteConfig
from extracto.domain.models import FetchOutcome, PageChange
from extracto.services.crawl_service import CrawlService
from tests.fake_site import BASE, FakeSite, html, sitemap
from tests.fake_site import Page as FakePage

UA = "Extracto-test/1.0 (+contact: qa@x.test)"


def make_site(**overrides: object) -> SiteConfig:
    values: dict[str, object] = {
        "name": "Fake",
        "start_url": f"{BASE}/",
        "user_agent": UA,
        "delay_seconds": 0.01,
        "exclude_patterns": ["/search", "/login"],
        **overrides,
    }
    return SiteConfig.model_validate(values)


def build_pages() -> dict[str, FakePage]:
    return {
        "/robots.txt": FakePage(
            body=f"User-agent: *\nDisallow: /private\n\nSitemap: {BASE}/sitemap.xml\n",
            content_type="text/plain",
        ),
        "/sitemap.xml": sitemap("/pricing", "/only-in-sitemap"),
        "/": html(
            "Home",
            "Welcome to the fake site home page.",
            [
                "/pricing",
                "/about",
                "/blog",
                "/private/secret",
                "/search?q=x",
                "/login",
                "/files/brochure.pdf",
                "https://other.test/",
                "/old-pricing",
            ],
        ),
        "/pricing": html("Pricing", "The Pro plan costs $29 per month.", ["/"]),
        "/about": html("About", "We build fake software for testing.", ["/"]),
        "/blog": html("Blog", "Latest posts from the team.", ["/blog/post-1", "/blog/post-2"]),
        "/blog/post-1": html("Post 1", "Our first announcement.", ["/blog"]),
        "/blog/post-2": html("Post 2", "Our second announcement.", ["/blog"]),
        "/only-in-sitemap": html("Hidden", "Not linked from navigation.", []),
        "/old-pricing": FakePage(status=301, headers={"location": "/pricing"}),
        "/private/secret": html("Secret", "Should never be fetched.", []),
    }


EXPECTED_PAGES = {
    f"{BASE}/",
    f"{BASE}/pricing",
    f"{BASE}/about",
    f"{BASE}/blog",
    f"{BASE}/blog/post-1",
    f"{BASE}/blog/post-2",
    f"{BASE}/only-in-sitemap",
}


class Harness:
    def __init__(self, session_factory: sessionmaker[Session], raw_dir: Path) -> None:
        self.fake = FakeSite(build_pages())
        self.session_factory = session_factory
        self.raw_store = RawStore(raw_dir)
        self.fetchers: list[HttpFetcher] = []
        self.service = CrawlService(
            fetcher_factory=self._fetcher,
            extractor_factory=lambda site: TrafilaturaExtractor(site.noise_selectors),
            session_factory=session_factory,
            raw_store=self.raw_store,
        )

    def _fetcher(self, site: SiteConfig) -> HttpFetcher:
        fetcher = fetcher_for_site(site, client=self.fake.client(), sleep=lambda _s: None)
        self.fetchers.append(fetcher)
        return fetcher

    def run(self, site: SiteConfig | None = None):
        with self.session_factory.begin() as s:
            run_id = RunRepository(s).create().id
        return self.service.crawl_site(site or make_site(), run_id=run_id)

    def count(self, model: type) -> int:
        with self.session_factory() as s:
            return s.scalar(select(func.count()).select_from(model)) or 0

    def page_urls(self) -> set[str]:
        with self.session_factory() as s:
            return set(s.scalars(select(Page.url)))


@pytest.fixture
def h(session_factory: sessionmaker[Session], tmp_path: Path) -> Harness:
    return Harness(session_factory, tmp_path / "raw")


def test_crawl_stores_expected_pages(h: Harness) -> None:
    result = h.run()

    assert h.page_urls() == EXPECTED_PAGES
    assert result.new_snapshots == len(EXPECTED_PAGES)
    assert result.errors == 0
    assert h.count(Snapshot) == len(EXPECTED_PAGES)


def test_skips_junk_offsite_and_excluded_urls(h: Harness) -> None:
    h.run()
    requested = h.fake.paths_requested
    for path in ["/search?q=x", "/login", "/files/brochure.pdf"]:
        assert path not in requested
    assert all(r.url.host == "site.test" for r in h.fake.requests)


def test_robots_disallowed_never_requested_but_logged(h: Harness) -> None:
    result = h.run()
    assert "/private/secret" not in h.fake.paths_requested
    assert result.skipped_robots == 1
    with h.session_factory() as s:
        outcomes = set(s.scalars(select(Fetch.outcome).where(Fetch.url.like("%/private/%"))))
    assert outcomes == {FetchOutcome.SKIPPED_ROBOTS}


def test_redirect_does_not_duplicate_pages(h: Harness) -> None:
    h.run()
    assert "/old-pricing" in h.fake.paths_requested
    assert f"{BASE}/old-pricing" not in h.page_urls()


def test_stored_text_is_clean_and_raw_html_saved(h: Harness) -> None:
    h.run()
    with h.session_factory() as s:
        snap = s.scalars(select(Snapshot).join(Page).where(Page.url == f"{BASE}/pricing")).one()
    assert "The Pro plan costs $29 per month." in snap.text
    assert "SITE NAVIGATION" not in snap.text and "SITE FOOTER" not in snap.text
    assert snap.title == "Pricing"
    assert snap.raw_path is not None
    assert b"<title>Pricing</title>" in h.raw_store.load(snap.raw_path)


def test_second_unchanged_run_creates_no_snapshots(h: Harness) -> None:
    h.run()
    result = h.run()
    assert result.new_snapshots == 0
    assert h.count(Snapshot) == len(EXPECTED_PAGES)


def test_changed_page_gets_new_snapshot(h: Harness) -> None:
    h.run()
    h.fake.pages["/pricing"] = html("Pricing", "The Pro plan costs $39 per month.", ["/"])
    result = h.run()
    assert result.new_snapshots == 1
    assert h.count(Snapshot) == len(EXPECTED_PAGES) + 1


def test_not_modified_pages_still_yield_links(h: Harness) -> None:
    for page in h.fake.pages.values():
        page.headers.setdefault("etag", '"v1"')
    h.run()
    h.fake.requests.clear()

    result = h.run()

    not_modified = [r for r in h.fake.requests if r.headers.get("if-none-match") == '"v1"']
    assert not_modified, "second run should send conditional requests"
    # Pages only reachable through links on 304 pages were still crawled.
    assert "/blog/post-1" in h.fake.paths_requested
    assert result.new_snapshots == 0


def test_page_cap(h: Harness) -> None:
    result = h.run(make_site(max_pages=3))
    assert result.pages_crawled == 3
    assert len(h.page_urls()) == 3


def test_depth_limit(h: Harness) -> None:
    h.run(make_site(max_depth=0))
    # Start URL plus sitemap URLs; no link-following.
    assert h.page_urls() == {f"{BASE}/", f"{BASE}/pricing", f"{BASE}/only-in-sitemap"}


def test_start_url_exempt_from_allow_patterns(h: Harness) -> None:
    h.run(make_site(allow_patterns=["^/blog"]))
    assert h.page_urls() == {
        f"{BASE}/",
        f"{BASE}/blog",
        f"{BASE}/blog/post-1",
        f"{BASE}/blog/post-2",
    }


def test_server_errors_counted(h: Harness) -> None:
    h.fake.pages["/about"] = FakePage(status=500)
    result = h.run()
    assert result.errors == 1
    with h.session_factory() as s:
        fetch = s.scalars(select(Fetch).where(Fetch.url == f"{BASE}/about")).one()
    assert fetch.outcome is FetchOutcome.HTTP_ERROR and fetch.status_code == 500


def test_robots_crawl_delay_raises_site_delay(h: Harness) -> None:
    h.fake.pages["/robots.txt"] = FakePage(
        body="User-agent: *\nCrawl-delay: 7\n", content_type="text/plain"
    )
    h.run()
    assert h.fetchers[-1].delay_seconds == 7


def test_unreachable_robots_crawls_only_start_url(h: Harness) -> None:
    h.fake.pages["/robots.txt"] = FakePage(status=503)
    h.run()
    assert h.page_urls() == {f"{BASE}/"}


def test_dry_run_writes_nothing(session_factory: sessionmaker[Session]) -> None:
    fake = FakeSite(build_pages())
    service = CrawlService(
        fetcher_factory=lambda site: fetcher_for_site(
            site, client=fake.client(), sleep=lambda _s: None
        ),
        extractor_factory=lambda site: TrafilaturaExtractor(site.noise_selectors),
        session_factory=None,
        raw_store=None,
    )
    result = service.crawl_site(make_site(), run_id=None, dry_run=True)

    assert {p.url for p in result.pages if p.outcome is FetchOutcome.OK} == EXPECTED_PAGES
    assert {p.title for p in result.pages if p.url == f"{BASE}/pricing"} == {"Pricing"}
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Page)) == 0


def test_offsite_sitemaps_never_fetched(h: Harness) -> None:
    h.fake.pages["/robots.txt"] = FakePage(
        body="User-agent: *\nSitemap: http://10.0.0.1/sitemap.xml\n", content_type="text/plain"
    )
    h.run()
    assert all(r.url.host == "site.test" for r in h.fake.requests)


def _changes(result) -> dict[str, str]:
    return {p.url: p.change for p in result.pages if p.change is not None}


def test_first_crawl_is_baseline_with_all_pages_new(h: Harness) -> None:
    result = h.run()
    assert result.baseline
    assert set(_changes(result)) == EXPECTED_PAGES
    assert set(_changes(result).values()) == {PageChange.NEW}
    assert len(result.new_pages) == len(EXPECTED_PAGES) and result.updated_pages == []


def test_unchanged_second_crawl_has_no_changes(h: Harness) -> None:
    h.run()
    result = h.run()
    assert not result.baseline
    assert _changes(result) == {}


def test_edited_and_added_pages_classified(h: Harness) -> None:
    h.run()
    h.fake.pages["/pricing"] = html("Pricing", "The Pro plan costs $39 per month.", ["/"])
    h.fake.pages["/blog/post-3"] = html("Post 3", "A brand new announcement.", ["/blog"])
    h.fake.pages["/blog"] = html(
        "Blog", "Latest posts from the team.", ["/blog/post-1", "/blog/post-2", "/blog/post-3"]
    )
    result = h.run()

    # /blog only gained a nav link; navigation isn't content, so it doesn't count as updated.
    assert _changes(result) == {
        f"{BASE}/pricing": PageChange.UPDATED,
        f"{BASE}/blog/post-3": PageChange.NEW,
    }
    assert [p.title for p in result.updated_pages] == ["Pricing"]
    assert [p.title for p in result.new_pages] == ["Post 3"]
