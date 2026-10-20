from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import create_engine, func, select
from typer.testing import CliRunner

from extracto.adapters.storage.orm import Run, Snapshot
from extracto.cli import app
from extracto.domain.models import RunStatus
from tests.fake_site import FakeSite, Page, html

runner = CliRunner()

CONFIG = """
defaults:
  user_agent: "Extracto-test/1.0 (+contact: qa@x.test)"
  delay_seconds: 0.01
sites:
  - name: Fake
    start_url: https://site.test/
"""


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    config = tmp_path / "sites.yaml"
    config.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("SITES_CONFIG", str(config))
    return tmp_path


@pytest.fixture
def site() -> Iterator[FakeSite]:
    fake = FakeSite(
        {
            "/robots.txt": Page(status=404),
            "/": html("Home", "Welcome home.", ["/pricing"]),
            "/pricing": html("Pricing", "Pro is $29.", ["/"]),
        }
    )
    with respx.mock:
        respx.route(host="site.test").mock(side_effect=fake.handler)
        yield fake


def snapshot_count(data_dir: Path) -> int:
    engine = create_engine(f"sqlite:///{(data_dir / 'monitor.db').as_posix()}")
    with engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(Snapshot.__table__))
    engine.dispose()
    return count or 0


def test_dry_run_prints_pages_and_writes_nothing(env: Path, site: FakeSite) -> None:
    result = runner.invoke(app, ["run", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "https://site.test/pricing" in result.output
    assert '"Pricing"' in result.output
    assert "Fake: 2 pages" in result.output
    assert not (env / "data" / "monitor.db").exists()


def test_run_stores_snapshots_and_closes_run(env: Path, site: FakeSite) -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert "Fake: 2 pages, 2 new snapshots, 0 errors" in result.output
    assert snapshot_count(env / "data") == 2

    engine = create_engine(f"sqlite:///{(env / 'data' / 'monitor.db').as_posix()}")
    with engine.connect() as conn:
        status = conn.scalar(select(Run.__table__.c.status))
    engine.dispose()
    assert status == RunStatus.COMPLETED.value

    again = runner.invoke(app, ["run"])
    assert "0 new snapshots" in again.output
    assert snapshot_count(env / "data") == 2


def test_run_single_site(env: Path, site: FakeSite) -> None:
    result = runner.invoke(app, ["run", "--site", "Fake", "--dry-run"])
    assert result.exit_code == 0, result.output


def test_unknown_site(env: Path, site: FakeSite) -> None:
    result = runner.invoke(app, ["run", "--site", "Nope"])
    assert result.exit_code == 1
    assert "unknown site 'Nope'" in result.output


def test_missing_config(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITES_CONFIG", str(env / "missing.yaml"))
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "config file not found" in result.output


WEBHOOK = "https://discord.com/api/webhooks/1/token"


@pytest.fixture
def discord(site: FakeSite, monkeypatch: pytest.MonkeyPatch) -> respx.Route:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setattr("extracto.adapters.notifiers.discord.time.sleep", lambda _s: None)
    return respx.post(WEBHOOK).respond(204)


def embed(route: respx.Route) -> dict:
    import json

    return json.loads(route.calls.last.request.content)["embeds"][0]


def test_run_notifies_discord(env: Path, discord: respx.Route) -> None:
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert discord.call_count == 1
    sent = embed(discord)
    assert sent["title"] == "Extracto run #1 completed"
    assert sent["fields"][0]["name"] == "Fake"


def test_dry_run_does_not_notify(env: Path, discord: respx.Route) -> None:
    assert runner.invoke(app, ["run", "--dry-run"]).exit_code == 0
    assert not discord.called


def test_no_webhook_configured_is_fine(env: Path, site: FakeSite) -> None:
    assert runner.invoke(app, ["run"]).exit_code == 0


def test_discord_outage_does_not_fail_run(env: Path, discord: respx.Route) -> None:
    discord.respond(500)
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0
    assert "notification failed" in result.output
    assert snapshot_count(env / "data") == 2


def test_crashed_run_sends_failure_notice(
    env: Path, discord: respx.Route, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr("extracto.services.run_service.RunService.run", boom)
    result = runner.invoke(app, ["run"])
    assert result.exit_code != 0
    sent = embed(discord)
    assert sent["title"] == "Extracto run failed"
    assert "RuntimeError: disk full" in sent["description"]


def test_notify_test_command(env: Path, discord: respx.Route) -> None:
    result = runner.invoke(app, ["notify-test"])
    assert result.exit_code == 0, result.output
    assert "sent" in result.output
    assert embed(discord)["title"] == "Extracto test notification"


def test_notify_test_without_webhook(env: Path) -> None:
    result = runner.invoke(app, ["notify-test"])
    assert result.exit_code == 1
    assert "DISCORD_WEBHOOK_URL" in result.output


def test_notify_test_reports_failure(env: Path, discord: respx.Route) -> None:
    discord.mock(side_effect=httpx.ConnectError("down"))
    result = runner.invoke(app, ["notify-test"])
    assert result.exit_code == 1
    assert "token" not in result.output
