"""Domain value types shared across layers. Pure Python, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PageStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class PageChange(StrEnum):
    """What a crawl did to a page's stored content."""

    NEW = "new"  # first time this page was saved
    UPDATED = "updated"  # content hash differs from the previous snapshot


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SiteHealth(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"  # not reached before the global run timeout


class ChangeType(StrEnum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    MINOR = "MINOR"
    REMOVED = "REMOVED"


class ChangeCategory(StrEnum):
    PRICING = "pricing"
    PRODUCT = "product"
    BLOG = "blog"
    MESSAGING = "messaging"
    OTHER = "other"
    REMOVED = "removed"


class FeedbackLabel(StrEnum):
    USEFUL = "useful"
    NOISE = "noise"


class FetchOutcome(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"
    HTTP_ERROR = "http_error"
    NETWORK_ERROR = "network_error"
    SKIPPED_ROBOTS = "skipped_robots"
    SKIPPED_TOO_LARGE = "skipped_too_large"
    SKIPPED_NOT_HTML = "skipped_not_html"
    SKIPPED_OFFSITE_REDIRECT = "skipped_offsite_redirect"


@dataclass(frozen=True)
class FetchResult:
    """Outcome of one fetch (after redirects and retries). Never an exception for HTTP errors."""

    url: str
    final_url: str
    outcome: FetchOutcome
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)  # lowercase keys
    body: bytes = b""
    encoding: str | None = None
    duration_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is FetchOutcome.OK

    @property
    def text(self) -> str:
        return self.body.decode(self.encoding or "utf-8", errors="replace")


@dataclass(frozen=True)
class ExtractedPage:
    """Clean content extracted from one HTML page."""

    text: str
    content_hash: str
    short_text: bool
    title: str | None = None
    description: str | None = None
    headings: list[str] = field(default_factory=list)
    published: str | None = None
    links: list[str] = field(default_factory=list)  # absolute, not yet normalized


class NotificationLevel(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class Notification:
    """A channel-agnostic message; notifiers decide how to render it."""

    title: str
    description: str
    level: NotificationLevel = NotificationLevel.OK
    fields: list[tuple[str, str]] = field(default_factory=list)
