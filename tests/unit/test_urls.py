import pytest

from extracto.domain.urls import UrlFilter, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://WWW.A.test/Path?b=2&a=1#frag", "https://www.a.test/Path?a=1&b=2"),
        (
            "https://a.test/x?utm_source=x&id=3&gclid=1&fbclid=2&ref=hn&utm_medium=y",
            "https://a.test/x?id=3",
        ),
        ("https://a.test/blog/", "https://a.test/blog/"),  # kept: avoids a redirect per page
        ("https://a.test/blog", "https://a.test/blog"),
        ("https://a.test", "https://a.test/"),
        ("https://a.test/", "https://a.test/"),
        ("http://a.test:80/x", "http://a.test/x"),
        ("https://a.test:443/x", "https://a.test/x"),
        ("https://a.test:8443/x", "https://a.test:8443/x"),
        ("  https://a.test/x  ", "https://a.test/x"),
        ("https://a.test/a b", "https://a.test/a%20b"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_normalize_relative_to_base() -> None:
    assert normalize_url("../b?x=1", base="https://a.test/a/c/") == "https://a.test/a/b?x=1"
    assert normalize_url("#top", base="https://a.test/page") == "https://a.test/page"


@pytest.mark.parametrize(
    "raw", ["mailto:x@a.test", "javascript:void(0)", "tel:123", "", "   ", "data:text/html,hi"]
)
def test_normalize_rejects_non_http(raw: str) -> None:
    assert normalize_url(raw, base="https://a.test/") is None


@pytest.fixture
def url_filter() -> UrlFilter:
    return UrlFilter.build(
        domain="a.test",
        extra_domains=["partner.test"],
        allow_patterns=["^/(pricing|blog)"],
        exclude_patterns=["/login", r"\?page="],
    )


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://a.test/pricing", None),
        ("https://www.a.test/blog/post", None),
        ("https://blog.a.test/blog/x", None),
        ("https://partner.test/pricing", None),
        ("https://evil.test/pricing", "offsite"),
        ("https://xa.test/pricing", "offsite"),
        ("https://a.test/blog/login", "excluded"),
        ("https://a.test/blog?page=2", "excluded"),
        ("https://a.test/careers", "not_allowed"),
        ("https://a.test/blog/brochure.PDF", "junk_extension"),
        ("https://a.test/blog/logo.png", "junk_extension"),
        ("https://a.test/blog/" + "x" * 300, "too_long"),
        ("https://a.test/blog?a=1&b=2&c=3&d=4", "too_many_params"),
        ("https://a.test/blog/1/2/3/4/5/6/7/8/9/10/11", "too_deep"),
    ],
)
def test_filter(url_filter: UrlFilter, url: str, reason: str | None) -> None:
    assert url_filter.reject_reason(url) == reason


def test_filter_can_skip_allow_patterns(url_filter: UrlFilter) -> None:
    # The start URL is always crawled so links can be discovered from it.
    assert url_filter.reject_reason("https://a.test/", check_allow=False) is None
    assert url_filter.reject_reason("https://a.test/login", check_allow=False) == "excluded"


def test_filter_without_allow_patterns_allows_all_paths() -> None:
    f = UrlFilter.build(domain="a.test")
    assert f.reject_reason("https://a.test/anything") is None
