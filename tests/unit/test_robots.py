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
