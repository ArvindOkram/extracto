# Extracto diagrams

Mermaid diagrams render on GitHub and in VS Code (Markdown preview, or the "Markdown Preview
Mermaid Support" extension). Paste any block into https://mermaid.live to edit it.

## 0. Production on Render (free tier)

```mermaid
sequenceDiagram
    autonumber
    participant Cron as cron-job.org
    participant App as Render web service (extracto serve)
    participant Web as Target websites
    participant DB as Neon Postgres
    participant Discord as Discord webhook

    Cron->>App: GET /healthz (every 10 min in the crawl window; wakes / keeps awake)
    Cron->>App: POST /runs + X-API-Key (Mon/Wed/Fri 06:00 UTC)
    App->>DB: stale-run check, insert runs row (running)
    App-->>Cron: 202 {run_id, status_url}
    loop each site in sites.yaml (background thread)
        App->>Web: robots.txt, sitemap, pages (polite)
        App->>DB: pages, snapshots (only on change), fetches
    end
    App->>DB: close run (completed / failed)
    App->>Discord: summary: stats + new/updated pages (or baseline)
```

## 1. `extracto run`, end to end

```mermaid
sequenceDiagram
    autonumber
    actor User as User / scheduler
    participant CLI as cli (extracto run)
    participant Run as RunService
    participant Crawl as CrawlService
    participant Web as Target website
    participant DB as SQLite (data/monitor.db)
    participant Raw as data/raw (gzip HTML)
    participant Discord as Discord webhook

    User->>CLI: extracto run [--site NAME]
    CLI->>CLI: load config/sites.yaml, settings (.env)
    CLI->>Run: run(sites)
    Run->>DB: insert runs row (status=running)
    loop each site
        Run->>Crawl: crawl_site(site, run_id)
        Crawl->>Web: GET /robots.txt, sitemap.xml
        loop each queued URL (until queue empty or max_pages)
            alt robots.txt disallows
                Crawl->>DB: fetches row (skipped_robots)
            else allowed
                Crawl->>Web: GET page (polite delay, retries, If-None-Match)
                Web-->>Crawl: 200 HTML / 304 / error
                Crawl->>DB: page + snapshot (only if hash changed) + fetches row
                Crawl->>Raw: raw HTML (only with a new snapshot)
                Crawl->>Crawl: queue filtered links (depth + 1)
            end
        end
        Crawl-->>Run: SiteCrawlResult (pages, new snapshots, errors)
    end
    Run->>DB: close run (completed / failed)
    Run-->>CLI: RunOutcome
    CLI->>User: per-site summary in terminal
    CLI->>Discord: run summary embed (if DISCORD_WEBHOOK_URL set)
```

## 2. Crawling one site (`CrawlService.crawl_site`)

```mermaid
flowchart TD
    A([crawl_site]) --> B["Fetch /robots.txt"]
    B --> B1{"Status?"}
    B1 -- "2xx" --> R1["Parse rules, apply Crawl-delay"]
    B1 -- "404 / other 4xx" --> R2["No rules: allow all"]
    B1 -- "401 / 403" --> R3["Disallow all"]
    B1 -- "5xx / unreachable" --> R4["Allow start URL only"]
    R1 & R2 & R3 & R4 --> C["Upsert sites row"]
    C --> D["Queue start URL (depth 0, skips allow_patterns)"]
    D --> E["Read sitemap(s): queue URLs that pass the filter (depth 0)"]
    E --> F{"Queue empty or max_pages reached?"}
    F -- yes --> Z(["Return SiteCrawlResult"])
    F -- no --> G["Pop next URL (breadth-first)"]
    G --> H{"robots.txt allows?"}
    H -- no --> H1["fetches row: skipped_robots"] --> F
    H -- yes --> I["Fetch with ETag / Last-Modified"]
    I --> J{"Outcome"}
    J -- "200 HTML" --> K["Extract text, title, links; hash text"]
    K --> L{"Hash differs from latest snapshot?"}
    L -- yes --> M["Insert snapshot + save raw HTML"]
    L -- no --> N["Update last_seen only"]
    J -- "304 Not Modified" --> O["Update last_seen; reuse links from last snapshot"]
    J -- "error / skipped" --> P["Count error if HTTP or network error"]
    M & N & O & P --> Q["fetches row (same transaction)"]
    Q --> S{"depth < max_depth?"}
    S -- yes --> T["Normalize + filter links, queue at depth + 1"] --> F
    S -- no --> F
```

## 3. Database schema

```mermaid
erDiagram
    SITES ||--o{ PAGES : has
    SITES ||--o{ RUN_SITES : "stats per run"
    SITES ||--o{ FETCHES : "requests to"
    RUNS ||--o{ RUN_SITES : has
    RUNS ||--o{ SNAPSHOTS : produced
    RUNS ||--o{ CHANGES : produced
    RUNS ||--o{ FETCHES : made
    PAGES ||--o{ SNAPSHOTS : "versions of"
    PAGES ||--o{ CHANGES : "changes to"
    PAGES |o--o{ FETCHES : "requests for"
    SNAPSHOTS |o--o{ CHANGES : "before / after"
    CHANGES ||--o{ FEEDBACK : receives

    SITES {
        int id PK
        string name UK
        string domain
        datetime created_at
    }
    PAGES {
        int id PK
        int site_id FK
        text url
        string url_hash "unique per site"
        string status "active | removed"
        datetime first_seen
        datetime last_seen
        int missed_runs
        string etag
        string last_modified
    }
    SNAPSHOTS {
        int id PK
        int page_id FK
        int run_id FK
        datetime fetched_at
        string content_hash
        text title
        text text
        json meta_json "description, headings, links"
        text raw_path
    }
    RUNS {
        int id PK
        datetime started_at
        datetime finished_at
        string status "running | completed | failed"
    }
    RUN_SITES {
        int run_id PK, FK
        int site_id PK, FK
        int pages_crawled
        int errors
        int short_text_pages
        string health "ok | degraded | failed | needs_review | skipped"
        float duration_s
    }
    CHANGES {
        int id PK
        int run_id FK
        int page_id FK
        string change_type "NEW | CHANGED | MINOR | REMOVED"
        float diff_pct
        string category "pricing | product | blog | ..."
        text summary
        int before_snapshot_id FK
        int after_snapshot_id FK
        datetime created_at
    }
    FEEDBACK {
        int id PK
        int change_id FK
        string label "useful | noise"
        datetime created_at
    }
    FETCHES {
        int id PK
        int run_id FK
        int site_id FK
        int page_id FK "null if skipped before a page existed"
        text url
        datetime fetched_at
        string outcome "ok | not_modified | http_error | ..."
        int status_code
        int duration_ms
        int bytes
        string content_hash
        text error
    }
```

## 4. Code layers

```mermaid
flowchart LR
    CLI["cli/<br/>extracto commands"] --> Boot["bootstrap.py<br/>wiring"]
    Boot --> Svc
    subgraph Svc["services/"]
        RunS["run_service"] --> CrawlS["crawl_service"]
        NotifyS["notification_service"]
    end
    Svc --> Dom["domain/<br/>urls, robots, sitemap, text, models<br/>(pure, no I/O)"]
    Svc --> Ifc["interfaces.py<br/>Fetcher, Extractor, Notifier"]
    subgraph Ad["adapters/"]
        F["fetchers/<br/>http_fetcher"]
        E["extractors/<br/>trafilatura"]
        S["storage/<br/>orm, repositories, raw_store, backup"]
        N["notifiers/<br/>discord"]
    end
    Ad -. implements .-> Ifc
    F --> Web[(Websites)]
    S --> DB[(SQLite)]
    N --> DC[(Discord)]
```
