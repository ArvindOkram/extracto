import json
from collections.abc import Iterator

import httpx
import pytest
import respx

from extracto.adapters.notifiers.discord import DiscordNotifier, NotificationError
from extracto.domain.models import Notification, NotificationLevel

WEBHOOK = "https://discord.com/api/webhooks/123/secret-token"


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def notifier(sleeps: list[float]) -> Iterator[DiscordNotifier]:
    n = DiscordNotifier(WEBHOOK, sleep=sleeps.append)
    yield n
    n.close()


def sample(**overrides: object) -> Notification:
    values: dict[str, object] = {
        "title": "Extracto run #7 completed",
        "description": "2 sites · 10 pages",
        "level": NotificationLevel.OK,
        "fields": [("Competitor A", "7 pages")],
        **overrides,
    }
    return Notification(**values)  # type: ignore[arg-type]


def body(route: respx.Route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_posts_embed(notifier: DiscordNotifier) -> None:
    route = respx.post(WEBHOOK).respond(204)
    notifier.send(sample())

    payload = body(route)
    embed = payload["embeds"][0]
    assert payload["username"] == "Extracto"
    assert embed["title"] == "Extracto run #7 completed"
    assert embed["description"] == "2 sites · 10 pages"
    assert embed["color"] == 0x2ECC71
    assert embed["fields"] == [{"name": "Competitor A", "value": "7 pages", "inline": False}]
    assert "timestamp" in embed


@respx.mock
def test_mentions_disabled(notifier: DiscordNotifier) -> None:
    # Page titles are untrusted; an "@everyone" in one must never ping the channel.
    route = respx.post(WEBHOOK).respond(204)
    notifier.send(sample(fields=[("@everyone", "<@&123> hi")]))
    assert body(route)["allowed_mentions"] == {"parse": []}


@pytest.mark.parametrize(
    ("level", "color"),
    [(NotificationLevel.WARNING, 0xF1C40F), (NotificationLevel.ERROR, 0xE74C3C)],
)
@respx.mock
def test_level_colors(notifier: DiscordNotifier, level: NotificationLevel, color: int) -> None:
    route = respx.post(WEBHOOK).respond(204)
    notifier.send(sample(level=level))
    assert body(route)["embeds"][0]["color"] == color


@respx.mock
def test_discord_limits_respected(notifier: DiscordNotifier) -> None:
    route = respx.post(WEBHOOK).respond(204)
    notifier.send(
        sample(
            title="T" * 400,
            description="D" * 5000,
            fields=[(f"site {i}", "v" * 2000) for i in range(40)],
        )
    )
    embed = body(route)["embeds"][0]
    assert len(embed["title"]) <= 256
    assert len(embed["description"]) <= 4096
    assert len(embed["fields"]) <= 25
    assert all(len(f["value"]) <= 1024 for f in embed["fields"])
    total = len(embed["title"]) + len(embed["description"])
    total += sum(len(f["name"]) + len(f["value"]) for f in embed["fields"])
    assert total <= 6000


@respx.mock
def test_empty_field_value_replaced(notifier: DiscordNotifier) -> None:
    route = respx.post(WEBHOOK).respond(204)
    notifier.send(sample(fields=[("A", "")]))
    assert body(route)["embeds"][0]["fields"][0]["value"] == "-"


@respx.mock
def test_rate_limit_retried(notifier: DiscordNotifier, sleeps: list[float]) -> None:
    route = respx.post(WEBHOOK).mock(
        side_effect=[
            httpx.Response(429, json={"retry_after": 1.5, "global": False}),
            httpx.Response(204),
        ]
    )
    notifier.send(sample())
    assert route.call_count == 2
    assert sleeps == [1.5]


@respx.mock
def test_server_error_retried_then_raises(notifier: DiscordNotifier) -> None:
    route = respx.post(WEBHOOK).respond(502)
    with pytest.raises(NotificationError, match="HTTP 502"):
        notifier.send(sample())
    assert route.call_count == 3


@respx.mock
def test_client_error_not_retried(notifier: DiscordNotifier) -> None:
    route = respx.post(WEBHOOK).respond(404, json={"message": "Unknown Webhook"})
    with pytest.raises(NotificationError, match="HTTP 404") as exc:
        notifier.send(sample())
    assert route.call_count == 1
    assert "secret-token" not in str(exc.value)


@respx.mock
def test_network_error_hides_webhook_url(notifier: DiscordNotifier) -> None:
    respx.post(WEBHOOK).mock(side_effect=httpx.ConnectError(f"cannot reach {WEBHOOK}"))
    with pytest.raises(NotificationError) as exc:
        notifier.send(sample())
    assert "secret-token" not in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://discord.com/api/webhooks/1/x",
        "https://evil.test/api/webhooks/1/x",
        "https://discord.com/not-a-webhook",
    ],
)
def test_rejects_non_discord_webhook_urls(url: str) -> None:
    with pytest.raises(ValueError, match="Discord webhook"):
        DiscordNotifier(url)


def test_accepts_discordapp_and_ptb_hosts() -> None:
    for url in [
        "https://discordapp.com/api/webhooks/1/x",
        "https://ptb.discord.com/api/webhooks/1/x",
    ]:
        DiscordNotifier(url).close()


@respx.mock
def test_relay_receives_webhook_path() -> None:
    route = respx.post("https://relay.test/api/webhooks/123/secret-token").respond(204)
    n = DiscordNotifier(WEBHOOK, relay_url="https://relay.test/")
    n.send(sample())
    n.close()
    assert route.called
    assert body(route)["allowed_mentions"] == {"parse": []}


def test_rejects_non_https_relay() -> None:
    with pytest.raises(ValueError, match="DISCORD_RELAY_URL"):
        DiscordNotifier(WEBHOOK, relay_url="http://relay.test")
