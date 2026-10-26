"""Crawl one site: robots.txt, sitemap + link discovery, fetch, extract, store snapshots."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.storage.orm import utcnow
from extracto.adapters.storage.raw_store import RawStore
from extracto.adapters.storage.repositories import (
    FetchRepository,
    PageRepository,
    SiteRepository,
    SnapshotRepository,
)
from extracto.config import SiteConfig
from extracto.domain.models import ExtractedPage, FetchOutcome, FetchResult, PageChange
from extracto.domain.robots import RobotsRules
from extracto.domain.sitemap import parse_sitemap
from extracto.domain.urls import UrlFilter, normalize_url
from extracto.interfaces import Extractor, Fetcher

log = logging.getLogger(__name__)

MAX_SITEMAP_FILES = 10
SITEMAP_SIZE_FACTOR = 5  # sitemaps may be this many times a site's page size limit
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SITEMAP_BUDGET_S = 120.0  # sitemaps are only a seed; stop reading them after this long
ERROR_OUTCOMES = frozenset({FetchOutcome.HTTP_ERROR, FetchOutcome.NETWORK_ERROR})


@dataclass(frozen=True)
class PageResult:
    url: str
    outcome: FetchOutcome
    status_code: int | None = None
    title: str | None = None
    chars: int = 0
    short_text: bool = False
    new_snapshot: bool = False
    change: PageChange | None = None  # None in dry runs and for unchanged pages


@dataclass
class SiteCrawlResult:
    site: str
    pages: list[PageResult] = field(default_factory=list)
    skipped_robots: int = 0
    duration_s: float = 0.0
    baseline: bool = False  # first crawl of this site: every page is "new"

    @property
    def new_pages(self) -> list[PageResult]:
        return [p for p in self.pages if p.change is PageChange.NEW]

    @property
    def updated_pages(self) -> list[PageResult]:
        return [p for p in self.pages if p.change is PageChange.UPDATED]

    @property
    def pages_crawled(self) -> int:
        return len(self.pages)

    @property
    def errors(self) -> int:
        return sum(p.outcome in ERROR_OUTCOMES for p in self.pages)

    @property
    def short_text_pages(self) -> int:
        return sum(p.short_text for p in self.pages)

    @property
    def new_snapshots(self) -> int:
        return sum(p.new_snapshot for p in self.pages)


@dataclass
class _SiteState:
    """Per-crawl working state."""

    site: SiteConfig
    fetcher: Fetcher
    extractor: Extractor
    url_filter: UrlFilter
    robots: dict[str, RobotsRules]  # per origin (scheme://host:port), loaded on first use
    run_id: int | None
    site_id: int | None
    dry_run: bool
    frontier: deque[tuple[str, int]] = field(default_factory=deque)
    queued: set[str] = field(default_factory=set)
    visited: set[str] = field(default_factory=set)

    def enqueue(self, url: str, depth: int) -> None:
        if url not in self.queued:
            self.queued.add(url)
            self.frontier.append((url, depth))


class CrawlService:
    def __init__(
        self,
        *,
        fetcher_factory: Callable[[SiteConfig], Fetcher],
        extractor_factory: Callable[[SiteConfig], Extractor],
        session_factory: sessionmaker[Session] | None,
        raw_store: RawStore | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetcher_factory = fetcher_factory
        self._extractor_factory = extractor_factory
        self._session_factory = session_factory
        self._raw_store = raw_store
        self._clock = clock

    def crawl_site(
        self, site: SiteConfig, *, run_id: int | None, dry_run: bool = False
    ) -> SiteCrawlResult:
        if not dry_run and (run_id is None or self._session_factory is None):
            raise ValueError("a run_id and session_factory are required unless dry_run")
        if site.render_js:
            log.warning("render_js not supported yet; using plain HTTP", extra={"site": site.name})

        started = self._clock()
        result = SiteCrawlResult(site=site.name)
        fetcher = self._fetcher_factory(site)
        try:
            state = self._start(site, fetcher, run_id, dry_run)
            if not dry_run:
                with self._session() as session:
                    result.baseline = not PageRepository(session).site_has_pages(
                        self._site_id(state)
                    )
            while state.frontier and result.pages_crawled < site.max_pages:
                url, depth = state.frontier.popleft()
                if not self._allowed(state, url):
                    result.skipped_robots += 1
                    self._record_skip(state, url)
                    continue
                page = self._crawl_url(state, url, depth)
                if page is not None and page.outcome is FetchOutcome.SKIPPED_ROBOTS:
                    result.skipped_robots += 1  # redirected to a disallowed URL
                elif page is not None:
                    result.pages.append(page)
        finally:
            fetcher.close()
        result.duration_s = self._clock() - started
        log.info(
            "site crawled",
            extra={
                "site": site.name,
                "pages": result.pages_crawled,
                "errors": result.errors,
                "new_snapshots": result.new_snapshots,
                "duration_s": round(result.duration_s, 1),
            },
        )
        return result

    # -- setup --------------------------------------------------------------------------------

    def _start(
        self, site: SiteConfig, fetcher: Fetcher, run_id: int | None, dry_run: bool
    ) -> _SiteState:
        start_url = normalize_url(site.start_url)
        assert start_url is not None  # validated by config

        site_id = None
        if not dry_run:
            assert self._session_factory is not None
            with self._session_factory.begin() as session:
                site_id = SiteRepository(session).upsert(site.name, site.domain).id

        state = _SiteState(
            site=site,
            fetcher=fetcher,
            extractor=self._extractor_factory(site),
            url_filter=UrlFilter.build(
                domain=site.domain,
                extra_domains=site.extra_domains,
                allow_patterns=site.allow_patterns,
                exclude_patterns=site.exclude_patterns,
            ),
            robots={},
            run_id=run_id,
            site_id=site_id,
            dry_run=dry_run,
        )
        robots = self._robots(state, start_url)
        state.enqueue(start_url, 0)  # always crawled, even if allow_patterns don't match it
        if site.use_sitemap:
            sources = [site.sitemap_url] if site.sitemap_url else robots.sitemaps
            for url in self._sitemap_urls(state, sources):
                state.enqueue(url, 0)
        return state

    def _robots(self, state: _SiteState, url: str) -> RobotsRules:
        """robots.txt for the URL's origin; each host (www, blog., extra_domains) has its own."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in state.robots:
            fetcher = state.fetcher
            result = fetcher.fetch(f"{origin}/robots.txt", html_only=False)
            status = (
                result.status_code if result.outcome is not FetchOutcome.NETWORK_ERROR else None
            )
            # Unreachable robots.txt: only the start URL may be fetched (so nothing on other hosts).
            rules = RobotsRules.from_response(
                status, result.text if result.ok else "", state.site.start_url
            )
            delay = rules.crawl_delay(state.site.user_agent)
            if delay is not None and delay > fetcher.delay_seconds:
                fetcher.delay_seconds = delay
            state.robots[origin] = rules
        return state.robots[origin]

    def _allowed(self, state: _SiteState, url: str) -> bool:
        return self._robots(state, url).can_fetch(url, state.site.user_agent)

    def _sitemap_urls(self, state: _SiteState, sources: list[str]) -> list[str]:
        """Crawlable URLs from the sitemaps, most recently modified first, up to max_pages."""
        queue = deque(sources)
        seen: set[str] = set()
        found: dict[str, datetime] = {}  # URL -> <lastmod> (EPOCH when undated)
        limit = state.site.max_pages
        max_bytes = state.site.max_bytes * SITEMAP_SIZE_FACTOR
        deadline = self._clock() + SITEMAP_BUDGET_S
        while queue and len(found) < limit and len(seen) < MAX_SITEMAP_FILES:
            if self._clock() > deadline:
                log.warning(
                    "sitemap time budget used up; relying on links",
                    extra={"site": state.site.name, "sitemaps_read": len(seen)},
                )
                break
            sitemap_url = queue.popleft()
            host = urlsplit(sitemap_url).hostname or ""
            # Offsite sitemaps (even ones listed in robots.txt) are never fetched.
            if (
                sitemap_url in seen
                or not state.url_filter.on_domain(host)
                or not self._allowed(state, sitemap_url)
            ):
                continue
            seen.add(sitemap_url)
            result = state.fetcher.fetch(sitemap_url, html_only=False, max_bytes=max_bytes)
            if not result.ok:
                log.warning(
                    "sitemap unavailable", extra={"url": sitemap_url, "outcome": result.outcome}
                )
                continue
            content = parse_sitemap(result.body, max_bytes=max_bytes)
            # Filter here so only crawlable URLs count toward the page limit.
            for raw in content.urls:
                url = normalize_url(raw)
                if url and url not in found and state.url_filter.reject_reason(url) is None:
                    found[url] = content.lastmod.get(raw, EPOCH)
            queue.extend(content.sitemaps)
        # Newest first (undated last), so fresh posts aren't crowded out by the page cap.
        return sorted(found, key=found.__getitem__, reverse=True)[:limit]  # stable for ties

    # -- per URL ------------------------------------------------------------------------------

    def _crawl_url(self, state: _SiteState, url: str, depth: int) -> PageResult | None:
        if url in state.visited:  # already reached via a redirect
            return None
        etag = last_modified = None
        if not state.dry_run:
            with self._session() as session:
                known = PageRepository(session).get(self._site_id(state), url)
                if known is not None:
                    etag, last_modified = known.etag, known.last_modified

        fetch = state.fetcher.fetch(
            url,
            etag=etag,
            last_modified=last_modified,
            can_follow=lambda target: self._allowed(state, target),
        )
        final = normalize_url(fetch.final_url) or url
        log.info(
            "fetched",
            extra={
                "site": state.site.name,
                "url": url,
                "status": fetch.status_code,
                "outcome": fetch.outcome,
                "bytes": len(fetch.body),
                "duration_ms": fetch.duration_ms,
            },
        )
        if final != url and (
            final in state.visited
            or state.url_filter.reject_reason(final, check_allow=False) is not None
        ):
            # Redirected to a page we've already handled (or shouldn't store).
            self._record(state, fetch, url=url, page_id=None)
            return None
        state.visited.add(final)

        extracted: ExtractedPage | None = None
        if fetch.ok:
            extracted = state.extractor.extract(fetch.text, final)

        change: PageChange | None = None
        if state.dry_run:
            links = extracted.links if extracted else []
            new_snapshot = extracted is not None
        else:
            links, change = self._persist(state, fetch, final, extracted)
            new_snapshot = change is not None

        if depth < state.site.max_depth:
            for link in links:
                normalized = normalize_url(link)
                if normalized and state.url_filter.reject_reason(normalized) is None:
                    state.enqueue(normalized, depth + 1)

        return PageResult(
            url=final,
            outcome=fetch.outcome,
            status_code=fetch.status_code,
            title=extracted.title if extracted else None,
            chars=len(extracted.text) if extracted else 0,
            short_text=extracted.short_text if extracted else False,
            new_snapshot=new_snapshot,
            change=change,
        )

    def _persist(
        self, state: _SiteState, fetch: FetchResult, url: str, extracted: ExtractedPage | None
    ) -> tuple[list[str], PageChange | None]:
        """Write page, snapshot, raw HTML, and fetch log in one transaction.

        Returns the page's links (from the stored snapshot on 304) and the change, if a new
        snapshot was written.
        """
        site_id, run_id = self._site_id(state), self._run_id(state)
        now = utcnow()
        with self._session() as session:
            pages, snapshots = PageRepository(session), SnapshotRepository(session)
            page = pages.get(site_id, url)
            links: list[str] = []
            change: PageChange | None = None

            if extracted is not None:
                page, created = pages.get_or_create(site_id, url)
                page.last_seen = now
                page.etag = fetch.headers.get("etag")
                page.last_modified = fetch.headers.get("last-modified")
                snapshot = snapshots.insert_if_changed(
                    page_id=page.id,
                    run_id=run_id,
                    content_hash=extracted.content_hash,
                    text=extracted.text,
                    title=extracted.title,
                    meta=_meta(extracted),
                    fetched_at=now,
                )
                if snapshot is not None:
                    change = PageChange.NEW if created else PageChange.UPDATED
                    if self._raw_store is not None:
                        snapshot.raw_path = self._raw_store.save(page.url_hash, now, fetch.body)
                links = extracted.links
            elif fetch.outcome is FetchOutcome.NOT_MODIFIED and page is not None:
                page.last_seen = now
                latest = snapshots.latest(page.id)
                links = list((latest.meta or {}).get("links", [])) if latest else []

            FetchRepository(session).record(
                run_id=run_id,
                site_id=site_id,
                page_id=page.id if page is not None else None,
                url=url,
                outcome=fetch.outcome,
                status_code=fetch.status_code,
                duration_ms=fetch.duration_ms,
                bytes=len(fetch.body) or None,
                content_hash=extracted.content_hash if extracted else None,
                error=fetch.error,
            )
        return links, change

    def _record_skip(self, state: _SiteState, url: str) -> None:
        if state.dry_run:
            return
        with self._session() as session:
            FetchRepository(session).record(
                run_id=self._run_id(state),
                site_id=self._site_id(state),
                url=url,
                outcome=FetchOutcome.SKIPPED_ROBOTS,
            )

    def _record(
        self, state: _SiteState, fetch: FetchResult, *, url: str, page_id: int | None
    ) -> None:
        if state.dry_run:
            return
        with self._session() as session:
            FetchRepository(session).record(
                run_id=self._run_id(state),
                site_id=self._site_id(state),
                page_id=page_id,
                url=url,
                outcome=fetch.outcome,
                status_code=fetch.status_code,
                duration_ms=fetch.duration_ms,
                error=fetch.error,
            )

    # -- helpers ------------------------------------------------------------------------------

    def _session(self) -> AbstractContextManager[Session]:
        assert self._session_factory is not None
        return self._session_factory.begin()

    @staticmethod
    def _site_id(state: _SiteState) -> int:
        assert state.site_id is not None
        return state.site_id

    @staticmethod
    def _run_id(state: _SiteState) -> int:
        assert state.run_id is not None
        return state.run_id


def _meta(page: ExtractedPage) -> dict[str, Any]:
    return {
        "description": page.description,
        "headings": page.headings,
        "published": page.published,
        "links": page.links,
        "short_text": page.short_text,
    }
