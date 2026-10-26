"""Protocols that services depend on. Each is added in the phase that first needs it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from extracto.domain.models import ExtractedPage, FetchResult, Notification


class Fetcher(Protocol):
    delay_seconds: float

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        html_only: bool = True,
        max_bytes: int | None = None,
        can_follow: Callable[[str], bool] | None = None,
    ) -> FetchResult: ...

    def close(self) -> None: ...


class Extractor(Protocol):
    def extract(self, html: str, url: str) -> ExtractedPage: ...


class NotificationError(Exception):
    """A notifier couldn't deliver a message. Never contains secrets such as webhook URLs."""


class Notifier(Protocol):
    def send(self, notification: Notification) -> None:
        """Deliver the notification or raise NotificationError."""
        ...
