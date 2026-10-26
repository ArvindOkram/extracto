"""Discord webhook notifier. The webhook URL is a secret: never log it or put it in errors."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from extracto.domain.models import Notification, NotificationLevel
from extracto.interfaces import NotificationError

__all__ = ["DiscordNotifier", "NotificationError"]

DISCORD_HOSTS = frozenset(
    {"discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com"}
)
COLORS = {
    NotificationLevel.OK: 0x2ECC71,
    NotificationLevel.WARNING: 0xF1C40F,
    NotificationLevel.ERROR: 0xE74C3C,
}
# https://discord.com/developers/docs/resources/message#embed-object-embed-limits
TITLE_MAX, DESCRIPTION_MAX, FIELDS_MAX = 256, 4096, 25
FIELD_NAME_MAX, FIELD_VALUE_MAX, EMBED_TOTAL_MAX = 256, 1024, 6000
MAX_RETRY_WAIT = 30.0


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DiscordNotifier:
    def __init__(
        self,
        webhook_url: str,
        *,
        username: str = "Extracto",
        relay_url: str | None = None,
        client: httpx.Client | None = None,
        max_attempts: int = 3,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        parts = urlsplit(webhook_url)
        if (
            parts.scheme != "https"
            or parts.hostname not in DISCORD_HOSTS
            or not parts.path.startswith("/api/webhooks/")
        ):
            raise ValueError("DISCORD_WEBHOOK_URL must be a https Discord webhook URL")
        self._url = webhook_url
        if relay_url:
            # Some hosts' shared IPs are blocked by Discord; a relay (e.g. a Cloudflare Worker)
            # receives the same /api/webhooks/... path and forwards it to Discord.
            relay = urlsplit(relay_url)
            if relay.scheme != "https" or not relay.hostname:
                raise ValueError("DISCORD_RELAY_URL must be a https URL")
            query = f"?{parts.query}" if parts.query else ""
            self._url = relay_url.rstrip("/") + parts.path + query
        self._username = username
        self._client = client or httpx.Client(timeout=10)
        self._max_attempts = max_attempts
        self._sleep = sleep or time.sleep

    def close(self) -> None:
        self._client.close()

    def send(self, notification: Notification) -> None:
        payload = self._payload(notification)
        for attempt in range(1, self._max_attempts + 1):
            last = attempt == self._max_attempts
            try:
                response = self._client.post(self._url, json=payload)
            except httpx.HTTPError as exc:
                # Exception text can contain the URL (and its token), so report the type only.
                if last:
                    raise NotificationError(f"Discord unreachable ({type(exc).__name__})") from None
                self._sleep(2.0**attempt)
                continue

            status = response.status_code
            if status < 300:
                return
            if status == 429 and not last:
                self._sleep(min(self._retry_after(response), MAX_RETRY_WAIT))
                continue
            if status >= 500 and not last:
                self._sleep(2.0**attempt)
                continue
            raise NotificationError(f"Discord webhook rejected the message: HTTP {status}")

    def _retry_after(self, response: httpx.Response) -> float:
        try:
            return float(response.json().get("retry_after", 1.0))
        except (ValueError, AttributeError):
            header = response.headers.get("retry-after", "1")
            return float(header) if header.replace(".", "", 1).isdigit() else 1.0

    def _payload(self, n: Notification) -> dict[str, Any]:
        title = _truncate(n.title, TITLE_MAX)
        description = _truncate(n.description, DESCRIPTION_MAX)
        budget = EMBED_TOTAL_MAX - len(title) - len(description)

        fields: list[dict[str, Any]] = []
        for name, value in n.fields[:FIELDS_MAX]:
            name = _truncate(name or "-", FIELD_NAME_MAX)
            value = _truncate(value or "-", FIELD_VALUE_MAX)
            if len(name) + len(value) > budget:
                break
            budget -= len(name) + len(value)
            fields.append({"name": name, "value": value, "inline": False})

        return {
            "username": self._username,
            # Content includes untrusted page text: never let it ping anyone.
            "allowed_mentions": {"parse": []},
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": COLORS[n.level],
                    "fields": fields,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ],
        }
