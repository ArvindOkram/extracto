from pathlib import Path

import pytest

from extracto.adapters.extractors.trafilatura_extractor import TrafilaturaExtractor
from extracto.domain.text import content_hash

URL = "https://a.test/pricing"
ARTICLE = (Path(__file__).parents[1] / "fixtures" / "pages" / "article.html").read_text("utf-8")


@pytest.fixture
def page():
    return TrafilaturaExtractor(noise_selectors=[".ticker"]).extract(ARTICLE, URL)


def test_main_text_extracted(page) -> None:
    assert "The Pro plan costs $29 per user per month" in page.text
    assert not page.short_text


@pytest.mark.parametrize("marker", ["NAV", "FOOTER", "COOKIE", "SCRIPT", "TICKER"])
def test_boilerplate_removed(page, marker: str) -> None:
    assert f"{marker}_SHOULD_NOT_APPEAR" not in page.text


def test_metadata(page) -> None:
    assert page.title == "Pricing | Competitor A"
    assert page.description == "Simple pricing for teams of every size."
    assert page.published == "2026-10-01"
    assert page.headings == ["Plans and pricing", "Pro plan", "Enterprise plan"]


def test_links_from_full_html_resolved(page) -> None:
    # Nav and footer links count for discovery even though their text is dropped.
    for link in [
        "https://a.test/",
        "https://a.test/pricing",
        "https://a.test/blog/",
        "https://a.test/blog/pricing-update",
        "https://a.test/privacy",
        "https://other.test/partner",
    ]:
        assert link in page.links
    assert not any(link.startswith("mailto:") for link in page.links)


def test_hash_is_of_extracted_text(page) -> None:
    assert page.content_hash == content_hash(page.text)


def test_same_html_same_hash() -> None:
    extractor = TrafilaturaExtractor()
    assert (
        extractor.extract(ARTICLE, URL).content_hash == extractor.extract(ARTICLE, URL).content_hash
    )


def test_noise_selector_changes_do_not_change_hash() -> None:
    extractor = TrafilaturaExtractor(noise_selectors=[".ticker"])
    changed = ARTICLE.replace("1,204 teams", "1,377 teams")
    assert (
        extractor.extract(changed, URL).content_hash == extractor.extract(ARTICLE, URL).content_hash
    )


def test_nearly_empty_page_flagged_short() -> None:
    html = "<html><head><title>App</title></head><body><div id='root'></div></body></html>"
    page = TrafilaturaExtractor().extract(html, URL)
    assert page.short_text
    assert page.title == "App"


def test_malformed_html_does_not_raise() -> None:
    page = TrafilaturaExtractor().extract("<html><body><p>unclosed <b>tags <a href='/x'>x", URL)
    assert "https://a.test/x" in page.links
