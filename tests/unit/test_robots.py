from extracto.domain.robots import RobotsRules

UA = "Extracto/0.1 (contact: me@x.test)"
START = "https://a.test/"

ROBOTS = """
User-agent: *
Disallow: /private
Crawl-delay: 5

User-agent: Extracto
Disallow: /blog/drafts
Crawl-delay: 4

Sitemap: https://a.test/sitemap.xml
Sitemap: https://a.test/sitemap-blog.xml
"""


def test_specific_agent_group_applies() -> None:
    rules = RobotsRules.from_response(200, ROBOTS, START)
    assert rules.can_fetch("https://a.test/pricing", UA)
    assert not rules.can_fetch("https://a.test/blog/drafts/x", UA)
    assert rules.crawl_delay(UA) == 4


def test_wildcard_group_applies_to_other_agents() -> None:
    rules = RobotsRules.from_response(200, ROBOTS, START)
    assert not rules.can_fetch("https://a.test/private/x", "OtherBot/1.0")
    assert rules.crawl_delay("OtherBot/1.0") == 5


def test_sitemaps_listed() -> None:
    rules = RobotsRules.from_response(200, ROBOTS, START)
    assert rules.sitemaps == ["https://a.test/sitemap.xml", "https://a.test/sitemap-blog.xml"]


def test_missing_robots_allows_all() -> None:
    rules = RobotsRules.from_response(404, "", START)
    assert rules.can_fetch("https://a.test/anything", UA)
    assert rules.crawl_delay(UA) is None


def test_forbidden_robots_disallows_all() -> None:
    rules = RobotsRules.from_response(403, "", START)
    assert not rules.can_fetch("https://a.test/", UA)


def test_unreachable_robots_allows_only_start_url() -> None:
    for status in (None, 500, 503):
        rules = RobotsRules.from_response(status, "", START)
        assert rules.can_fetch(START, UA)
        assert not rules.can_fetch("https://a.test/pricing", UA)


def test_wildcards_and_end_anchor() -> None:
    robots = "User-agent: *\nDisallow: */exercise-videos/\nDisallow: /*.pdf$\n"
    rules = RobotsRules.from_response(200, robots, START)
    assert not rules.can_fetch("https://a.test/fitness/exercise-videos/squat", UA)
    assert not rules.can_fetch("https://a.test/files/brochure.pdf", UA)
    assert rules.can_fetch("https://a.test/files/brochure.pdf?v=2", UA)  # $ anchors the end
    assert rules.can_fetch("https://a.test/fitness/plans", UA)


def test_longest_match_wins_and_allow_wins_ties() -> None:
    robots = "User-agent: *\nDisallow: /blog\nAllow: /blog/public\nAllow: /shop\nDisallow: /shop\n"
    rules = RobotsRules.from_response(200, robots, START)
    assert not rules.can_fetch("https://a.test/blog/drafts", UA)
    assert rules.can_fetch("https://a.test/blog/public/post", UA)  # longer allow beats disallow
    assert rules.can_fetch("https://a.test/shop", UA)  # equal length: allow wins


def test_groups_for_same_agent_are_combined_and_comments_ignored() -> None:
    robots = (
        "User-agent: extracto  # us\nDisallow: /a\n\n"
        "User-agent: Other\nUser-agent: EXTRACTO\nDisallow: /b\n"
    )
    rules = RobotsRules.from_response(200, robots, START)
    assert not rules.can_fetch("https://a.test/a", UA)
    assert not rules.can_fetch("https://a.test/b", UA)
    assert rules.can_fetch("https://a.test/c", UA)


def test_empty_disallow_allows_everything_and_robots_txt_always_allowed() -> None:
    rules = RobotsRules.from_response(200, "User-agent: *\nDisallow:\n", START)
    assert rules.can_fetch("https://a.test/anything", UA)
    rules = RobotsRules.from_response(200, "User-agent: *\nDisallow: /\n", START)
    assert not rules.can_fetch("https://a.test/pricing", UA)
    assert rules.can_fetch("https://a.test/robots.txt", UA)
