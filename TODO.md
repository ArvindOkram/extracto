# Extracto: TODO

Status as of 20 Oct 2026. Code: storage, crawler (Phases 1–3), Discord notifications, HTTP API
(test crawls, background runs), Postgres support, Render packaging. Tests: 261, all passing locally (the Postgres CI job runs once pushed).
Deploy guide: [`docs/deploy-render.md`](docs/deploy-render.md).

Legend: 🧑 = you (accounts, secrets, decisions) · 🤖 = code work I can do

---

## 1. Verify locally (before deploying)

- [ ] 🧑 Activate the venv and reinstall: `.venv\Scripts\Activate.ps1`, then `pip install -e ".[dev,api,postgres]"`
- [ ] 🧑 Run the tests: `pytest -q` (expect all passing)
- [ ] 🧑 Set a real contact email in `config/sites.yaml` → `defaults.user_agent` (currently `marketing-it@example.com`)
- [ ] 🧑 Dry run: `extracto run --site "Google Search Docs" --dry-run`
- [ ] 🧑 Real run: `extracto run --site "Google Search Docs"`, then confirm `data\monitor.db` exists
- [ ] 🧑 Second real run shows "0 new snapshots" (no false changes)
- [ ] 🧑 Discord locally: set `DISCORD_WEBHOOK_URL` in `.env`, then `extracto notify-test`
- [ ] 🧑 API locally: `extracto serve`, open http://127.0.0.1:8000/docs, try `POST /runs`, then `GET /runs/1`
- [ ] 🧑 Optional: local Docker build, if Docker is installed: `docker build -t extracto .`

## 2. Git and GitHub (Render deploys from GitHub)

- [ ] 🧑 Decide what to commit: all code, plus the planning docs? (`competitor-site-monitor-prd-and-tech-doc.md`, `extracto-phase-wise-development-plan.md`, `extracto-project-plan.md`, `future-plan.md`)
- [ ] 🤖 Create a branch, commit, and open a PR (ask me; nothing is committed yet)
- [ ] 🧑 Create the GitHub repo (private is fine) and push
- [ ] 🧑 Confirm these are **not** in git: `.env`, `config/sites.yaml`, `data/`, which `.gitignore` covers
- [ ] 🧑 Check that GitHub Actions CI is green (both jobs: SQLite tests and the Postgres job)
- [ ] 🧑 Optional: branch protection on `main` requiring CI to pass

## 3. Discord

- [ ] 🧑 Choose the channel for updates
- [ ] 🧑 Edit Channel → Integrations → Webhooks → New Webhook → copy the URL
- [ ] 🧑 Keep the URL secret (it will go into Render only)

## 4. Neon (free Postgres)

- [ ] 🧑 Create a Neon account and project (region near your Render region)
- [ ] 🧑 Copy the **direct** connection string (with `sslmode=require`)
- [ ] 🧑 Optional: test from your machine: put it in `.env` as `DATABASE_URL=...`, run `extracto init-db`, then remove it again
- [ ] 🧑 Note the free storage limit (~0.5 GB) and keep `max_pages` realistic (about 50–150 per site)

## 5. Render (free web service)

- [ ] 🧑 New → Blueprint → select the repo (uses `render.yaml`)
- [ ] 🧑 Paste `DATABASE_URL` and `DISCORD_WEBHOOK_URL` when prompted
- [ ] 🧑 Add the Secret File `sites.yaml` (Environment → Secret Files) with your real site list
- [ ] 🧑 Copy the generated `EXTRACTO_API_KEY` (Environment tab) into a password manager
- [ ] 🧑 Note the service URL (`https://<name>.onrender.com`)
- [ ] 🧑 Verify: `GET /healthz` → `{"status":"ok"}`
- [ ] 🧑 Verify: `POST /notify-test` (with key) → a Discord message arrives
- [ ] 🧑 Verify: `POST /runs` → 202; `GET /runs/{id}` → `completed`; Discord summary arrives

## 6. cron-job.org (free scheduler)

- [ ] 🧑 Create an account; set the job time zone to UTC
- [ ] 🧑 Job 1, keep-awake: `GET https://<app>.onrender.com/healthz`, crontab `*/10 5-9 * * 1,3,5`
- [ ] 🧑 Job 2, start run: `POST https://<app>.onrender.com/runs`, crontab `0 6 * * 1,3,5`, headers `X-API-Key` and `Content-Type: application/json`, body `{}`
- [ ] 🧑 Turn on failure email notifications for Job 2
- [ ] 🧑 Size the keep-awake window: total pages × 3 s must fit inside it
- [ ] 🧑 After the first scheduled day, check: Discord message received, `GET /runs` shows `completed`

## 7. Security checklist

- [ ] 🧑 No secrets in git history (`git log -p | findstr /i "webhooks api_key password"` shows nothing real)
- [ ] 🧑 `EXTRACTO_API_KEY` is long and random (Render's generated value is)
- [ ] 🧑 Discord webhook, Neon password and API key are stored only in Render and your password manager
- [ ] 🧑 Know how to rotate each one (see the deploy guide)
- [ ] 🧑 Each site's terms of service reviewed before adding it to `sites.yaml`
- [ ] 🤖 Hardening: re-check private-IP safety on every request, not just the start URL (currently checked for `/crawl` start URLs only)

## 8. First month in production

- [ ] 🧑 Check the first 3 Discord summaries with marketing: useful vs noise
- [ ] 🧑 Spot-check 5 pages per site: stored text matches the live page
- [ ] 🧑 Tune `exclude_patterns` and `noise_selectors` for noisy sites
- [ ] 🧑 Watch Neon storage usage (dashboard) and Render free hours (750/month)

---

## 9. Development roadmap (🤖 code)

### Phase 4: change detection (next)
- [ ] Confirmation re-fetch before reporting a change (filters A/B tests and glitches)
- [ ] Word-level diff with `diff_pct`; under 2% is MINOR
- [ ] Write `changes` rows (NEW / CHANGED / MINOR / REMOVED) with before and after snapshots
- [ ] Tracked fields (e.g. price via CSS selector or regex) always count as CHANGED
- [ ] Removal rules: confirmed 404/410, or missing in 2 healthy runs
- [ ] Discord: show "Pro plan $29 → $39" style details for tracked fields

### Phase 5: health and resilience
- [ ] Per-site health: error rate > 30% trips the circuit breaker; page count drop → needs_review; short text → degraded
- [ ] One site crashing never fails the whole run (per-site error boundary)
- [ ] Record `run_sites` stats; `extracto health` command and an API endpoint
- [ ] Global run timeout; DB-level run lock shared by the CLI and API
- [ ] Count requests (not saved pages) toward `max_pages`

### Phase 6: reporting
- [ ] Rule-based classification (pricing, product, blog, messaging) and ranking
- [ ] HTML report with before/after diffs; `extracto report`; feedback import (useful/noise)

### Phase 7: summaries and delivery
- [ ] Optional Claude summaries (diff-only input, validated, template fallback)
- [ ] Email/Slack delivery (optional; Discord already works)

### Phase 8: hardening and pilot
- [ ] Playwright for `render_js` sites
- [ ] `extracto prune` (12-month retention); backups for Postgres
- [ ] Regression tests from real saved HTML; runbook; README update

### Smaller items
- [ ] Log robots.txt and sitemap requests in `fetches`
- [ ] Dashboard (extends the FastAPI app): run history, page history, diffs
- [ ] Merge the three planning docs (paused; earlier analysis in chat)
- [ ] Optional: "Authorize" button in `/docs` for the API key

## 10. Open decisions

- [ ] 🧑 Final list of sites (and terms reviewed)
- [ ] 🧑 Crawler contact email
- [ ] 🧑 Crawl days and times (default Mon/Wed/Fri 06:00 UTC)
- [ ] 🧑 Who else should receive Discord updates or reports
- [ ] 🧑 When to add AI summaries (needs `ANTHROPIC_API_KEY`, small cost)
