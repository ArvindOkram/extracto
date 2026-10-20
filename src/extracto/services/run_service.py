"""Run orchestration: one run record wrapping a crawl of each configured site.

Health checks, per-site isolation, the lock file, and the global timeout arrive in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.storage.repositories import RunRepository
from extracto.config import SiteConfig
from extracto.domain.models import RunStatus
from extracto.services.crawl_service import CrawlService, SiteCrawlResult


@dataclass
class RunOutcome:
    run_id: int | None
    results: list[SiteCrawlResult] = field(default_factory=list)


class RunService:
    def __init__(self, crawl: CrawlService, session_factory: sessionmaker[Session] | None) -> None:
        self._crawl = crawl
        self._session_factory = session_factory

    def start(self) -> int:
        """Create the run record and return its id (crawling happens in `execute`)."""
        assert self._session_factory is not None
        with self._session_factory.begin() as session:
            return RunRepository(session).create().id

    def execute(self, run_id: int, sites: list[SiteConfig]) -> RunOutcome:
        """Crawl each site under an existing run; always closes the run (completed/failed)."""
        assert self._session_factory is not None
        outcome = RunOutcome(run_id)
        status = RunStatus.FAILED
        try:
            for site in sites:
                outcome.results.append(self._crawl.crawl_site(site, run_id=run_id))
            status = RunStatus.COMPLETED
        finally:
            with self._session_factory.begin() as session:
                RunRepository(session).close(run_id, status)
        return outcome

    def run(self, sites: list[SiteConfig], *, dry_run: bool = False) -> RunOutcome:
        if dry_run:
            return RunOutcome(
                None, [self._crawl.crawl_site(s, run_id=None, dry_run=True) for s in sites]
            )
        return self.execute(self.start(), sites)
