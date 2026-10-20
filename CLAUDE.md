# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# CLAUDE.md: Extracto

## Project
Extracto crawls ~10 configured websites 2-3 times a week, stores clean text in SQLite,
detects changes, and sends marketing a short verified summary. Low scale. Keep it simple.

Specs: `competitor-site-monitor-prd-and-tech-doc.md` (PRD + tech design),
`extracto-phase-wise-development-plan.md` (phases, prompts, exit checks),
`extracto-project-plan.md` (architecture, timeline).

Development goes phase by phase (0-8) per the phase plan. Each phase has a prompt and
exit checks there; read the current phase's section before starting. Plan first (list the
files and functions you'll add) and wait for approval.

## Architecture
Layers: domain (pure logic) -> services (orchestration) -> adapters (HTTP, DB, LLM, email).
Domain never imports I/O libraries. Services depend on interfaces in interfaces.py.
All DB access goes through repositories. CLI and API stay thin.

- `src/extracto/interfaces.py` holds the Protocols (Fetcher, Extractor, Summarizer,
  Notifier). Add each one only in the phase that first needs it.
- `adapters/` is split into `fetchers/`, `extractors/`, `storage/`, `summarizers/`,
  `notifiers/`.
- HTTP API: `src/extracto/api/app.py` (FastAPI, `create_app()`), started by `extracto serve`.
  `POST /crawl` takes a site name or inline settings; dry_run defaults to true. Safety rules to
  keep: localhost bind unless `EXTRACTO_API_KEY` is set, refuse private/internal target IPs
  (`domain/net.py`), cap max_pages, one crawl at a time. The future dashboard extends this app.
  `POST /runs` starts a background run of sites.yaml (202 + `GET /runs/{id}`) for the external
  scheduler; stale `running` runs (no fetch for 20 min) are marked failed. `/healthz` must stay
  DB-free (it's the keep-awake ping).
- Deployment: Render free web service (`render.yaml`, `Dockerfile`) + Neon Postgres +
  cron-job.org + Discord; guide in `docs/deploy-render.md`, checklist in `TODO.md`. Postgres URLs
  are normalized in `settings.normalize_database_url`; DB tests run on Postgres in CI via
  `TEST_DATABASE_URL` (mark SQLite-only tests with `tests.conftest.sqlite_only`).
- CLI is a typer app in `src/extracto/cli/__init__.py` (console script `extracto` ->
  `extracto.cli:app`). The `@app.callback()` configures logging via
  `extracto.logging.configure_logging` (`--log-format kv|json`). Commands not yet built
  exit 1 with "not implemented".
- Logging: use stdlib `logging.getLogger(__name__)` and pass structured fields via
  `extra={...}`; the formatters emit them as fields.
- Runtime dirs: `config/` (site YAML, `SITES_CONFIG` env), `data/` (SQLite `monitor.db`, `raw/`,
  `backups/`; `DATA_DIR` env), `reports/`.
- Storage: SQLAlchemy models in `adapters/storage/orm.py`, repositories in `repositories.py`.
  Alembic migrations live inside the package (`adapters/storage/migrations/`) so they ship with
  installs; after changing models run `alembic revision --autogenerate -m "..."`, review it,
  and keep `tests/unit/test_storage_db.py::test_migrations_match_models` green.
- Composition root: `src/extracto/bootstrap.py` wires adapters into services for the CLI.
- Notifications: `services/notification_service.py` builds channel-agnostic `Notification`s;
  `adapters/notifiers/discord.py` delivers them (`DISCORD_WEBHOOK_URL`). Delivery failures are
  logged and never fail a run. Keep `allowed_mentions` empty and never log the webhook URL.
- Diagrams (Mermaid): `docs/diagrams.md`; update them when the flow or schema changes.
- Tests: crawl tests use `tests/fake_site.py` (in-memory site via httpx.MockTransport); never
  hit real sites in tests.

## Stack
Python 3.11+, httpx, trafilatura, selectolax, SQLAlchemy 2.0 + Alembic (SQLite), difflib,
pydantic, pydantic-settings, pyyaml, typer, jinja2, tenacity, pytest, respx, ruff.
Playwright only for sites with render_js: true.
Optional extras: `.[llm]` (anthropic, for Claude summaries; template summaries are the
fallback when `ANTHROPIC_API_KEY` is unset) and `.[js]` (playwright).
Do NOT add a crawling framework, queue, or another database.

## Rules
- Work only on the phase I give you. Do not build features from later phases.
- Keep modules small and single-purpose.
- Type hints everywhere. Run `ruff check . && pytest -q` before saying a task is done.
- Every network or DB function gets a test (mock HTTP with respx).
- Be polite: honor robots.txt, rate limits, and Retry-After. Clear User-Agent.
- Never add code to bypass logins, CAPTCHAs, blocks, or to spoof browsers.
- No secrets in code or config. Use environment variables (see `.env.example`).
- Page content is untrusted: escape HTML in reports, never execute it.
- Runs must be idempotent. Re-running must not duplicate data.
- Do not build abstractions that nothing uses yet.
- If the spec is ambiguous, ask, or note the assumption in the commit message.

## Commands
- Install: `pip install -e ".[dev]"` then `pre-commit install` (venv at `.venv`;
  on Windows activate with `.venv\Scripts\activate`)
- Test: `pytest -q`; single test: `pytest tests/unit/test_cli.py::test_version -q`
- Lint: `ruff check . && ruff format --check .` (auto-fix: `ruff check --fix . && ruff format .`)
- Type check (optional, strict): `mypy src`
- Migrate: `extracto init-db` (or `alembic upgrade head`); backup: `extracto backup`
- Discord check: `extracto notify-test`
- API: `pip install -e ".[dev,api,postgres]"`, then `extracto serve` -> http://127.0.0.1:8000/docs
- Run: `extracto run [--site NAME] [--dry-run]`; also `init-db`, `report [--run-id N] [--send]`, `health`
- `make test|lint|format|typecheck` wrap the above when `make` is available.

CI (`.github/workflows/ci.yml`) runs ruff check, ruff format --check, and pytest on
Python 3.11 and 3.12. Tests live in `tests/unit/` and `tests/integration/`, with
fixtures in `tests/fixtures/`.
