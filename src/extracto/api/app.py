"""HTTP API: trigger crawls with a JSON body. Thin: validates input, calls services.

- POST /crawl       test crawl from a body; waits for the result (dry_run by default)
- POST /runs        scheduled run of sites.yaml in the background; returns 202 immediately
- GET  /runs        recent runs with totals
- GET  /runs/{id}   one run in detail: totals, current site, per-site breakdown
- POST /notify-test check the Discord webhook

Safety: binds to localhost by default (see `extracto serve`), refuses private/internal target
addresses (SSRF), optional X-API-Key, capped page counts for /crawl, one crawl at a time.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from extracto import __version__
from extracto.adapters.fetchers.dns import resolve_host
from extracto.adapters.fetchers.http_fetcher import fetcher_for_site
from extracto.adapters.storage.orm import utcnow
from extracto.adapters.storage.repositories import RunRepository
from extracto.bootstrap import Storage, build_notifier, build_run_service, build_storage
from extracto.config import AppConfig, ConfigError, SiteConfig, load_config
from extracto.domain.models import FetchOutcome, RunStatus
from extracto.domain.net import is_public_ip
from extracto.interfaces import Fetcher, NotificationError, Notifier
from extracto.services.crawl_service import SiteCrawlResult
from extracto.services.notification_service import (
    connectivity_check,
    deliver,
    run_failed,
    run_summary,
)
from extracto.services.run_service import RunService
from extracto.settings import Settings

log = logging.getLogger(__name__)

MAX_PAGES = 50
MAX_DEPTH = 5
MIN_DELAY_SECONDS = 1.0
# A "running" run with no requests for this long is treated as dead (e.g. the host slept).
STALE_AFTER = timedelta(minutes=20)


class CrawlRequest(BaseModel):
    """Either `site` (a name from sites.yaml) or `start_url` plus optional settings."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "start_url": "https://developers.google.com/search/docs/",
                    "allow_patterns": ["^/search/docs"],
                    "max_pages": 10,
                    "max_depth": 2,
                    "dry_run": True,
                },
                {"site": "Google Search Docs", "max_pages": 5, "dry_run": True},
            ]
        },
    )

    site: str | None = Field(None, description="Name of a site in sites.yaml.")
    start_url: str | None = Field(None, description="Crawl this URL with inline settings.")
    name: str | None = Field(None, description="Label for an inline site (default: its host).")
    sitemap_url: str | None = None
    use_sitemap: bool | None = Field(None, description="False: follow links only, no sitemaps.")
    allow_patterns: list[str] = []
    exclude_patterns: list[str] = Field([], description="Added to the defaults in sites.yaml.")
    max_pages: int | None = Field(None, ge=1, le=MAX_PAGES)
    max_depth: int | None = Field(None, ge=0, le=MAX_DEPTH)
    delay_seconds: float | None = Field(None, ge=MIN_DELAY_SECONDS)
    dry_run: bool = Field(True, description="True: crawl and return results, write nothing.")
    notify: bool = Field(True, description="Send the Discord summary (real runs only).")

    @model_validator(mode="after")
    def _one_target(self) -> CrawlRequest:
        if (self.site is None) == (self.start_url is None):
            raise ValueError("set exactly one of 'site' or 'start_url'")
        if self.site is not None:
            inline_only = {"name", "sitemap_url", "allow_patterns", "exclude_patterns"}
            if inline_only & self.model_fields_set:
                raise ValueError(f"{sorted(inline_only)} only apply with 'start_url'")
        return self


class PageOut(BaseModel):
    url: str
    outcome: FetchOutcome
    status_code: int | None
    title: str | None
    chars: int
    short_text: bool
    new_snapshot: bool


class CrawlResponse(BaseModel):
    run_id: int | None
    dry_run: bool
    site: str
    pages_crawled: int
    new_snapshots: int
    errors: int
    skipped_robots: int
    duration_s: float
    notification_error: str | None = None
    pages: list[PageOut]


def _secret(value: SecretStr | str | None) -> str | None:
    if value is None:
        return None
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    return raw or None


def _response(
    result: SiteCrawlResult, run_id: int | None, dry_run: bool, notification_error: str | None
) -> CrawlResponse:
    return CrawlResponse(
        run_id=run_id,
        dry_run=dry_run,
        site=result.site,
        pages_crawled=result.pages_crawled,
        new_snapshots=result.new_snapshots,
        errors=result.errors,
        skipped_robots=result.skipped_robots,
        duration_s=round(result.duration_s, 2),
        notification_error=notification_error,
        pages=[PageOut(**vars(p)) for p in result.pages],
    )


class RunRequest(BaseModel):
    """Start a run of the sites in sites.yaml (all of them, or one)."""

    model_config = ConfigDict(extra="forbid")

    site: str | None = Field(default=None, description="Only this site from sites.yaml.")
    notify: bool = Field(default=True, description="Send the Discord summary when the run ends.")


class RunStarted(BaseModel):
    run_id: int
    status: RunStatus
    status_url: str


class RunStatusOut(BaseModel):
    run_id: int
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    pages_fetched: int
    new_snapshots: int
    errors: int


class SiteRunOut(BaseModel):
    site: str
    pages_fetched: int = Field(description="Requests made (robots.txt skips excluded).")
    new_pages: int = Field(description="Pages seen for the first time.")
    updated_pages: int = Field(description="Pages whose content changed since the last snapshot.")
    not_modified: int = Field(description="Pages the server reported unchanged (HTTP 304).")
    errors: int
    skipped_robots: int
    outcomes: dict[str, int] = Field(description="Count of every fetch outcome.")
    first_fetch_at: datetime
    last_fetch_at: datetime


class RunDetailOut(RunStatusOut):
    duration_s: float = Field(description="So far, if the run is still going.")
    last_activity_at: datetime
    current_site: str | None = Field(description="Site being crawled now (running runs only).")
    sites_crawled: int
    new_pages: int
    updated_pages: int
    not_modified: int
    skipped_robots: int
    sites: list[SiteRunOut]


def create_app(
    settings: Settings | None = None,
    *,
    fetcher_factory: Callable[[SiteConfig], Fetcher] = fetcher_for_site,
    resolver: Callable[[str], list[str]] = resolve_host,
    notifier_factory: Callable[[Settings], Notifier | None] = build_notifier,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Extracto API",
        version=__version__,
        description=(
            "Trigger crawls with a JSON body. `POST /crawl` is for testing (`dry_run: true` "
            "writes nothing); `POST /runs` is for the scheduler (runs in the background)."
        ),
    )
    app.state.crawl_lock = threading.Lock()
    app.state.run_thread = None
    storage_lock = threading.Lock()
    storage_holder: list[Storage] = []

    def storage() -> Storage:
        """Open (and migrate) the database once, on first use."""
        with storage_lock:
            if not storage_holder:
                storage_holder.append(build_storage(settings))
            return storage_holder[0]

    def notifier_or_none() -> Notifier | None:
        try:
            return notifier_factory(settings)
        except ValueError:  # malformed webhook URL: crawl anyway, skip notifying
            return None

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        expected = _secret(settings.api_key)
        if expected is None:
            return
        if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
            raise HTTPException(401, "missing or invalid X-API-Key")

    def load() -> AppConfig:
        try:
            return load_config(settings.sites_config)
        except ConfigError as exc:
            raise HTTPException(400, f"{exc} (defaults such as user_agent come from it)") from None

    def resolve_site(body: CrawlRequest) -> SiteConfig:
        config = load()
        if body.site is not None:
            try:
                site = config.site(body.site)
            except ConfigError as exc:
                raise HTTPException(404, str(exc)) from None
            overrides = body.model_dump(
                include={"max_pages", "max_depth", "delay_seconds", "use_sitemap"}
            )
            updates = {k: v for k, v in overrides.items() if v is not None}
            updates["max_pages"] = min(updates.get("max_pages", site.max_pages), MAX_PAGES)
            return site.model_copy(update=updates)

        values: dict[str, Any] = body.model_dump(
            exclude={"site", "dry_run", "notify"}, exclude_none=True
        )
        values.setdefault("name", urlsplit(body.start_url or "").hostname or "inline")
        values.setdefault("max_pages", min(config.defaults.max_pages, MAX_PAGES))
        values.setdefault("max_depth", min(config.defaults.max_depth, MAX_DEPTH))
        try:
            site = config.build_site(values)
        except ValidationError as exc:
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False, include_input=False)
            ) from None
        sitemap_host = urlsplit(site.sitemap_url).hostname if site.sitemap_url else None
        if sitemap_host and not (
            sitemap_host == site.domain or sitemap_host.endswith("." + site.domain)
        ):
            raise HTTPException(422, "sitemap_url must be on the same domain as start_url")
        return site

    def check_target(site: SiteConfig) -> None:
        host = urlsplit(site.start_url).hostname or ""
        try:
            addresses = resolver(host)
        except OSError:
            raise HTTPException(400, f"cannot resolve host {host!r}") from None
        blocked = [ip for ip in addresses if not is_public_ip(ip)]
        if not addresses or blocked:
            raise HTTPException(400, f"refusing to crawl private or internal address for {host!r}")

    def ensure_no_active_run() -> None:
        """409 if another run is live; mark runs that died silently (host slept) as failed."""
        with storage().session_factory.begin() as session:
            runs = RunRepository(session)
            for run in runs.running():
                if utcnow() - runs.last_activity(run.id) > STALE_AFTER:
                    log.warning("marking stale run as failed", extra={"run_id": run.id})
                    runs.close(run.id, RunStatus.FAILED)
                else:
                    raise HTTPException(409, f"run {run.id} is still running")

    def run_in_background(
        service: RunService, run_id: int, sites: list[SiteConfig], notifier: Notifier | None
    ) -> None:
        lock: threading.Lock = app.state.crawl_lock
        try:
            outcome = service.execute(run_id, sites)
            deliver(notifier, run_summary(outcome))
        except Exception as exc:
            log.exception("run failed", extra={"run_id": run_id})
            deliver(notifier, run_failed(exc, run_id))
        finally:
            lock.release()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Also the scheduler's keep-awake target: keep it free of database work.
        return {"status": "ok"}

    @app.post(
        "/crawl",
        response_model=CrawlResponse,
        dependencies=[Depends(require_key)],
        responses={409: {"description": "Another crawl is running"}},
    )
    def crawl(body: CrawlRequest, request: Request) -> CrawlResponse:
        site = resolve_site(body)
        check_target(site)

        lock: threading.Lock = request.app.state.crawl_lock
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "another crawl is running; try again when it finishes")
        try:
            service = build_run_service(
                settings,
                dry_run=body.dry_run,
                fetcher_factory=fetcher_factory,
                storage=None if body.dry_run else storage(),
            )
            notifier = notifier_or_none() if not body.dry_run and body.notify else None
            try:
                outcome = service.run([site], dry_run=body.dry_run)
            except Exception as exc:
                deliver(notifier, run_failed(exc))
                raise
            error = deliver(notifier, run_summary(outcome))
            return _response(outcome.results[0], outcome.run_id, body.dry_run, error)
        finally:
            lock.release()

    @app.post(
        "/runs",
        status_code=202,
        response_model=RunStarted,
        dependencies=[Depends(require_key)],
        responses={409: {"description": "A run is already in progress"}},
    )
    def start_run(request: Request, body: RunRequest | None = None) -> RunStarted:
        body = body or RunRequest()
        config = load()
        try:
            sites = [config.site(body.site)] if body.site else list(config.sites)
        except ConfigError as exc:
            raise HTTPException(404, str(exc)) from None

        lock: threading.Lock = request.app.state.crawl_lock
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "a run is already in progress")
        try:
            ensure_no_active_run()
            service = build_run_service(
                settings, dry_run=False, fetcher_factory=fetcher_factory, storage=storage()
            )
            run_id = service.start()
            notifier = notifier_or_none() if body.notify else None
            thread = threading.Thread(
                target=run_in_background,
                args=(service, run_id, sites, notifier),
                name=f"extracto-run-{run_id}",
                daemon=True,
            )
            request.app.state.run_thread = thread
            thread.start()  # the thread releases the lock when the run ends
        except BaseException:
            lock.release()
            raise
        return RunStarted(run_id=run_id, status=RunStatus.RUNNING, status_url=f"/runs/{run_id}")

    def status_of(runs: RunRepository, run_id: int) -> RunStatusOut:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"run {run_id} not found")
        return RunStatusOut(
            run_id=run.id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            **runs.progress(run.id),
        )

    @app.get("/runs", response_model=list[RunStatusOut], dependencies=[Depends(require_key)])
    def list_runs(limit: int = 10) -> list[RunStatusOut]:
        with storage().session_factory() as session:
            runs = RunRepository(session)
            return [status_of(runs, r.id) for r in runs.recent(min(max(limit, 1), 100))]

    @app.get("/runs/{run_id}", response_model=RunDetailOut, dependencies=[Depends(require_key)])
    def get_run(run_id: int) -> RunDetailOut:
        """Status, totals, and a per-site breakdown of one run."""
        with storage().session_factory() as session:
            runs = RunRepository(session)
            summary = status_of(runs, run_id)
            sites = [SiteRunOut(**s) for s in runs.site_stats(run_id)]
            last_activity = runs.last_activity(run_id)
        running = summary.status is RunStatus.RUNNING
        end = summary.finished_at or utcnow()
        return RunDetailOut(
            **summary.model_dump(),
            duration_s=round((end - summary.started_at).total_seconds(), 1),
            last_activity_at=last_activity,
            current_site=sites[-1].site if running and sites else None,
            sites_crawled=len(sites),
            new_pages=sum(s.new_pages for s in sites),
            updated_pages=sum(s.updated_pages for s in sites),
            not_modified=sum(s.not_modified for s in sites),
            skipped_robots=sum(s.skipped_robots for s in sites),
            sites=sites,
        )

    @app.post("/notify-test", dependencies=[Depends(require_key)])
    def notify_test() -> dict[str, str]:
        try:
            notifier = notifier_factory(settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        if notifier is None:
            raise HTTPException(400, "DISCORD_WEBHOOK_URL is not set")
        try:
            notifier.send(connectivity_check())
        except NotificationError as exc:
            raise HTTPException(502, str(exc)) from None
        return {"status": "sent"}

    return app
