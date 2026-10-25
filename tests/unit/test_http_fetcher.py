from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx

from extracto.adapters.fetchers.http_fetcher import HttpFetcher, parse_retry_after
from extracto.domain.models import FetchOutcome

UA = "Extracto-test/1.0 (+contact: qa@x.test)"
HTML = {"content-type": "text/html; charset=utf-8"}


class FakeTime:
    """Deterministic clock; sleeping advances it instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def t() -> FakeTime:
    return FakeTime()


@pytest.fixture
def fetcher(t: FakeTime) -> Iterator[HttpFetcher]:
    f = HttpFetcher(
        user_agent=UA,
        delay_seconds=1.0,
        timeout_seconds=5,
        max_bytes=1000,
        is_allowed_host=lambda host: host == "a.test" or host.endswith(".a.test"),
        sleep=t.sleep,
        clock=t.clock,
        rand=lambda: 0.0,
    )
    yield f
    f.close()


@respx.mock
def test_ok_html(fetcher: HttpFetcher) -> None:
    route = respx.get("https://a.test/").respond(200, headers=HTML, text="<p>héllo</p>")
    result = fetcher.fetch("https://a.test/")

    assert result.outcome is FetchOutcome.OK and result.ok
    assert result.status_code == 200
    assert result.final_url == "https://a.test/"
    assert result.text == "<p>héllo</p>"
    assert route.calls.last.request.headers["user-agent"] == UA


@respx.mock
def test_redirect_chain(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/old").respond(301, headers={"location": "/mid"})
    respx.get("https://a.test/mid").respond(302, headers={"location": "https://www.a.test/new"})
    respx.get("https://www.a.test/new").respond(200, headers=HTML, text="new")

    result = fetcher.fetch("https://a.test/old")
    assert result.ok and result.final_url == "https://www.a.test/new"


@respx.mock
def test_offsite_redirect_dropped(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/out").respond(302, headers={"location": "https://evil.test/"})
    evil = respx.get("https://evil.test/").respond(200, headers=HTML, text="x")

    result = fetcher.fetch("https://a.test/out")
    assert result.outcome is FetchOutcome.SKIPPED_OFFSITE_REDIRECT
    assert not evil.called


@respx.mock
def test_redirect_to_disallowed_target_not_followed(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/go").respond(302, headers={"location": "/private/x"})
    private = respx.get("https://a.test/private/x").respond(200, headers=HTML, text="x")

    result = fetcher.fetch("https://a.test/go", can_follow=lambda url: "/private" not in url)
    assert result.outcome is FetchOutcome.SKIPPED_ROBOTS
    assert not private.called


@respx.mock
def test_slow_download_aborted(fetcher: HttpFetcher, t: FakeTime) -> None:
    def trickle():
        for _ in range(5):
            t.now += 60  # each chunk arrives a minute after the last
            yield b"x"

    respx.get("https://a.test/slow").mock(
        return_value=httpx.Response(200, headers=HTML, content=trickle())
    )
    result = fetcher.fetch("https://a.test/slow")
    assert result.outcome is FetchOutcome.NETWORK_ERROR and result.error == "download too slow"


@respx.mock
def test_too_many_redirects(fetcher: HttpFetcher) -> None:
    for i in range(10):
        respx.get(f"https://a.test/r{i}").respond(302, headers={"location": f"/r{i + 1}"})
    result = fetcher.fetch("https://a.test/r0")
    assert result.outcome is FetchOutcome.HTTP_ERROR
    assert "redirect" in (result.error or "")


@respx.mock
def test_404_not_retried(fetcher: HttpFetcher) -> None:
    route = respx.get("https://a.test/gone").respond(404)
    result = fetcher.fetch("https://a.test/gone")
    assert result.outcome is FetchOutcome.HTTP_ERROR and result.status_code == 404
    assert route.call_count == 1


@respx.mock
def test_429_honors_retry_after_and_slows_down(fetcher: HttpFetcher, t: FakeTime) -> None:
    respx.get("https://a.test/").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, headers=HTML, text="ok"),
        ]
    )
    result = fetcher.fetch("https://a.test/")
    assert result.ok
    assert 7 in t.sleeps
    assert fetcher.delay_seconds == 2.0


@respx.mock
def test_503_then_success(fetcher: HttpFetcher, t: FakeTime) -> None:
    route = respx.get("https://a.test/").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, headers=HTML, text="ok")]
    )
    assert fetcher.fetch("https://a.test/").ok
    assert route.call_count == 2
    assert fetcher.delay_seconds == 2.0


@respx.mock
def test_retry_after_too_long_gives_up(fetcher: HttpFetcher, t: FakeTime) -> None:
    route = respx.get("https://a.test/").respond(429, headers={"retry-after": "3600"})
    result = fetcher.fetch("https://a.test/")
    assert result.outcome is FetchOutcome.HTTP_ERROR and result.status_code == 429
    assert route.call_count == 1
    assert max(t.sleeps, default=0) < 3600


@respx.mock
def test_5xx_retried_with_backoff_then_fails(fetcher: HttpFetcher, t: FakeTime) -> None:
    route = respx.get("https://a.test/").respond(500)
    result = fetcher.fetch("https://a.test/")
    assert result.outcome is FetchOutcome.HTTP_ERROR and result.status_code == 500
    assert route.call_count == 3
    assert t.sleeps == [2, 4]
    assert fetcher.delay_seconds == 1.0  # plain 5xx doesn't trigger slow-down


@respx.mock
def test_timeout_retried_then_success(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, headers=HTML, text="ok")]
    )
    assert fetcher.fetch("https://a.test/").ok


@respx.mock
def test_network_error_after_retries(fetcher: HttpFetcher) -> None:
    route = respx.get("https://a.test/").mock(side_effect=httpx.ConnectError("refused"))
    result = fetcher.fetch("https://a.test/")
    assert result.outcome is FetchOutcome.NETWORK_ERROR
    assert result.status_code is None and "refused" in (result.error or "")
    assert route.call_count == 3


@respx.mock
def test_oversized_by_content_length(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/big").respond(200, headers=HTML, content=b"x" * 1001)
    assert fetcher.fetch("https://a.test/big").outcome is FetchOutcome.SKIPPED_TOO_LARGE


@respx.mock
def test_max_bytes_override_per_call(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/big").respond(200, headers=HTML, content=b"x" * 1001)
    result = fetcher.fetch("https://a.test/big", max_bytes=2000)
    assert result.outcome is FetchOutcome.OK and len(result.body) == 1001


@respx.mock
def test_oversized_while_streaming(fetcher: HttpFetcher) -> None:
    chunks = (b"x" * 400 for _ in range(3))  # no content-length header
    respx.get("https://a.test/big").mock(
        return_value=httpx.Response(200, headers=HTML, content=chunks)
    )
    result = fetcher.fetch("https://a.test/big")
    assert result.outcome is FetchOutcome.SKIPPED_TOO_LARGE and result.body == b""


@respx.mock
def test_non_html_skipped_unless_allowed(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/robots.txt").respond(
        200, headers={"content-type": "text/plain"}, text="User-agent: *"
    )
    assert fetcher.fetch("https://a.test/robots.txt").outcome is FetchOutcome.SKIPPED_NOT_HTML
    assert fetcher.fetch("https://a.test/robots.txt", html_only=False).ok


@respx.mock
def test_conditional_request_and_304(fetcher: HttpFetcher) -> None:
    route = respx.get("https://a.test/").respond(304)
    result = fetcher.fetch(
        "https://a.test/", etag='"abc"', last_modified="Wed, 14 Oct 2026 07:00:00 GMT"
    )
    assert result.outcome is FetchOutcome.NOT_MODIFIED
    sent = route.calls.last.request.headers
    assert sent["if-none-match"] == '"abc"'
    assert sent["if-modified-since"] == "Wed, 14 Oct 2026 07:00:00 GMT"


@respx.mock
def test_response_validators_exposed(fetcher: HttpFetcher) -> None:
    respx.get("https://a.test/").respond(
        200, headers={**HTML, "etag": '"v2"', "last-modified": "Thu, 15 Oct 2026 07:00:00 GMT"}
    )
    result = fetcher.fetch("https://a.test/")
    assert result.headers["etag"] == '"v2"'
    assert result.headers["last-modified"] == "Thu, 15 Oct 2026 07:00:00 GMT"


@respx.mock
def test_polite_delay_between_requests(fetcher: HttpFetcher, t: FakeTime) -> None:
    respx.get("https://a.test/").respond(200, headers=HTML, text="ok")
    fetcher.fetch("https://a.test/")
    assert t.sleeps == []  # first request doesn't wait
    fetcher.fetch("https://a.test/")
    assert t.sleeps == [1.0]


@respx.mock
def test_jitter_adds_up_to_20_percent(t: FakeTime) -> None:
    respx.get("https://a.test/").respond(200, headers=HTML, text="ok")
    with HttpFetcher(
        user_agent=UA,
        delay_seconds=1.0,
        timeout_seconds=5,
        max_bytes=1000,
        sleep=t.sleep,
        clock=t.clock,
        rand=lambda: 1.0,
    ) as f:
        f.fetch("https://a.test/")
        f.fetch("https://a.test/")
    assert t.sleeps == [pytest.approx(1.2)]


def test_parse_retry_after() -> None:
    now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("30", now) == 30
    assert parse_retry_after("Tue, 20 Oct 2026 12:01:00 GMT", now) == 60
    assert parse_retry_after("Tue, 20 Oct 2026 11:00:00 GMT", now) == 0
    assert parse_retry_after("soon", now) is None
    assert parse_retry_after(None, now) is None
