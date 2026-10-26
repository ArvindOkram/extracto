# Extracto: TODO

Status as of 25 Oct 2026. Code: storage, crawler (Phases 1–3, RFC 9309 robots, sitemaps, politeness),
Discord notifications, HTTP API (`/crawl` test crawls, `/runs` background runs with per-site stats),
Postgres support, Render packaging. Tests: 283 passing locally. Sites: 40 in `config/sites.yaml`
(health, marketing/SEO, social, design, newsletters, AI). A full run takes about 70 minutes.
Deploy guide: [`docs/deploy-render.md`](docs/deploy-render.md).

Legend: 🧑 = you (accounts, secrets, decisions) · 🤖 = code work I can do

---

## Go live, in order

### 1. Code to GitHub
- [ ] 🤖 Optional fix first: crawl only the start host by default (Semrush wanders into `pt.`, `es.`... subdomains)
- [ ] 🤖 Commit the work on a branch and open a PR to `main` (ask me)
- [ ] 🧑 CI green on the PR: ruff, SQLite tests, and the **Postgres** job (first time the new run-stats query runs on Postgres)
- [ ] 🧑 Merge to `main` (Render deploys from `main`)
- [ ] 🧑 Confirm `.env`, `config/sites.yaml`, `data/` are not on GitHub (they're gitignored)

### 2. Secrets
- [ ] 🧑 **Rotate the Discord webhook** (it appeared in chat and old logs): delete it, create a new one in the updates channel
- [ ] 🧑 Don't reuse the local `EXTRACTO_API_KEY` (it was pasted in chat); Render generates a new one
- [ ] 🧑 Crawler contact email in `config/sites.yaml` → `defaults.user_agent` is one you check (now `aokram17@gmail.com`; a team address is better)
- [ ] 🧑 Terms of service checked for the sites you keep (especially TechCrunch and The Verge)

### 3. Neon (database)
- [ ] 🧑 neon.tech → Create project → region **AWS Asia Pacific (Singapore)**
- [ ] 🧑 Copy the **direct** (non-pooled) connection string with `sslmode=require`
- [ ] 🧑 Optional check from your laptop: `$env:DATABASE_URL="..."; extracto init-db`, then close the terminal

### 4. Render (app)
- [ ] 🧑 render.com → New → **Blueprint** → repo `ArvindOkram/extracto` (reads `render.yaml`, Singapore, free)
- [ ] 🧑 Paste `DATABASE_URL` (Neon) and `DISCORD_WEBHOOK_URL` (the new webhook)
- [ ] 🧑 Environment → **Secret Files** → add `sites.yaml` = contents of your local `config/sites.yaml`
- [ ] 🧑 Copy the generated `EXTRACTO_API_KEY` into a password manager
- [ ] 🧑 Note the URL `https://<name>.onrender.com`

### 5. Verify on Render
- [ ] 🧑 `GET /healthz` → `{"status":"ok"}` (first call can take ~1 min while it wakes)
- [ ] 🧑 `POST /notify-test` with `X-API-Key` → test message in Discord
- [ ] 🧑 `POST /crawl` `{"site": "Anthropic News", "max_pages": 3}` → dry run works from Render
- [ ] 🧑 Baseline run: `POST /runs` with `{}` → 202 + `run_id`. Keep the app awake for ~70 min
      (open `/healthz` every ~10 min, or turn on cron Job 1 first), then `GET /runs/{id}` → `completed`
- [ ] 🧑 Discord shows "Baseline saved" per site; check `errors` per site in `GET /runs/{id}`

### 6. cron-job.org (schedule, times in UTC)
- [ ] 🧑 Job 1 keep-awake: `GET https://<app>.onrender.com/healthz`, crontab `*/10 5-9 * * 1,3,5`
- [ ] 🧑 Job 2 start run: `POST https://<app>.onrender.com/runs`, crontab `0 6 * * 1,3,5`,
      headers `X-API-Key: <key>` and `Content-Type: application/json`, body `{}`
- [ ] 🧑 Failure email notifications on for Job 2
- [ ] 🧑 Window check: run starts 06:00, ends ~07:10, keep-awake runs to 09:50 ✅ (re-check if you add sites)

### 7. After the first scheduled run
- [ ] 🧑 Discord summary arrived; `GET /runs` shows `completed`, not `failed`
- [ ] 🧑 Second run lists only real new/updated pages (no flood of false changes)
- [ ] 🧑 Neon dashboard storage is growing slowly (expect tens of MB per month, limit ~0.5 GB)
- [ ] 🤖 Hardening: re-check private-IP safety on every request, not just `/crawl` start URLs

### Changing sites later
- Edit local `config/sites.yaml`, dry-run with `POST /crawl`, then paste the file into the Render Secret File (it doesn't sync from git). New sites start with a silent baseline.

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
- [ ] 🧑 When to add AI summaries (needs `GEMINI_API_KEY`, small cost)
