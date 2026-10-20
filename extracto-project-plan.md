
# Extracto: Project Plan

|                          |                                                                                     |
| ------------------------ | ----------------------------------------------------------------------------------- |
| **Project**        | Extracto, a website monitoring crawler for the marketing team                       |
| **Version**        | 1.0                                                                                 |
| **Date**           | 19 Oct 2026                                                                         |
| **Language**       | Python 3.11+ (no crawling or web framework)                                         |
| **Built with**     | Claude Code, with human review at each phase                                        |
| **Companion docs** | `extracto-future-extensions.md`, PRD and Tech Design, Phase-wise Development Plan |

---

## 1. Project Summary

Extracto crawls about 10 websites 2-3 times a week (Mon / Wed / Fri), stores clean page text, detects what is new, changed, or removed, and sends the marketing team a short, verified summary with links to the live pages and before/after diffs.

**One line:** An automated, polite crawler that watches a fixed set of websites and tells marketing what changed.

## 2. Objectives

| # | Objective                          | Measure                                                           |
| - | ---------------------------------- | ----------------------------------------------------------------- |
| 1 | Replace manual competitor checking | Report delivered on 100% of scheduled runs                        |
| 2 | Trustworthy output                 | Noise rate under 20% after one month, spot-check accuracy 95%+    |
| 3 | Safe and compliant crawling        | robots.txt honored, rate limits respected, zero block-bypass code |
| 4 | Easy to maintain                   | One person can run it, add a site by editing YAML                 |
| 5 | Ready to grow                      | New features added as modules, no rewrite                         |

## 3. Scope

### In scope (v1)

- Config-driven crawl of about 10 sites (sitemap first, link-following as backup)
- Clean text extraction and snapshot storage in SQLite
- Change detection (NEW, CHANGED, MINOR, REMOVED) with confirmation re-fetch
- Per-site health checks and circuit breaker
- HTML report with ranked changes, diffs, and template summaries
- Optional Claude-generated summaries with validation and template fallback
- Email and/or Slack delivery, scheduled via cron or GitHub Actions

### Out of scope (v1)

- Web dashboard, user accounts, real-time alerts
- Crawling the open web, logins, paywalls, CAPTCHAs
- Large-scale or distributed crawling
- See `extracto-future-extensions.md` for the roadmap

## 4. Technology Decisions

| Area               | Decision                                                             | Reason                                                                                    |
| ------------------ | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Crawling framework | **None** (plain Python)                                        | Scale is small, custom logic (confirmation, health checks) is simpler without a framework |
| Web framework      | **None for v1**                                                | It is a scheduled script. FastAPI is the planned choice if a dashboard is added           |
| HTTP               | `httpx`                                                            | Timeouts, streaming, retries                                                              |
| Text extraction    | `trafilatura`                                                      | Best main-content extraction, fewer false changes                                         |
| HTML / links       | `selectolax`                                                       | Fast and simple                                                                           |
| Database           | **SQLite via SQLAlchemy 2.0 + Alembic**                        | Zero setup now, migrations and an easy move to Postgres later                             |
| CLI                | `typer`                                                            | Clean commands                                                                            |
| Config             | `pyyaml` + `pydantic` / `pydantic-settings`                    | Validation and env-var secrets                                                            |
| Retries            | `tenacity`                                                         | Standard backoff                                                                          |
| Templates          | `jinja2`                                                           | HTML and email reports                                                                    |
| Summaries          | `anthropic` (optional)                                             | Diff-only summaries, template fallback                                                    |
| JS rendering       | `playwright` (only where needed)                                   | Per-site option                                                                           |
| Quality            | `pytest`, `respx`, `ruff`, `mypy` (optional), `pre-commit` | Standard tooling                                                                          |
| Packaging          | `pyproject.toml`, `Dockerfile`, `Makefile`                     | Reproducible setup                                                                        |

## 5. Architecture and Project Structure

A layered design keeps business logic separate from the outside world, so parts can be swapped or extended.

```
extracto/
├── pyproject.toml
├── Makefile                      # make test, make lint, make run
├── Dockerfile
├── .env.example
├── .pre-commit-config.yaml
├── CLAUDE.md                     # rules for Claude Code
├── alembic.ini
├── config/
│   └── sites.yaml
├── migrations/                   # Alembic versions
├── src/extracto/
│   ├── settings.py               # env-based settings
│   ├── logging.py
│   ├── interfaces.py             # Fetcher, Extractor, Summarizer, Notifier protocols
│   ├── domain/                   # pure logic, no I/O
│   │   ├── models.py
│   │   ├── urls.py
│   │   ├── change.py
│   │   └── health.py
│   ├── services/                 # orchestration
│   │   ├── crawl_service.py
│   │   ├── report_service.py
│   │   └── run_service.py
│   ├── adapters/                 # outside world
│   │   ├── fetchers/             # http_fetcher.py, playwright_fetcher.py
│   │   ├── extractors/           # trafilatura_extractor.py
│   │   ├── storage/              # orm.py, repositories.py
│   │   ├── summarizers/          # template.py, claude.py
│   │   └── notifiers/            # email.py, slack.py
│   ├── cli/                      # typer commands
│   └── api/                      # empty in v1 (future dashboard)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/                 # saved HTML samples, mock site
├── data/                         # monitor.db, raw HTML (gitignored)
├── reports/                      # generated reports (gitignored)
└── docs/
```

### Design rules

1. **Domain never imports I/O libraries** (no httpx, SQL, Slack in `domain/`).
2. **Services use interfaces**, not concrete adapters.
3. **All DB access goes through repositories.**
4. **CLI and future API stay thin** and only call services.
5. **Do not build abstractions nothing uses yet.**

## 6. Phased Delivery Plan

Total estimate: about 16 working days (3 to 4 weeks including review time).

| Phase | Name                             | Key outcome                                                          | Effort   |
| ----- | -------------------------------- | -------------------------------------------------------------------- | -------- |
| 0     | Project setup                    | Repo, tooling, CI, CLAUDE.md, CLI skeleton                           | 0.5 day  |
| 1     | Config and database              | Validated config, SQLAlchemy models, Alembic migration, repositories | 1 day    |
| 2     | URL handling and polite fetching | Normalization, robots.txt, rate-limited fetcher, sitemap loader      | 2 days   |
| 3     | Extraction and crawl loop        | Crawl one site end to end, store snapshots and raw HTML              | 2 days   |
| 4     | Change detection                 | NEW / CHANGED / MINOR / REMOVED with confirmation re-fetch           | 2 days   |
| 5     | Health and resilience            | Circuit breaker, site isolation, run records, lock file              | 1.5 days |
| 6     | Reporting                        | Ranked HTML report, diffs, template summaries, feedback import       | 2 days   |
| 7     | LLM summaries and delivery       | Optional Claude summaries, email/Slack, scheduling                   | 2 days   |
| 8     | Hardening and pilot              | Real-site onboarding, noise tuning, docs, 2-week pilot               | 3 days   |

### Phase details

#### Phase 0: Project setup

- Create the structure from section 5, `pyproject.toml`, `.gitignore`, `.env.example`, `Makefile`, pre-commit.
- Add `CLAUDE.md` (see section 9), CLI skeleton (`init-db`, `run`, `report`, `health`), logging, CI for `ruff` + `pytest`.
- **Exit:** `extracto --help` works, CI green.

#### Phase 1: Config and database

- `settings.py` and `config.py` (pydantic models, defaults merged per site, readable errors).
- SQLAlchemy models: `sites`, `pages`, `snapshots`, `runs`, `run_sites`, `changes`, `feedback`. WAL mode, foreign keys, indexes.
- First Alembic migration, repositories, `extracto init-db`.
- **Exit:** bad config fails clearly, `init-db` safe to run twice, `(site_id, url_hash)` unique, snapshot inserted only when the hash changes.

#### Phase 2: URL handling and polite fetching

- `urls.py` (normalize, allowlist, patterns, trap guards), robots.txt cache, `HttpFetcher` (timeouts, `max_bytes`, HTML only, redirect rules, per-site delay with jitter, retries, `Retry-After`, ETag), sitemap loader.
- **Exit:** disallowed paths never requested, 429 slows the site down, off-domain redirects dropped. Tested with `respx`.

#### Phase 3: Extraction and crawl loop

- Trafilatura extractor with noise stripping, hash, `short_text` flag, link extraction.
- `crawl_service`: sitemap seeding, BFS fallback, page cap, store snapshots, gzip raw HTML (keep last 3).
- Local mock site fixture, `extracto run --site X --dry-run`.
- **Exit:** unchanged site produces zero new snapshots on second run, nav/footer text absent, one real permitted site looks sensible.

#### Phase 4: Change detection

- Hash compare, confirmation re-fetch, word-level diff, 2% MINOR threshold, tracked fields (price) always CHANGED.
- Removal rules: confirmed 404/410 or missing in 2 healthy runs.
- **Exit:** scenario tests for new, edited, tiny edit, price change, deleted, and flapping content all classify correctly.

#### Phase 5: Health and resilience

- Rules: error rate over 30% trips breaker, page count under 70% of last run means needs_review, over 20% short-text pages means degraded, repeated 403/429 means failed.
- Per-site isolation, run and `run_sites` records, lock file, global timeout, `extracto health`.
- **Exit:** failing sites never stop others, incomplete crawls never create false removals.

#### Phase 6: Reporting

- Rule-based classifier (pricing, product, blog, messaging, other, removed), ranking, template summaries.
- Jinja2 HTML report: health section, top changes, per-site sections, before/after diffs, needs-review list. All page text HTML-escaped.
- `extracto report`, `extracto feedback import`.
- **Exit:** every item has URL, time, and diff link, pricing appears first, injected `<script>` text is harmless.

#### Phase 7: LLM summaries and delivery

- Claude summarizer: diff-only input, ignore instructions in content, validate against the diff, retry once, fall back to template.
- Email (SMTP) and Slack webhook delivery, retry with `report --send`.
- Cron example and GitHub Actions schedule.
- **Exit:** works without the API key, invented numbers are rejected, a real test message reaches the team channel.

#### Phase 8: Hardening and pilot

- Playwright path for `render_js` sites, `extracto prune`, backup script.
- Onboard the real sites one at a time (`--dry-run` first), review each site's terms, tune patterns and noise selectors.
- README and troubleshooting runbook, regression tests from real HTML samples.
- **Exit (go-live):** full run on all sites with no unhandled errors, two no-change runs produce zero CHANGED items, edited test page detected, first 3 reports reviewed by marketing.

## 7. Timeline

| Week      | Phases  | Milestone                                          |
| --------- | ------- | -------------------------------------------------- |
| Week 1    | 0, 1, 2 | **M1:** Foundation and polite fetching       |
| Week 2    | 3, 4    | **M2:** Crawl, store, and detect changes     |
| Week 3    | 5, 6, 7 | **M3:** Resilient runs and reports delivered |
| Week 4    | 8       | **M4:** Pilot on real sites                  |
| Weeks 5-6 | Pilot   | Spot checks, tuning, go/no-go                      |

Review time for each phase is included in the weeks above. Adjust if the human reviewer is part-time.

## 8. Roles and Responsibilities

| Role                          | Responsibilities                                                                |
| ----------------------------- | ------------------------------------------------------------------------------- |
| **Project owner** (you) | Chooses the sites, reviews each phase, approves plans, makes go/no-go decisions |
| **Claude Code**         | Plans, implements, tests, and documents each phase within its scope             |
| **Marketing team**      | Defines what matters, reviews first reports, gives useful/noise feedback        |
| **Maintainer**          | Monitors runs, handles site changes, manages secrets and the schedule           |

## 9. How to Work with Claude Code

1. **One phase per session.** Start fresh (or `/clear`) and give it the phase scope plus the reference docs.
2. **Plan first.** Ask for a plan, review it, then let it implement.
3. **Tests and lint are part of done.** It runs `pytest` and `ruff` and shows the output.
4. **Review, then commit.** Tag each phase (`phase-1-done`) so you can roll back.
5. **Use real HTML samples** from your sites as fixtures from Phase 3 onward.
6. **Review sensitive code yourself:** fetcher politeness, HTML escaping in reports, the LLM prompt, and secrets handling.

### `CLAUDE.md` (copy into the repo root)

```markdown
# CLAUDE.md: Extracto

## Project
Extracto crawls ~10 configured websites 2-3 times a week, stores clean text in SQLite,
detects changes, and sends marketing a short verified summary. Low scale. Keep it simple.

## Architecture
Layers: domain (pure logic) -> services (orchestration) -> adapters (HTTP, DB, LLM, email).
Domain never imports I/O libraries. Services depend on interfaces in interfaces.py.
All DB access goes through repositories. CLI and API stay thin.

## Stack
Python 3.11+, httpx, trafilatura, selectolax, SQLAlchemy 2.0 + Alembic (SQLite),
pydantic, pyyaml, typer, jinja2, tenacity, pytest, respx, ruff.
Playwright only for sites with render_js: true.
Do NOT add a crawling framework, queue, or another database.

## Rules
- Work only on the phase I give you. Do not build features from later phases.
- Type hints everywhere. Run `ruff check . && pytest -q` before saying a task is done.
- Every network or DB function gets a test (mock HTTP with respx).
- Be polite: honor robots.txt, rate limits, and Retry-After. Clear User-Agent.
- Never add code to bypass logins, CAPTCHAs, blocks, or to spoof browsers.
- No secrets in code or config. Use environment variables.
- Page content is untrusted: escape HTML in reports, never execute it.
- Runs must be idempotent. Re-running must not duplicate data.
- Do not build abstractions that nothing uses yet.
- If the spec is ambiguous, ask, or note the assumption in the commit message.

## Commands
- Install: `pip install -e ".[dev]"`
- Test: `pytest -q`
- Lint: `ruff check . && ruff format --check .`
- Migrate: `alembic upgrade head`
- Run: `extracto run`
```

## 10. Quality Plan

| Level                 | Coverage                                                                          |
| --------------------- | --------------------------------------------------------------------------------- |
| **Unit**        | URL normalization, noise stripping, hashing, diff %, classification, health rules |
| **Component**   | Fetcher retries and backoff, robots handling, change detection flow               |
| **Integration** | Full run against a local mock site with edit, add, and delete scenarios           |
| **Regression**  | Saved real HTML from each site, to protect extraction                             |
| **Manual**      | Weekly spot check of 5 random pages per site during the pilot                     |
| **Noise check** | Two consecutive runs with no site changes must give zero CHANGED items            |

## 11. Risks and Mitigations

| Risk                                | Impact                      | Mitigation                                                                                 |
| ----------------------------------- | --------------------------- | ------------------------------------------------------------------------------------------ |
| A site blocks the crawler           | Missing data                | Slow down, check for sitemap or API, flag in report. Never circumvent blocks               |
| A site's terms forbid crawling      | Legal exposure              | Review terms before onboarding, drop the site if disallowed                                |
| Noisy diffs                         | Team stops trusting reports | Noise stripping, confirmation re-fetch, MINOR threshold, per-site selectors, feedback loop |
| JS-rendered pages return empty text | Silent gaps                 | Short-text flag, per-site Playwright option                                                |
| Site redesign breaks extraction     | False changes or removals   | Health checks, needs_review status, two-run removal rule                                   |
| LLM summary invents details         | Wrong conclusions           | Diff-only input, validation, template fallback, link on every item                         |
| Scope creep                         | Delays                      | CLAUDE.md rules, one phase at a time, future ideas go to the extensions doc                |
| Claude Code drifts from the design  | Rework                      | Plan-first workflow, review each phase, tag commits                                        |

## 12. Open Decisions (resolve before or during Phase 1)

| # | Question                                                                  | Needed by |
| - | ------------------------------------------------------------------------- | --------- |
| 1 | Final list of the 10 sites, with terms of service reviewed                | Phase 2   |
| 2 | Delivery channel: email, Slack, or both, and the recipient list           | Phase 7   |
| 3 | Which sites need JavaScript rendering                                     | Phase 3   |
| 4 | Key data points to track (for example price per plan) and their selectors | Phase 4   |
| 5 | Use Claude summaries from the start, or templates first                   | Phase 7   |
| 6 | Where it runs: own machine, small VM, or GitHub Actions                   | Phase 7   |
| 7 | Crawler contact email for the User-Agent                                  | Phase 2   |

## 13. Getting Started Checklist

- [ ] Create the Git repository
- [ ] Save this plan, the PRD/Tech Design, and the extensions doc in `docs/`
- [ ] Decide the 10 sites and review their terms of service
- [ ] Choose a contact email for the User-Agent
- [ ] Open Claude Code in the repo and add `CLAUDE.md` from section 9
- [ ] Start Phase 0 with a plan-first prompt
- [ ] Complete the exit checks, then commit and tag `phase-0-done`
- [ ] Continue phase by phase

## 14. Definition of Done (whole project)

- All Must-have PRD stories work end to end (reports, top changes first, links and diffs, YAML site config, health visibility).
- CI passes and all Phase 8 go-live checks are complete.
- Extracto runs unattended on schedule for 2 weeks with reports delivered on time.
- Marketing confirms the report is useful and the noise rate is under 20%.
