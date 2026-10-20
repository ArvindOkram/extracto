from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from extracto.adapters.fetchers.http_fetcher import HttpFetcher, fetcher_for_site
from extracto.adapters.storage.orm import Snapshot
from extracto.api.app import create_app
from extracto.config import SiteConfig
from extracto.domain.models import Notification
from extracto.settings import Settings
from tests.fake_site import FakeSite, Page, html

PUBLIC_IP = "93.184.216.34"
CONFIG = """
defaults:
  user_agent: "Extracto-test/1.0 (+contact: qa@x.test)"
  delay_seconds: 2.5
sites:
  - name: Fake
    start_url: https://site.test/
"""


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
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
        resolver: Callable[[str], list[str]] = lambda _host: [PUBLIC_IP],
        settings_override: Settings | None = None,
    ) -> TestClient:
        def fetcher(site: SiteConfig) -> HttpFetcher:
            return fetcher_for_site(site, client=fake.client(), sleep=lambda _s: None)

        app = create_app(
            settings_override or settings,
            fetcher_factory=fetcher,
            resolver=resolver,
            notifier_factory=lambda _settings: notifier,
        )
        return TestClient(app)

    return factory


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def snapshots(settings: Settings) -> int:
    db = settings.data_dir / "monitor.db"
    if not db.exists():
        return 0
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(Snapshot.__table__)) or 0
    engine.dispose()
    return count


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_inline_dry_run(
    client: TestClient, settings: Settings, notifier: RecordingNotifier
) -> None:
    resp = client.post("/crawl", json={"start_url": "https://site.test/", "max_pages": 10})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True and body["run_id"] is None
    assert body["site"] == "site.test"
    assert body["pages_crawled"] == 3
    assert {p["url"] for p in body["pages"]} == {
        "https://site.test/",
        "https://site.test/pricing",
        "https://site.test/blog",
    }
    assert {p["title"] for p in body["pages"]} == {"Home", "Pricing", "Blog"}
    assert snapshots(settings) == 0
    assert notifier.sent == []


def test_inline_patterns_and_limits(client: TestClient) -> None:
    resp = client.post(
        "/crawl",
        json={"start_url": "https://site.test/", "allow_patterns": ["^/pricing"], "max_depth": 1},
    )
    assert {p["url"] for p in resp.json()["pages"]} == {
        "https://site.test/",
        "https://site.test/pricing",
    }


def test_real_run_stores_and_notifies(
    client: TestClient, settings: Settings, notifier: RecordingNotifier
) -> None:
    resp = client.post("/crawl", json={"start_url": "https://site.test/", "dry_run": False})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == 1 and body["new_snapshots"] == 3
    assert snapshots(settings) == 3
    assert [n.title for n in notifier.sent] == ["Extracto run #1 completed"]


def test_real_run_without_notify(client: TestClient, notifier: RecordingNotifier) -> None:
    client.post(
        "/crawl", json={"start_url": "https://site.test/", "dry_run": False, "notify": False}
    )
    assert notifier.sent == []


def test_named_site_from_config(client: TestClient) -> None:
    resp = client.post("/crawl", json={"site": "Fake"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["site"] == "Fake"


def test_unknown_named_site(client: TestClient) -> None:
    resp = client.post("/crawl", json={"site": "Nope"})
    assert resp.status_code == 404
    assert "unknown site 'Nope'" in resp.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"site": "Fake", "start_url": "https://site.test/"},
        {"start_url": "ftp://site.test/"},
        {"start_url": "https://site.test/", "max_pages": 51},
        {"start_url": "https://site.test/", "max_pages": 0},
        {"start_url": "https://site.test/", "max_depth": 6},
        {"start_url": "https://site.test/", "delay_seconds": 0.5},
        {"start_url": "https://site.test/", "allow_patterns": ["(bad"]},
        {"start_url": "https://site.test/", "sitemap_url": "https://elsewhere.test/s.xml"},
        {"start_url": "https://site.test/", "surprise": True},
    ],
)
def test_validation_errors(client: TestClient, body: dict) -> None:
    assert client.post("/crawl", json=body).status_code == 422


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"])
def test_private_targets_refused(make_client: Callable[..., TestClient], ip: str) -> None:
    client = make_client(resolver=lambda _host: [PUBLIC_IP, ip])
    resp = client.post("/crawl", json={"start_url": "https://site.test/"})
    assert resp.status_code == 400
    assert "private" in resp.json()["detail"]


def test_unresolvable_host(make_client: Callable[..., TestClient]) -> None:
    def fail(_host: str) -> list[str]:
        raise OSError("no such host")

    resp = make_client(resolver=fail).post("/crawl", json={"start_url": "https://site.test/"})
    assert resp.status_code == 400
    assert "resolve" in resp.json()["detail"]


def test_missing_config_file(make_client: Callable[..., TestClient], tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, sites_config=tmp_path / "none.yaml")
    resp = make_client(settings_override=settings).post(
        "/crawl", json={"start_url": "https://site.test/"}
    )
    assert resp.status_code == 400
    assert "config file not found" in resp.json()["detail"]


def test_api_key_enforced_when_set(
    make_client: Callable[..., TestClient], settings: Settings
) -> None:
    keyed = settings.model_copy(update={"api_key": "s3cret"})
    client = make_client(settings_override=keyed)
    body = {"start_url": "https://site.test/"}

    assert client.post("/crawl", json=body).status_code == 401
    assert client.post("/crawl", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/crawl", json=body, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/healthz").status_code == 200  # health stays open


def test_one_crawl_at_a_time(client: TestClient) -> None:
    lock = client.app.state.crawl_lock  # type: ignore[attr-defined]
    lock.acquire()
    try:
        resp = client.post("/crawl", json={"start_url": "https://site.test/"})
    finally:
        lock.release()
    assert resp.status_code == 409


def test_interactive_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
