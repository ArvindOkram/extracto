from extracto.domain.text import content_hash, is_short_text, normalize_text, strip_cookie_lines


def test_normalize_text() -> None:
    assert normalize_text("  a   b \n\n\n  c  \r\n\td ") == "a b\nc\nd"
    assert normalize_text("ﬁne") == "fine"  # NFKC ligature


def test_strip_cookie_lines() -> None:
    text = "\n".join(
        [
            "Pricing plans for teams",
            "We use cookies to improve your experience. Accept all cookies",
            "Read our Cookie Policy",
            "Pro plan costs $29 per month",
        ]
    )
    assert strip_cookie_lines(text) == "Pricing plans for teams\nPro plan costs $29 per month"


def test_long_paragraph_mentioning_cookies_is_kept() -> None:
    para = "Our recipe blog is about cookies. " * 20
    assert strip_cookie_lines(para) == para


def test_hash_ignores_dynamic_noise() -> None:
    a = "Updated October 14, 2026 at 10:32 am. 1,234 views. Posted 3 hours ago. Price $29"
    b = "Updated October 15, 2026 at 9:01 PM. 1,240 views. Posted 5 hours ago. Price $29"
    assert content_hash(a) == content_hash(b)


def test_hash_ignores_numeric_dates_and_last_updated() -> None:
    a = "Last updated: 2026-10-14\nPlan details 14/10/2026"
    b = "Last updated: 2026-10-19\nPlan details 19/10/2026"
    assert content_hash(a) == content_hash(b)


def test_hash_detects_real_changes() -> None:
    assert content_hash("Pro plan $29") != content_hash("Pro plan $39")
    assert content_hash("New feature: AI") != content_hash("New feature: Search")


def test_hash_ignores_whitespace_and_is_sha256() -> None:
    h = content_hash("a  b\n\n c")
    assert h == content_hash("a b\nc")
    assert len(h) == 64


def test_is_short_text() -> None:
    assert is_short_text("x" * 199)
    assert not is_short_text("x" * 200)
