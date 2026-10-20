# extracto
Extracto is a lightweight crawler that watches about 10 websites 2-3 times a week, stores their content, and sends your marketing team a short, verified summary of what’s new, changed, or removed, with links to the live pages and before/after diffs.

> Status: Phase 0 (project skeleton). Commands exist but are not implemented yet.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # add ,llm or ,js for Claude summaries / Playwright
cp .env.example .env
pre-commit install
```

## Usage

```bash
extracto --help
extracto init-db
extracto run [--site NAME] [--dry-run]
extracto report [--run-id N] [--send]
extracto health
```

## Development

```bash
pytest -q                                  # tests
ruff check . && ruff format --check .      # lint
mypy src                                   # type check (optional)
```

`make test`, `make lint`, and `make format` wrap these if `make` is available.

## Layout

```
src/extracto/
├── domain/      # pure logic, no I/O
├── services/    # orchestration
├── adapters/    # fetchers, extractors, storage, summarizers, notifiers
├── cli/         # typer commands
└── api/         # reserved for a future dashboard
```

See `CLAUDE.md` for the architecture rules and the docs in the repo root for the full spec.
