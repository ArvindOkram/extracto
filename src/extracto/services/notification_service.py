"""Turn run results into channel-agnostic notifications."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from extracto.domain.models import Notification, NotificationLevel
from extracto.interfaces import NotificationError, Notifier
from extracto.services.crawl_service import PageResult, SiteCrawlResult
from extracto.services.run_service import RunOutcome

log = logging.getLogger(__name__)

MAX_LISTED = 5  # per change type, per site
FIELD_BUDGET = 1000  # Discord caps a field value at 1024 characters
TITLE_MAX = 80
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]()#])")


def deliver(notifier: Notifier | None, notification: Notification) -> str | None:
    """Send if a notifier is configured. Returns an error message instead of raising."""
    if notifier is None:
        return None
    try:
        notifier.send(notification)
    except NotificationError as exc:
        log.warning("notification failed", extra={"error": str(exc)})
        return str(exc)
    return None


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _escape(text: str) -> str:
    """Neutralize Markdown in untrusted page text (no fake links, bold, or code)."""
    text = " ".join(text.split())
    if len(text) > TITLE_MAX:
        text = text[: TITLE_MAX - 1] + "…"
    return _MARKDOWN.sub(r"\\\1", text)


def _link(page: PageResult) -> str:
    label = _escape(page.title or urlsplit(page.url).path or page.url)
    url = page.url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
    return f"[{label}]({url})"


def _site_value(result: SiteCrawlResult) -> str:
    stats = [_count(result.pages_crawled, "page"), _count(result.errors, "error")]
    if result.skipped_robots:
        stats.append(f"{result.skipped_robots} skipped by robots.txt")
    stats.append(f"{result.duration_s:.1f}s")
    lines = [" · ".join(stats)]

    if result.baseline:
        lines.append(f"Baseline saved: {_count(len(result.new_pages), 'page')} (first crawl)")
        return "\n".join(lines)
    if not result.new_pages and not result.updated_pages:
        lines.append("No changes")
        return "\n".join(lines)

    budget = FIELD_BUDGET - len(lines[0])
    for icon, label, pages in (
        ("🆕", "new", result.new_pages),
        ("✏️", "updated", result.updated_pages),
    ):
        shown = 0
        for page in pages[:MAX_LISTED]:
            line = f"{icon} {_link(page)}"
            if len(line) + 40 > budget:  # keep room for the "+N more" line
                break
            lines.append(line)
            budget -= len(line) + 1
            shown += 1
        if len(pages) > shown:
            more = f"+{len(pages) - shown} more {label}"
            lines.append(more)
            budget -= len(more) + 1
    return "\n".join(lines)


def run_summary(outcome: RunOutcome) -> Notification:
    results = outcome.results
    errors = sum(r.errors for r in results)
    changed = [r for r in results if not r.baseline]
    parts = [
        _count(len(results), "site"),
        _count(sum(r.pages_crawled for r in results), "page"),
    ]
    baselines = len(results) - len(changed)
    if baselines:
        parts.append(f"{baselines} baseline")
    parts += [
        f"{sum(len(r.new_pages) for r in changed)} new",
        f"{sum(len(r.updated_pages) for r in changed)} updated",
        _count(errors, "error"),
    ]
    return Notification(
        title=f"Extracto run #{outcome.run_id} completed",
        description=" · ".join(parts),
        level=NotificationLevel.WARNING if errors else NotificationLevel.OK,
        fields=[(r.site, _site_value(r)) for r in results],
    )


def run_failed(error: BaseException, run_id: int | None = None) -> Notification:
    label = f"run #{run_id}" if run_id is not None else "run"
    return Notification(
        title=f"Extracto {label} failed",
        description=f"{type(error).__name__}: {error}",
        level=NotificationLevel.ERROR,
    )


def run_interrupted(
    run_id: int, *, sites_done: int, total_sites: int | None, pages: int
) -> Notification:
    """A run that stopped without finishing (the host restarted or slept mid-run)."""
    of_total = f" of {total_sites}" if total_sites is not None else ""
    return Notification(
        title=f"Extracto run #{run_id} was interrupted",
        description=(
            f"It stopped after {sites_done}{of_total} sites ({_count(pages, 'page')}): the app "
            "restarted or went to sleep. Pages crawled so far are saved. "
            "Start a new run with POST /runs."
        ),
        level=NotificationLevel.ERROR,
    )


def connectivity_check() -> Notification:
    return Notification(
        title="Extracto test notification",
        description="If you can read this, Discord notifications are working.",
    )
