from extracto.domain.models import FetchOutcome, NotificationLevel, PageChange
from extracto.services.crawl_service import PageResult, SiteCrawlResult
from extracto.services.notification_service import run_failed, run_summary
from extracto.services.run_service import RunOutcome


def page(path: str, change: PageChange | None = None, title: str | None = None) -> PageResult:
    return PageResult(
        url=f"https://a.test/{path}",
        outcome=FetchOutcome.OK,
        title=title if title is not None else path.title(),
        new_snapshot=change is not None,
        change=change,
    )


def site(
    name: str,
    pages: list[PageResult],
    *,
    errors: int = 0,
    skipped: int = 0,
    baseline: bool = False,
) -> SiteCrawlResult:
    failed = [
        PageResult(url=f"https://a.test/err{i}", outcome=FetchOutcome.HTTP_ERROR)
        for i in range(errors)
    ]
    return SiteCrawlResult(
        site=name,
        pages=pages + failed,
        skipped_robots=skipped,
        duration_s=12.34,
        baseline=baseline,
    )


def test_summary_lists_new_and_updated_pages() -> None:
    a = site(
        "A",
        [
            page("home"),
            page("pricing", PageChange.UPDATED),
            page("ai", PageChange.NEW, "AI Assistant"),
        ],
    )
    b = site("B", [page("x"), page("y")], skipped=1)
    n = run_summary(RunOutcome(run_id=7, results=[a, b]))

    assert n.title == "Extracto run #7 completed"
    assert n.level is NotificationLevel.OK
    assert n.description == "2 sites · 5 pages · 1 new · 1 updated · 0 errors"
    assert n.fields[0] == (
        "A",
        "3 pages · 0 errors · 12.3s\n"
        "🆕 [AI Assistant](https://a.test/ai)\n"
        "✏️ [Pricing](https://a.test/pricing)",
    )
    assert n.fields[1] == ("B", "2 pages · 0 errors · 1 skipped by robots.txt · 12.3s\nNo changes")


def test_first_crawl_reported_as_baseline_not_as_new_pages() -> None:
    pages = [page(f"p{i}", PageChange.NEW) for i in range(40)]
    n = run_summary(RunOutcome(run_id=1, results=[site("A", pages, baseline=True)]))

    assert n.description == "1 site · 40 pages · 1 baseline · 0 new · 0 updated · 0 errors"
    assert n.fields[0][1].endswith("Baseline saved: 40 pages (first crawl)")
    assert "🆕" not in n.fields[0][1]


def test_long_change_lists_are_capped() -> None:
    pages = [page(f"new{i}", PageChange.NEW) for i in range(12)]
    pages += [page(f"upd{i}", PageChange.UPDATED) for i in range(9)]
    value = run_summary(RunOutcome(run_id=1, results=[site("A", pages)])).fields[0][1]

    assert value.count("🆕") == 5 and value.count("✏️") == 5
    assert "+7 more new" in value and "+4 more updated" in value
    assert len(value) <= 1024


def test_titles_are_escaped_and_urls_safe() -> None:
    evil = page("x(1)", PageChange.UPDATED, title="[Click](https://phish.test) **now** @everyone")
    value = run_summary(RunOutcome(run_id=1, results=[site("A", [evil])])).fields[0][1]

    assert "](https://phish.test)" not in value
    assert "\\[Click\\]" in value and "\\*\\*now\\*\\*" in value
    assert "(https://a.test/x%281%29)" in value


def test_missing_title_falls_back_to_url_path() -> None:
    untitled = page("pricing/pro", PageChange.UPDATED, title="")
    value = run_summary(RunOutcome(run_id=1, results=[site("A", [untitled])])).fields[0][1]
    assert "[/pricing/pro](https://a.test/pricing/pro)" in value


def test_errors_raise_level_to_warning() -> None:
    n = run_summary(RunOutcome(run_id=1, results=[site("A", [page("x")], errors=2)]))
    assert n.level is NotificationLevel.WARNING
    assert "2 errors" in n.description


def test_singular_wording() -> None:
    n = run_summary(RunOutcome(run_id=1, results=[site("A", [], errors=1)]))
    assert n.description == "1 site · 1 page · 0 new · 0 updated · 1 error"


def test_failed_run() -> None:
    n = run_failed(RuntimeError("database is locked"), run_id=3)
    assert n.title == "Extracto run #3 failed"
    assert n.level is NotificationLevel.ERROR
    assert "RuntimeError: database is locked" in n.description


def test_failed_run_without_id() -> None:
    assert run_failed(ValueError("x")).title == "Extracto run failed"
