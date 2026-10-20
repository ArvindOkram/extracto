# Extracto: Future Extensions

|                     |                                   |
| ------------------- | --------------------------------- |
| **Project**   | Extracto                          |
| **Document**  | Post-v1 feature ideas and roadmap |
| **Date**      | 19 Oct 2026                       |
| **Companion** | `extracto-project-plan.md`      |

This is a backlog, not a commitment. Build v1 first, run the pilot, and let real feedback from the marketing team decide what is worth adding.

---

## 1. How to use this document

1. Finish v1 and the 2-week pilot before starting anything here.
2. Pick extensions based on **marketing feedback** (what they ask for), not on what is technically interesting.
3. Build one extension at a time, using the same phase approach: plan, implement with tests, review, commit.
4. Add each new capability as a **new module** (adapter, service, or API route) rather than modifying core logic.

## 2. Prerequisites already built into v1

These design choices make the extensions below cheap to add:

| v1 foundation                                         | Enables                                                      |
| ----------------------------------------------------- | ------------------------------------------------------------ |
| Snapshots stored only when content changes            | Pricing history, trends, timelines, chat over history        |
| Layered structure (domain, services, adapters)        | New fetchers, notifiers, summarizers as single files         |
| Interfaces (Fetcher, Extractor, Summarizer, Notifier) | Swapping or adding implementations without touching services |
| Repository pattern + Alembic migrations               | Schema changes and a later move to Postgres                  |
| `feedback` table                                    | Learning from useful/noise labels                            |
| Empty `api/` package                                | A FastAPI dashboard reusing existing services                |
| Per-site YAML config                                  | Per-site features (JS rendering, selectors, alert keywords)  |

## 3. Extension catalog

**Effort scale:** Low (about 1-2 days), Medium (about 3-7 days), High (more than a week).
**Value scale:** how much it helps the marketing team, High / Medium / Low.

### A. Better insight for marketing

| ID | Feature                                   | What it does                                                                 | Effort | Value  |
| -- | ----------------------------------------- | ---------------------------------------------------------------------------- | ------ | ------ |
| A1 | **Keyword and topic alerts**        | Alert when a page mentions a watched term (product name, "free trial", "AI") | Low    | High   |
| A2 | **Pricing history**                 | Tracks plan prices over time and charts them per competitor                  | Low    | High   |
| A3 | **SEO signals**                     | Tracks title tags, meta descriptions, headings, and new or removed keywords  | Low    | Medium |
| A4 | **Weekly and monthly trend digest** | "Competitor B published 6 posts this month, up from 2"                       | Medium | High   |
| A5 | **Competitor timeline**             | One history of launches, price changes, and messaging shifts per site        | Medium | High   |
| A6 | **Messaging shift detection**       | Embeddings flag changes in positioning or tone, not just wording             | Medium | Medium |
| A7 | **Content gap analysis**            | Compares topics competitors cover against your own site                      | High   | Medium |

### B. Better data capture

| ID | Feature                                     | What it does                                                                    | Effort | Value  |
| -- | ------------------------------------------- | ------------------------------------------------------------------------------- | ------ | ------ |
| B1 | **JS-rendered sites**                 | Playwright fetcher enabled per site (planned in Phase 8)                        | Low    | High   |
| B2 | **RSS and API sources**               | Uses feeds or official APIs where available, which is gentler and more reliable | Low    | Medium |
| B3 | **Screenshot and visual diff**        | Saves page screenshots and highlights layout or banner changes                  | Medium | Medium |
| B4 | **PDF and document tracking**         | Reads whitepapers, pricing sheets, and brochures                                | Medium | Medium |
| B5 | **Job postings tracking**             | Hiring patterns hint at strategy (new AI team, new region)                      | Medium | Medium |
| B6 | **Social, press, and review sources** | Adds news, review sites, and app store pages where terms allow                  | High   | Medium |

### C. Delivery and workflow

| ID | Feature                           | What it does                                                            | Effort         | Value  |
| -- | --------------------------------- | ----------------------------------------------------------------------- | -------------- | ------ |
| C1 | **Real-time alerts**        | Immediate Slack message for high-priority changes such as pricing       | Low            | High   |
| C2 | **Export**                  | CSV, Google Sheets, or Notion sync                                      | Low            | Medium |
| C3 | **Weekly PDF report**       | Polished report for leadership                                          | Low            | Medium |
| C4 | **Web dashboard (FastAPI)** | Browse and search changes, view diffs, filter by site or category       | Medium         | High   |
| C5 | **Feedback buttons**        | One-click useful/noise in the report or dashboard, feeding noise tuning | Low (after C4) | High   |
| C6 | **Per-team subscriptions**  | Pricing team gets pricing, content team gets blog posts                 | Medium         | Medium |
| C7 | **Chat with your data**     | Ask "what did Competitor A change this quarter?" and get a cited answer | Medium         | High   |

### D. Intelligence (AI)

| ID | Feature                              | What it does                                                         | Effort | Value |
| -- | ------------------------------------ | -------------------------------------------------------------------- | ------ | ----- |
| D1 | **Importance scoring**         | LLM rates each change so the top of the report is better ranked      | Low    | High  |
| D2 | **Structured fact extraction** | Pulls plans, prices, features, and integrations into a table         | Medium | High  |
| D3 | **Impact notes**               | "This undercuts our Pro plan by 10%", using your own product context | Medium | High  |
| D4 | **Feature comparison matrix**  | Your product vs each competitor, kept up to date automatically       | High   | High  |

### E. Reliability and scale

| ID | Feature                           | What it does                                                          | Effort | Value                      |
| -- | --------------------------------- | --------------------------------------------------------------------- | ------ | -------------------------- |
| E1 | **Metrics and alerting**    | Simple dashboards for crawl health and run failures                   | Low    | Medium                     |
| E2 | **Self-healing extraction** | Detects when a redesign breaks extraction and suggests selector fixes | Medium | Medium                     |
| E3 | **More sites (50+)**        | Concurrency across sites, then Postgres                               | Medium | Depends on need            |
| E4 | **Task queue**              | Celery or RQ with Redis wrapping `crawl_service`                    | High   | Low until scale demands it |
| E5 | **Multi-user access**       | Login, roles, and team ownership                                      | High   | Depends on need            |

## 4. Recommended roadmap

| Stage                                       | Features                                                                          | Why this order                                                                    |
| ------------------------------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Stage 1: Quick wins** (after pilot) | A1 keyword alerts, A2 pricing history, C1 real-time alerts, D1 importance scoring | High value, low effort, uses data already stored                                  |
| **Stage 2: Self-service**             | C4 dashboard, C5 feedback buttons, C2 export                                      | Marketing explores data without asking you, and feedback improves noise filtering |
| **Stage 3: Depth**                    | D2 fact extraction, B3 screenshot diffs, A4 trend digests, A5 timeline            | Richer reports once months of history exist                                       |
| **Stage 4: Intelligence**             | C7 chat over data, D3 impact notes, D4 comparison matrix                          | Needs good history and structured facts                                           |
| **Stage 5: Scale** (only if needed)   | E3 more sites, E4 task queue, E5 multi-user                                       | Only when usage demands it                                                        |

## 5. Extension details: how to build the top ones

### A1. Keyword and topic alerts

- **Config:** `watch_keywords` list per site or global in `sites.yaml`.
- **Where it fits:** new function in `domain/change.py` that scans added text from the diff, new service step in `report_service`.
- **Data:** optional `alerts` table (change_id, keyword, matched_text).
- **Done when:** a test page edited to include a watched term appears in a dedicated "Watchlist hits" report section.

### A2. Pricing history

- **Prerequisite:** tracked fields (price selectors) configured per site in v1.
- **Where it fits:** new `field_values` table (page_id, field, value, run_id), populated during change detection. A report section or dashboard chart reads it.
- **Done when:** a plan's price over the last N runs is shown as a table or chart.

### C1. Real-time alerts

- **Where it fits:** a rule in `report_service` (category equals pricing, or keyword hit) calls the existing Slack notifier immediately after the run instead of waiting for the weekly summary.
- **Done when:** a pricing change triggers a Slack message within the run.

### C4 and C5. Dashboard and feedback buttons

- **Stack:** FastAPI in `src/extracto/api/`, reading through existing repositories, Jinja2 or a small HTMX front end. Add basic auth first.
- **Pages:** latest run, change list with filters (site, category, date), diff view, page history, search.
- **Feedback:** POST endpoint writes to `feedback`. A monthly job reports which rules produced the most "noise" labels.
- **Done when:** marketing can find any change and mark it useful or noise without CLI access.

### D2. Structured fact extraction

- **Approach:** the LLM extracts a fixed JSON schema (plan name, price, billing period, features) from pricing pages, validated with pydantic and checked against the page text.
- **Where it fits:** new `summarizers/` or `extractors/` adapter, new `facts` table.
- **Done when:** the comparison table is generated from facts, and any value not found in the page is rejected.

### C7. Chat with your data

- **Approach:** retrieval over stored snapshots and changes (SQL filters first, optionally embeddings), with Claude answering strictly from retrieved rows and citing URL and date.
- **Guardrails:** answers must include sources, and "not found in stored data" is an acceptable answer.

## 6. Guardrails for every extension

- **Compliance first:** any new source must have its terms reviewed and must respect robots.txt and rate limits. No logins, CAPTCHA bypass, or spoofing.
- **No personal data:** do not collect names, emails, or user-generated content, especially for social, review, or job sources.
- **Verifiable output:** every new insight keeps a link to the source URL, fetch time, and stored text.
- **LLM safety:** diff or snippet-only inputs, ignore instructions found in page content, validate outputs against the source, and always allow a template fallback.
- **Secrets and access:** keep secrets in environment variables. Add authentication before exposing a dashboard beyond localhost.
- **Stay simple:** add infrastructure (Postgres, Redis, queues) only when measured needs require it.

## 7. Decision checklist before starting any extension

- [ ] Did a real user ask for it, or did feedback show the need?
- [ ] Is there stored data to support it (enough history)?
- [ ] Can it be added as a new module without changing core logic?
- [ ] Are legal and terms-of-service implications checked?
- [ ] Is there a clear "done when" test?
- [ ] Is the effort justified by the value?

## 8. Ideas parking lot

Add new ideas here as they come up during the pilot, then score them with the table format above.

| Idea | Requested by | Date | Notes |
| ---- | ------------ | ---- | ----- |
|      |              |      |       |
