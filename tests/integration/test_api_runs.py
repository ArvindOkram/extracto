"""Background runs: POST /runs returns 202 immediately; GET /runs/{id} reports progress."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from extracto.adapters.fetchers.http_fetcher import HttpFetcher, fetcher_for_site
from extracto.adapters.storage.db import make_engine, make_session_factory
from extracto.adapters.storage.orm import Run, utcnow
from extracto.api.app import create_app
from extracto.config import SiteConfig
from extracto.domain.models import Notification, NotificationLevel, RunStatus
from extracto.interfaces import NotificationError
from extracto.settings import Settings
from tests.fake_site import FakeSite, Page, html

CONFIG = """
defaults:
  user_agent: "Extracto-test/1.0 (+contact: qa@x.test)"
sites:
  - name: Fake
    start_url: https://site.test/
  - name: Other
    start_url: https://site.test/blog
    allow_patterns: ["^/blog"]
"""


class RecordingNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Notification] = []
        self.fail = fail

    def send(self, notification: Notification) -> None:
        if self.fail:
            raise NotificationError("Discord unreachable (ConnectError)")
        self.sent.append(notification)


@pytest.fixture
def fake() -> FakeSite:
    return FakeSite(
        {
            "/robots.txt": Page(status=404),
            "/": html("Home", "Welcome home.", ["/pricing", "/blog"]),
            "/pricing": html("Pricing", "Pro is $29.", ["/"]),
            "/blog": html("Blog", "Posts.", ["/"]),
        }
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    config = tmp_path / "sites.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    return Settings(_env_file=None, data_dir=tmp_path / "data", sites_config=config)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def make_client(
    fake: FakeSite, settings: Settings, notifier: RecordingNotifier
) -> Callable[..., TestClient]:
    def factory(
        fetcher_factory: Callable[[SiteConfig], HttpFetcher] | None = None,
        settings_override: Settings | None = None,
        notifier_override: object | None = None,
        sleep: Callable[[float], None] = lambda _s: None,
    ) -> TestClient:
        def fetcher(site: SiteConfig) -> HttpFetcher:
            return fetcher_for_site(site, client=fake.client(), sleep=lambda _s: None)

        chosen = notifier_override if notifier_override is not None else notifier
        app = create_app(
            settings_override or settings,
            fetcher_factory=fetcher_factory or fetcher,
            resolver=lambda _host: ["93.184.216.34"],
            notifier_factory=lambda _s: chosen,  # type: ignore[return-value,arg-type]
            sleep=sleep,
        )
        return TestClient(app)

    return factory


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def wait_for_run(client: TestClient) -> None:
    thread = client.app.state.run_thread  # type: ignore[attr-defined]
    thread.join(timeout=30)
    assert not thread.is_alive()


def test_start_run_returns_202_then_completes(
    client: TestClient, notifier: RecordingNotifier
) -> None:
    resp = client.post("/runs")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert body["status_url"] == f"/runs/{body['run_id']}"

    wait_for_run(client)
    status = client.get(f"/runs/{body['run_id']}").json()
    assert status["status"] == "completed"
    assert status["finished_at"] is not None
    assert status["new_snapshots"] == 4  # Fake: /, /pricing, /blog; Other: its own /blog
    assert status["pages_fetched"] >= 4
    assert status["errors"] == 0
    assert [n.title for n in notifier.sent] == [f"Extracto run #{body['run_id']} completed"]
    assert [f[0] for f in notifier.sent[0].fields] == ["Fake", "Other"]


def test_start_run_for_one_site(client: TestClient, notifier: RecordingNotifier) -> None:
    assert client.post("/runs", json={"site": "Other"}).status_code == 202
    wait_for_run(client)
    assert [f[0] for f in notifier.sent[0].fields] == ["Other"]


def test_run_without_notification(client: TestClient, notifier: RecordingNotifier) -> None:
    client.post("/runs", json={"notify": False})
    wait_for_run(client)
    assert notifier.sent == []


def test_unknown_site(client: TestClient) -> None:
    resp = client.post("/runs", json={"site": "Nope"})
    assert resp.status_code == 404


def test_rejects_unknown_fields(client: TestClient) -> None:
    assert client.post("/runs", json={"sites": ["Fake"]}).status_code == 422


def test_second_start_while_running_is_409(client: TestClient) -> None:
    lock = client.app.state.crawl_lock  # type: ignore[attr-defined]
    lock.acquire()
    try:
        assert client.post("/runs").status_code == 409
    finally:
        lock.release()


def _insert_running_run(settings: Settings, started_ago: timedelta) -> int:
    engine = make_engine(settings.resolved_database_url)
    with make_session_factory(engine).begin() as s:
        run = Run(started_at=utcnow() - started_ago, status=RunStatus.RUNNING)
        s.add(run)
        s.flush()
        run_id = run.id
    engine.dispose()
    return run_id


def test_recent_running_run_in_db_blocks_new_run(client: TestClient, settings: Settings) -> None:
    client.get("/runs")  # creates the schema
    running = _insert_running_run(settings, timedelta(minutes=2))
    resp = client.post("/runs")
    assert resp.status_code == 409
    assert str(running) in resp.json()["detail"]


def test_stale_running_run_is_failed_and_replaced(
    client: TestClient, settings: Settings, notifier: RecordingNotifier
) -> None:
    client.get("/runs")
    stale = _insert_running_run(settings, timedelta(hours=2))

    resp = client.post("/runs")
    assert resp.status_code == 202
    wait_for_run(client)
    client.app.state.alert_thread.join(timeout=10)  # type: ignore[attr-defined]
    assert client.get(f"/runs/{stale}").json()["status"] == "failed"
    titles = {n.title for n in notifier.sent}
    assert f"Extracto run #{stale} was interrupted" in titles


def start_app(client: TestClient) -> None:
    """Run the app's startup (lifespan) and wait for its interrupted-run check."""
    client.__enter__()
    client.app.state.watch_thread.join(timeout=10)  # type: ignore[attr-defined]
    assert not client.app.state.watch_thread.is_alive()  # type: ignore[attr-defined]
    client.__exit__(None, None, None)


def test_startup_alerts_on_run_left_unfinished(
    make_client: Callable[..., TestClient], settings: Settings, notifier: RecordingNotifier
) -> None:
    make_client().get("/runs")  # creates the schema
    orphan = _insert_running_run(settings, timedelta(hours=1))

    client = make_client()
    start_app(client)

    assert client.get(f"/runs/{orphan}").json()["status"] == "failed"
    [alert] = notifier.sent
    assert alert.title == f"Extracto run #{orphan} was interrupted"
    assert alert.level is NotificationLevel.ERROR
    assert "0 of 2 sites" in alert.description


def test_startup_waits_until_a_recent_run_goes_quiet(
    make_client: Callable[..., TestClient],
    settings: Settings,
    notifier: RecordingNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_client().get("/runs")
    orphan = _insert_running_run(settings, timedelta(minutes=2))
    clock = [utcnow()]
    monkeypatch.setattr("extracto.api.app.utcnow", lambda: clock[0])

    def sleep(seconds: float) -> None:
        assert notifier.sent == []  # not alerted while it could still be alive
        clock[0] += timedelta(seconds=seconds) * 10

    client = make_client(sleep=sleep)
    start_app(client)

    assert client.get(f"/runs/{orphan}").json()["status"] == "failed"
    assert [n.title for n in notifier.sent] == [f"Extracto run #{orphan} was interrupted"]


def test_startup_with_no_unfinished_runs_sends_nothing(
    client: TestClient, notifier: RecordingNotifier
) -> None:
    start_app(client)
    assert notifier.sent == []


def test_crash_marks_run_failed_and_notifies(
    make_client: Callable[..., TestClient], notifier: RecordingNotifier
) -> None:
    def broken(_site: SiteConfig) -> HttpFetcher:
        raise RuntimeError("boom")

    client = make_client(fetcher_factory=broken)
    run_id = client.post("/runs").json()["run_id"]
    wait_for_run(client)

    assert client.get(f"/runs/{run_id}").json()["status"] == "failed"
    assert notifier.sent[0].title == f"Extracto run #{run_id} failed"
    assert notifier.sent[0].level is NotificationLevel.ERROR
    # The lock was released: a new run can start.
    assert client.post("/runs").status_code == 202
    wait_for_run(client)


def test_list_recent_runs(client: TestClient) -> None:
    for _ in range(2):
        client.post("/runs", json={"notify": False})
        wait_for_run(client)
    runs = client.get("/runs").json()
    assert [r["run_id"] for r in runs] == [2, 1]


def test_run_details_break_down_by_site(client: TestClient, fake: FakeSite) -> None:
    first = client.post("/runs", json={"notify": False}).json()["run_id"]
    wait_for_run(client)
    fake.pages["/pricing"] = html("Pricing", "Pro is now $39.", ["/"])
    second = client.post("/runs", json={"notify": False}).json()["run_id"]
    wait_for_run(client)

    detail = client.get(f"/runs/{first}").json()
    assert detail["status"] == "completed" and detail["current_site"] is None
    assert detail["sites_crawled"] == 2
    assert detail["new_pages"] == 4 and detail["updated_pages"] == 0
    assert detail["duration_s"] >= 0
    fake_site = detail["sites"][0]
    assert fake_site["site"] == "Fake"
    assert fake_site["new_pages"] == 3 and fake_site["errors"] == 0
    assert fake_site["outcomes"] == {"ok": 3}

    detail = client.get(f"/runs/{second}").json()
    assert detail["new_pages"] == 0 and detail["updated_pages"] == 1
    assert [s["updated_pages"] for s in detail["sites"]] == [1, 0]


def test_running_run_reports_current_site(client: TestClient, settings: Settings) -> None:
    client.get("/runs")
    run_id = _insert_running_run(settings, timedelta(minutes=1))
    detail = client.get(f"/runs/{run_id}").json()
    assert detail["status"] == "running"
    assert detail["sites"] == [] and detail["current_site"] is None
    assert detail["duration_s"] >= 60


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/runs/999").status_code == 404


def test_endpoints_require_key_when_set(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    keyed = make_client(settings_override=settings.model_copy(update={"api_key": "k"}))
    assert keyed.post("/runs").status_code == 401
    assert keyed.get("/runs").status_code == 401
    assert keyed.get("/runs/1").status_code == 401
    assert keyed.post("/notify-test").status_code == 401
    assert keyed.get("/healthz").status_code == 200


def test_notify_test_sends(client: TestClient, notifier: RecordingNotifier) -> None:
    resp = client.post("/notify-test")
    assert resp.status_code == 200 and resp.json() == {"status": "sent"}
    assert notifier.sent[0].title == "Extracto test notification"


def test_notify_test_failure_is_502(make_client: Callable[..., TestClient]) -> None:
    client = make_client(notifier_override=RecordingNotifier(fail=True))
    resp = client.post("/notify-test")
    assert resp.status_code == 502
    assert "Discord unreachable" in resp.json()["detail"]


def test_notify_test_not_configured(fake: FakeSite, settings: Settings) -> None:
    app = create_app(settings, notifier_factory=lambda _s: None)
    resp = TestClient(app).post("/notify-test")
    assert resp.status_code == 400
    assert "DISCORD_WEBHOOK_URL" in resp.json()["detail"]


def test_wake_up_ping_is_cheap(client: TestClient) -> None:
    # cron-job.org's keep-awake job hits /healthz; it must not touch the database.
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert isinstance(resp, httpx.Response)
