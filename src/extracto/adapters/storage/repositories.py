"""Data access. All DB reads and writes go through these repositories."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from extracto.adapters.storage.orm import Fetch, Page, Run, RunSite, Site, Snapshot, utcnow
from extracto.domain.models import FetchOutcome, RunStatus, SiteHealth


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class SiteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, name: str, domain: str) -> Site:
        site = self.session.scalar(select(Site).where(Site.name == name))
        if site is None:
            site = Site(name=name, domain=domain)
            self.session.add(site)
        else:
            site.domain = domain
        self.session.flush()
        return site


class PageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def site_has_pages(self, site_id: int) -> bool:
        return (
            self.session.scalar(select(Page.id).where(Page.site_id == site_id).limit(1)) is not None
        )

    def get(self, site_id: int, url: str) -> Page | None:
        return self.session.scalar(
            select(Page).where(Page.site_id == site_id, Page.url_hash == url_hash(url))
        )

    def get_or_create(self, site_id: int, url: str) -> tuple[Page, bool]:
        """Return the page for an already-normalized URL, and whether it was created."""
        page = self.get(site_id, url)
        if page is not None:
            return page, False
        page = Page(site_id=site_id, url=url, url_hash=url_hash(url))
        self.session.add(page)
        self.session.flush()
        return page, True


class SnapshotRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest(self, page_id: int) -> Snapshot | None:
        return self.session.scalar(
            select(Snapshot)
            .where(Snapshot.page_id == page_id)
            .order_by(Snapshot.fetched_at.desc(), Snapshot.id.desc())
            .limit(1)
        )

    def insert_if_changed(
        self,
        *,
        page_id: int,
        run_id: int,
        content_hash: str,
        text: str,
        title: str | None = None,
        meta: dict[str, Any] | None = None,
        raw_path: str | None = None,
        fetched_at: datetime | None = None,
    ) -> Snapshot | None:
        """Insert a snapshot only if the hash differs from the latest one. None if unchanged."""
        latest = self.latest(page_id)
        if latest is not None and latest.content_hash == content_hash:
            return None
        snapshot = Snapshot(
            page_id=page_id,
            run_id=run_id,
            content_hash=content_hash,
            text=text,
            title=title,
            meta=meta,
            raw_path=raw_path,
            fetched_at=fetched_at or utcnow(),
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot


class RunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self) -> Run:
        run = Run()
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: int) -> Run | None:
        return self.session.get(Run, run_id)

    def recent(self, limit: int = 10) -> list[Run]:
        return list(self.session.scalars(select(Run).order_by(Run.id.desc()).limit(limit)))

    def running(self) -> list[Run]:
        return list(self.session.scalars(select(Run).where(Run.status == RunStatus.RUNNING)))

    def last_activity(self, run_id: int) -> datetime:
        """Time of the run's latest request (or its start), to spot runs that died."""
        latest = self.session.scalar(
            select(func.max(Fetch.fetched_at)).where(Fetch.run_id == run_id)
        )
        return latest or self.session.get_one(Run, run_id).started_at

    def progress(self, run_id: int) -> dict[str, int]:
        fetched = select(func.count()).select_from(Fetch).where(Fetch.run_id == run_id)
        errors = fetched.where(
            Fetch.outcome.in_([FetchOutcome.HTTP_ERROR, FetchOutcome.NETWORK_ERROR])
        )
        snaps = select(func.count()).select_from(Snapshot).where(Snapshot.run_id == run_id)
        return {
            "pages_fetched": self.session.scalar(fetched) or 0,
            "errors": self.session.scalar(errors) or 0,
            "new_snapshots": self.session.scalar(snaps) or 0,
        }

    def site_stats(self, run_id: int) -> list[dict[str, Any]]:
        """Per-site breakdown of a run, in crawl order: fetch outcomes, new/updated pages."""
        sites: dict[int, dict[str, Any]] = {}
        rows = self.session.execute(
            select(
                Fetch.site_id,
                Site.name,
                Fetch.outcome,
                func.count(),
                func.min(Fetch.fetched_at),
                func.max(Fetch.fetched_at),
            )
            .join(Site, Site.id == Fetch.site_id)
            .where(Fetch.run_id == run_id)
            .group_by(Fetch.site_id, Site.name, Fetch.outcome)
        )
        for site_id, name, outcome, count, first, last in rows:
            stats = sites.setdefault(
                site_id,
                {"site": name, "outcomes": {}, "first_fetch_at": first, "last_fetch_at": last},
            )
            stats["outcomes"][FetchOutcome(outcome).value] = count
            stats["first_fetch_at"] = min(stats["first_fetch_at"], first)
            stats["last_fetch_at"] = max(stats["last_fetch_at"], last)

        # A snapshot is an update if its page already had an earlier one, otherwise a new page.
        prev = aliased(Snapshot)
        earlier = (
            select(func.count())
            .where(prev.page_id == Snapshot.page_id, prev.id < Snapshot.id)
            .scalar_subquery()
        )
        snaps = self.session.execute(
            select(Page.site_id, earlier)
            .select_from(Snapshot)
            .join(Page, Page.id == Snapshot.page_id)
            .where(Snapshot.run_id == run_id)
        )
        for site_id, prior in snaps:
            if site_id in sites:
                key = "updated_pages" if prior else "new_pages"
                sites[site_id][key] = sites[site_id].get(key, 0) + 1

        result = []
        for stats in sorted(sites.values(), key=lambda s: s["first_fetch_at"]):
            outcomes = stats["outcomes"]
            result.append(
                {
                    **stats,
                    "pages_fetched": sum(outcomes.values())
                    - outcomes.get(FetchOutcome.SKIPPED_ROBOTS.value, 0),
                    "errors": outcomes.get(FetchOutcome.HTTP_ERROR.value, 0)
                    + outcomes.get(FetchOutcome.NETWORK_ERROR.value, 0),
                    "skipped_robots": outcomes.get(FetchOutcome.SKIPPED_ROBOTS.value, 0),
                    "not_modified": outcomes.get(FetchOutcome.NOT_MODIFIED.value, 0),
                    "new_pages": stats.get("new_pages", 0),
                    "updated_pages": stats.get("updated_pages", 0),
                }
            )
        return result

    def close(self, run_id: int, status: RunStatus) -> Run:
        run = self.session.get_one(Run, run_id)
        run.status = status
        run.finished_at = utcnow()
        self.session.flush()
        return run

    def record_site(
        self,
        *,
        run_id: int,
        site_id: int,
        health: SiteHealth,
        pages_crawled: int = 0,
        errors: int = 0,
        short_text_pages: int = 0,
        duration_s: float | None = None,
    ) -> RunSite:
        """Insert or replace a site's stats for a run (safe to call again on retry)."""
        run_site = self.session.merge(
            RunSite(
                run_id=run_id,
                site_id=site_id,
                health=health,
                pages_crawled=pages_crawled,
                errors=errors,
                short_text_pages=short_text_pages,
                duration_s=duration_s,
            )
        )
        self.session.flush()
        return run_site


class FetchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        run_id: int,
        site_id: int,
        url: str,
        outcome: FetchOutcome,
        page_id: int | None = None,
        status_code: int | None = None,
        duration_ms: int | None = None,
        bytes: int | None = None,
        content_hash: str | None = None,
        error: str | None = None,
    ) -> Fetch:
        fetch = Fetch(
            run_id=run_id,
            site_id=site_id,
            page_id=page_id,
            url=url,
            outcome=outcome,
            status_code=status_code,
            duration_ms=duration_ms,
            bytes=bytes,
            content_hash=content_hash,
            error=error,
        )
        self.session.add(fetch)
        self.session.flush()
        return fetch
