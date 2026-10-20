from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from extracto.adapters.storage.orm import Fetch, Page, RunSite, Snapshot
from extracto.adapters.storage.repositories import (
    FetchRepository,
    PageRepository,
    RunRepository,
    SiteRepository,
    SnapshotRepository,
    url_hash,
)
from extracto.domain.models import FetchOutcome, PageStatus, RunStatus, SiteHealth

URL = "https://a.test/pricing"


@pytest.fixture
def session(session_factory: sessionmaker[Session]):
    with session_factory.begin() as s:
        yield s


def _site_and_run(session: Session) -> tuple[int, int]:
    site = SiteRepository(session).upsert("Competitor A", "a.test")
    run = RunRepository(session).create()
    return site.id, run.id


def test_upsert_site_is_idempotent_and_updates_domain(session: Session) -> None:
    repo = SiteRepository(session)
    first = repo.upsert("Competitor A", "a.test")
    second = repo.upsert("Competitor A", "www.a.test")
    assert first.id == second.id
    assert second.domain == "www.a.test"


def test_get_or_create_page(session: Session) -> None:
    site_id, _ = _site_and_run(session)
    repo = PageRepository(session)

    page, created = repo.get_or_create(site_id, URL)
    again, created_again = repo.get_or_create(site_id, URL)

    assert created and not created_again
    assert page.id == again.id
    assert page.url_hash == url_hash(URL)
    assert page.status is PageStatus.ACTIVE
    assert page.first_seen.tzinfo is not None


def test_page_url_unique_per_site(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as s:
        site_id = SiteRepository(s).upsert("A", "a.test").id
        PageRepository(s).get_or_create(site_id, URL)
    with pytest.raises(IntegrityError), session_factory.begin() as s:
        s.add(Page(site_id=site_id, url=URL, url_hash=url_hash(URL)))


def test_snapshot_inserted_only_when_hash_changes(session: Session) -> None:
    site_id, run_id = _site_and_run(session)
    page, _ = PageRepository(session).get_or_create(site_id, URL)
    repo = SnapshotRepository(session)
    t0 = datetime(2026, 10, 1, tzinfo=UTC)

    first = repo.insert_if_changed(
        page_id=page.id, run_id=run_id, content_hash="h1", text="v1", fetched_at=t0
    )
    same = repo.insert_if_changed(
        page_id=page.id, run_id=run_id, content_hash="h1", text="v1", fetched_at=t0
    )
    changed = repo.insert_if_changed(
        page_id=page.id,
        run_id=run_id,
        content_hash="h2",
        text="v2",
        fetched_at=t0 + timedelta(days=2),
    )

    assert first is not None and same is None and changed is not None
    assert repo.latest(page.id) == changed
    assert session.scalar(select(func.count()).select_from(Snapshot)) == 2


def test_latest_snapshot_none_for_new_page(session: Session) -> None:
    site_id, _ = _site_and_run(session)
    page, _ = PageRepository(session).get_or_create(site_id, URL)
    assert SnapshotRepository(session).latest(page.id) is None


def test_snapshot_meta_roundtrip(session: Session) -> None:
    site_id, run_id = _site_and_run(session)
    page, _ = PageRepository(session).get_or_create(site_id, URL)
    SnapshotRepository(session).insert_if_changed(
        page_id=page.id, run_id=run_id, content_hash="h", text="t", meta={"price": 39}
    )
    session.expire_all()
    latest = SnapshotRepository(session).latest(page.id)
    assert latest is not None and latest.meta == {"price": 39}


def test_foreign_keys_enforced(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), session_factory.begin() as s:
        s.add(Snapshot(page_id=999, run_id=999, content_hash="h", text="t"))


def test_check_constraint_rejects_unknown_status(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as s:
        site_id = SiteRepository(s).upsert("A", "a.test").id
    with pytest.raises(IntegrityError), session_factory.begin() as s:
        s.execute(
            text(
                "INSERT INTO pages (site_id, url, url_hash, status, first_seen, last_seen,"
                " missed_runs) VALUES (:s, 'u', 'h', 'bogus', '2026-01-01', '2026-01-01', 0)"
            ),
            {"s": site_id},
        )


def test_run_create_and_close(session: Session) -> None:
    repo = RunRepository(session)
    run = repo.create()
    assert run.status is RunStatus.RUNNING and run.finished_at is None

    closed = repo.close(run.id, RunStatus.COMPLETED)
    assert closed.status is RunStatus.COMPLETED
    assert closed.finished_at is not None and closed.finished_at >= closed.started_at


def test_record_site_is_idempotent(session: Session) -> None:
    site_id, run_id = _site_and_run(session)
    repo = RunRepository(session)
    repo.record_site(run_id=run_id, site_id=site_id, health=SiteHealth.OK, pages_crawled=10)
    repo.record_site(
        run_id=run_id, site_id=site_id, health=SiteHealth.DEGRADED, pages_crawled=12, errors=1
    )

    rows = session.scalars(select(RunSite)).all()
    assert len(rows) == 1
    assert rows[0].health is SiteHealth.DEGRADED and rows[0].pages_crawled == 12


def test_record_fetch_without_page(session: Session) -> None:
    site_id, run_id = _site_and_run(session)
    FetchRepository(session).record(
        run_id=run_id, site_id=site_id, url=URL, outcome=FetchOutcome.SKIPPED_ROBOTS
    )
    fetch = session.scalars(select(Fetch)).one()
    assert fetch.page_id is None and fetch.outcome is FetchOutcome.SKIPPED_ROBOTS


def test_naive_datetime_rejected(session_factory: sessionmaker[Session]) -> None:
    with pytest.raises(Exception, match="naive datetime"), session_factory.begin() as s:
        site_id, run_id = _site_and_run(s)
        page, _ = PageRepository(s).get_or_create(site_id, URL)
        SnapshotRepository(s).insert_if_changed(
            page_id=page.id,
            run_id=run_id,
            content_hash="h",
            text="t",
            fetched_at=datetime(2026, 1, 1),
        )


def test_get_page_without_creating(session: Session) -> None:
    site_id, _ = _site_and_run(session)
    repo = PageRepository(session)
    assert repo.get(site_id, URL) is None
    page, _ = repo.get_or_create(site_id, URL)
    assert repo.get(site_id, URL) == page
