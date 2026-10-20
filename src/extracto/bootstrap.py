"""Composition root: wires adapters into services. The CLI and the API call this."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.extractors.trafilatura_extractor import TrafilaturaExtractor
from extracto.adapters.fetchers.http_fetcher import fetcher_for_site
from extracto.adapters.notifiers.discord import DiscordNotifier
from extracto.adapters.storage.db import make_engine, make_session_factory
from extracto.adapters.storage.migrate import upgrade_to_head
from extracto.adapters.storage.raw_store import RawStore
from extracto.config import SiteConfig
from extracto.interfaces import Fetcher
from extracto.services.crawl_service import CrawlService
from extracto.services.run_service import RunService
from extracto.settings import Settings


@dataclass(frozen=True)
class Storage:
    engine: Engine
    session_factory: sessionmaker[Session]
    raw_store: RawStore | None


def build_storage(settings: Settings) -> Storage:
    """Migrate the schema (idempotent) and open the database. Build once per process."""
    url = settings.resolved_database_url
    upgrade_to_head(url)
    engine = make_engine(url)
    raw_store = RawStore(settings.raw_dir) if settings.raw_html_enabled else None
    return Storage(engine, make_session_factory(engine), raw_store)


def build_run_service(
    settings: Settings,
    *,
    dry_run: bool,
    fetcher_factory: Callable[[SiteConfig], Fetcher] = fetcher_for_site,
    storage: Storage | None = None,
) -> RunService:
    if not dry_run and storage is None:
        storage = build_storage(settings)
    session_factory = storage.session_factory if storage and not dry_run else None
    crawl = CrawlService(
        fetcher_factory=fetcher_factory,
        extractor_factory=lambda site: TrafilaturaExtractor(site.noise_selectors),
        session_factory=session_factory,
        raw_store=storage.raw_store if storage and not dry_run else None,
    )
    return RunService(crawl, session_factory)


def build_notifier(settings: Settings) -> DiscordNotifier | None:
    """The configured notifier, or None when no webhook is set."""
    if settings.discord_webhook_url is None:
        return None
    url = settings.discord_webhook_url.get_secret_value().strip()
    return DiscordNotifier(url) if url else None
