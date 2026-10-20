"""Polite HTTP fetcher: per-site delay with jitter, retries, Retry-After, size and type limits."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from urllib.parse import urljoin, urlsplit

import httpx
from tenacity import RetryCallState, Retrying, retry_if_exception_type

from extracto.config import SiteConfig
from extracto.domain.models import FetchOutcome, FetchResult
from extracto.domain.urls import UrlFilter

log = logging.getLogger(__name__)

JITTER = 0.2  # up to +20% on each delay
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
HTML_TYPES = ("text/html", "application/xhtml+xml")


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP date)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - now).total_seconds())


class _RetryableStatus(Exception):
    def __init__(self, status: int, retry_after: float | None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after


@dataclass
class _Raw:
    status: int
    headers: dict[str, str]
    outcome: FetchOutcome | None = None  # None means redirect
    location: str | None = None
    body: bytes = b""
    encoding: str | None = None
    error: str | None = None


class HttpFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        delay_seconds: float,
        timeout_seconds: float,
        max_bytes: int,
        is_allowed_host: Callable[[str], bool] = lambda _host: True,
        client: httpx.Client | None = None,
        max_redirects: int = 5,
        max_attempts: int = 3,
        max_retry_after: float = 120.0,
        max_delay: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        rand: Callable[[], float] = random.random,
    ) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self.max_bytes = max_bytes
        self._is_allowed_host = is_allowed_host
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._max_redirects = max_redirects
        self._max_attempts = max_attempts
        self._max_retry_after = max_retry_after
        self._max_delay = max_delay
        self._sleep = sleep
        self._clock = clock
        self._rand = rand
        self._last_request: float | None = None

    def __enter__(self) -> HttpFetcher:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        html_only: bool = True,
    ) -> FetchResult:
        start = self._clock()
        headers = {"User-Agent": self.user_agent}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        def result(
            final: str,
            outcome: FetchOutcome,
            *,
            status_code: int | None = None,
            headers: dict[str, str] | None = None,
            body: bytes = b"",
            encoding: str | None = None,
            error: str | None = None,
        ) -> FetchResult:
            return FetchResult(
                url=url,
                final_url=final,
                outcome=outcome,
                status_code=status_code,
                headers=headers or {},
                body=body,
                encoding=encoding,
                duration_ms=int((self._clock() - start) * 1000),
                error=error,
            )

        current = url
        for _ in range(self._max_redirects + 1):
            try:
                raw = self._retrying()(self._send, current, headers, html_only)
            except _RetryableStatus as exc:
                return result(
                    current, FetchOutcome.HTTP_ERROR, status_code=exc.status, error=str(exc)
                )
            except httpx.HTTPError as exc:
                return result(
                    current, FetchOutcome.NETWORK_ERROR, error=f"{type(exc).__name__}: {exc}"
                )

            if raw.outcome is not None:
                return result(
                    current,
                    raw.outcome,
                    status_code=raw.status,
                    headers=raw.headers,
                    body=raw.body,
                    encoding=raw.encoding,
                    error=raw.error,
                )

            assert raw.location is not None
            target = urljoin(current, raw.location)
            parts = urlsplit(target)
            if parts.scheme not in ("http", "https") or not self._is_allowed_host(
                parts.hostname or ""
            ):
                return result(
                    current,
                    FetchOutcome.SKIPPED_OFFSITE_REDIRECT,
                    status_code=raw.status,
                    error=f"redirect to {target}",
                )
            current = target
            headers.pop("If-None-Match", None)  # validators belong to the original URL
            headers.pop("If-Modified-Since", None)

        return result(current, FetchOutcome.HTTP_ERROR, error="too many redirects")

    # -- internals ----------------------------------------------------------------------------

    def _retrying(self) -> Retrying:
        return Retrying(
            retry=retry_if_exception_type((httpx.TransportError, _RetryableStatus)),
            stop=self._should_stop,
            wait=self._wait_seconds,
            sleep=self._sleep,
            reraise=True,
        )

    def _should_stop(self, state: RetryCallState) -> bool:
        if state.attempt_number >= self._max_attempts:
            return True
        exc = state.outcome.exception() if state.outcome else None
        return (
            isinstance(exc, _RetryableStatus)
            and exc.retry_after is not None
            and exc.retry_after > self._max_retry_after
        )

    def _wait_seconds(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, _RetryableStatus) and exc.retry_after is not None:
            return exc.retry_after
        return float(2**state.attempt_number)

    def _wait_politely(self) -> None:
        if self._last_request is None:
            return
        target = self._last_request + self.delay_seconds * (1 + JITTER * self._rand())
        remaining = target - self._clock()
        if remaining > 0:
            self._sleep(remaining)

    def _slow_down(self) -> None:
        self.delay_seconds = min(self.delay_seconds * 2, self._max_delay)
        log.warning("server asked us to slow down", extra={"delay_seconds": self.delay_seconds})

    def _send(self, url: str, headers: dict[str, str], html_only: bool) -> _Raw:
        self._wait_politely()
        try:
            with self._client.stream("GET", url, headers=headers) as resp:
                return self._read(resp, html_only)
        finally:
            self._last_request = self._clock()

    def _read(self, resp: httpx.Response, html_only: bool) -> _Raw:
        status = resp.status_code
        headers = {k.lower(): v for k, v in resp.headers.items()}

        if status in (429, 503):
            self._slow_down()
            raise _RetryableStatus(
                status, parse_retry_after(headers.get("retry-after"), datetime.now(UTC))
            )
        if status >= 500:
            raise _RetryableStatus(status, None)
        if status in REDIRECT_CODES and headers.get("location"):
            return _Raw(status, headers, location=headers["location"])
        if status == 304:
            return _Raw(status, headers, FetchOutcome.NOT_MODIFIED)
        if not 200 <= status < 300:
            return _Raw(status, headers, FetchOutcome.HTTP_ERROR, error=f"HTTP {status}")

        content_type = headers.get("content-type", "").lower()
        if html_only and content_type and not content_type.startswith(HTML_TYPES):
            return _Raw(status, headers, FetchOutcome.SKIPPED_NOT_HTML, error=content_type)

        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            return _Raw(status, headers, FetchOutcome.SKIPPED_TOO_LARGE)

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                return _Raw(status, headers, FetchOutcome.SKIPPED_TOO_LARGE)
            chunks.append(chunk)
        return _Raw(
            status, headers, FetchOutcome.OK, body=b"".join(chunks), encoding=resp.charset_encoding
        )


def fetcher_for_site(
    site: SiteConfig,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpFetcher:
    """A fetcher configured with the site's politeness settings and domain allowlist."""
    domains = UrlFilter.build(domain=site.domain, extra_domains=site.extra_domains)
    return HttpFetcher(
        user_agent=site.user_agent,
        delay_seconds=site.delay_seconds,
        timeout_seconds=site.timeout_seconds,
        max_bytes=site.max_bytes,
        is_allowed_host=domains.on_domain,
        client=client,
        sleep=sleep,
    )
