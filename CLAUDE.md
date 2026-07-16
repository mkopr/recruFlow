# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**recruFlow** is a local job-application automation system for the Polish market. It runs entirely on the developer's machine via Docker Compose, uses a local LLM (Ollama) for AI work, and automates ingestion, scoring, tailoring, and sending of job applications.

The `recruFlow/` directory is the application root.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy async · Alembic |
| Frontend | React · Vite · TypeScript (strict) · Tailwind CSS |
| AI | Ollama (local LLM) · LangChain · LangGraph |
| Database | PostgreSQL |
| Scheduling | APScheduler (inside FastAPI lifespan) |
| Package manager (Python) | `uv` |
| Package manager (Node) | `pnpm` |
| Linter/formatter | `ruff` (Python) · ESLint + Prettier (TypeScript) |
| Type checking | `mypy` (Python) · `tsc --noEmit` (TypeScript) |
| Migrations | Alembic |

## Development Commands

```bash
make install          # uv sync --all-groups + pnpm install + pre-commit install
make up               # docker compose up (all services, hot-reload)
make lint             # ruff check + mypy + pnpm lint
make format           # ruff format + ruff check --fix + pnpm format
make test             # uv run pytest + pnpm test
make test-unit        # unit tests only
make test-integration # integration tests only
make typecheck        # mypy + tsc --noEmit
make ci               # format + lint + typecheck + full test suite (must be zero failures)
make migrate          # alembic upgrade head
make seed             # load sample offers into DB
make generate-types   # generate TypeScript types from FastAPI /openapi.json
make clean            # remove build artefacts, __pycache__, .mypy_cache, dist/
```

Single test: `uv run pytest tests/path/to/test_file.py::test_function_name`

## Architecture

The system is structured around these phases:

- **Phase 0** — Foundations: project scaffold, Docker Compose, DB bootstrap, FastAPI skeleton, CI
- **Phase 1** — Ingestion: connectors for SOLID.Jobs, JustJoin.it, NoFluffJobs (all direct HTTP APIs); APScheduler; offer list UI
- **Phase 2** — Profile: candidate profile schema, CV upload + LLM extraction, profile editor UI, sjctl sync
- **Phase 3** — Matching: unified `MatchScore` schema, LangChain Matcher (all registered connectors), batch scoring job
- **Phase 4** — Application: CV tailoring chain, cover letter generation, review UI, SMTP send, status tracking
- **Phase 5** — Swarm: batch draft generation with SSE progress, dry-run gate, send queue worker (rate-limited), Playwright form-fill
- **Phase 6** — Hardening: source health monitoring, digest notifications, outcome dashboard, PDF/DOCX export

Key architectural constraints:
- **ELT pattern**: raw API payload always stored before normalisation
- **Dedup**: hash on canonical URL; fallback hash on title + company + location
- **No auto-send**: Applications are never created or sent without explicit user approval
- **Unified MatchScore**: every connector is scored by the same LangChain Matcher into one schema/table; the `engine` field is kept for schema stability but is only ever `"langchain"` today — the originally-planned second engine (`sjctl evaluate`, SOLID.Jobs-only) was abandoned before P3US23 shipped (see `docs/architecture/matching.md`'s P3US23 section and `docs/adr/0022-connector-registry-is-the-single-source-of-truth.md`)
- **SSE for swarm progress**: not WebSocket (OD-8)
- **Send queue**: rate-limited, daily cap enforced as a hard block (OD-5)

## Domain Glossary

Use these terms consistently in code, schemas, and PR descriptions:

| Term | Definition |
|---|---|
| **Offer** | A normalised job posting with exactly one Source. Alongside its ingestion-sourced fields, it carries four user-owned fields — `applied`, `hide`, `notes`, `link_opened_at` — set only via `PATCH /offers/{offer_id}`, never by ingestion or scoring |
| **Source** | The DB row holding one Connector's schedule, fetch-range, and enabled state — exactly one per registered Connector |
| **Connector** | A job board integration's code identity: a string key (e.g. `solid_jobs`), its `JobBoardConnector` subclass, and its `ConnectorSpec` entry (name/label/dispatch) in `CONNECTOR_REGISTRY` |
| **Raw Payload** | Unmodified API/scrape response stored at ingest time |
| **Profile** | Candidate's structured facts: skills, experience, preferences, constraints |
| **Match Score** | Structured evaluation of one Offer against the active Profile (score_percent 0-100 + dimensions) |
| **Application** | Record of intent/action to apply; statuses: `drafted` · `reviewed` · `sent` · `failed` · `interview` · `offer` · `rejected` |
| **Tailored CV** | Profile rendered as CV, adjusted in phrasing/emphasis for a specific Offer — facts only, no fabrication |
| **Cover Letter** | Generated letter alongside Tailored CV — same facts-only constraint |
| **Swarm** | Batch-send operation with mandatory dry-run review gate |
| **Dry Run** | Swarm execution that generates all drafts for review but does not send |
| **Matcher** | LangChain chain scoring an Offer against a Profile (used for JustJoin.it and NoFluffJobs) |
| **Digest** | Scheduled job surfacing new high-grade Offers since last run |
| **Send Queue** | Rate-limited, retry-aware worker dispatching Applications one at a time |
| **Campaign ID** | `recruflow` — passed as `campaign` parameter in all direct SOLID.Jobs API calls |
| **Remote** | An Offer requiring zero on-site presence. Hybrid arrangements are not Remote — they are tracked in a source's raw payload but not surfaced as a distinct normalised field in v1 |
| **Contract Type** | The legal/administrative form of an Offer's employment (e.g. UoP, B2B) — distinct from work-time schedule (full-time/part-time), which is not modelled |

## Development Workflow

When implementing a change:

1. Mirror patterns from prior work in the same subsystem — read existing routes/connectors/tests for the pattern to follow before writing new code.
2. Commit convention: `US<NN> <short message>` for stories, `BUG<number> <short message>` for bugs. Single-line subject only — no body, no bullet points, no trailers (e.g. no `Co-Authored-By`).
3. After implementation, run `make ci` (must be zero failures), then test end-to-end on the real stack with `make up`.
4. Update the relevant `docs/architecture/*.md` file (see `ARCHITECTURE.md`'s index) to reflect new endpoint contracts or design decisions — root `ARCHITECTURE.md` itself only changes for repo-layout/dependency/core-`app/`-package changes.

## Code Quality Rules

- `ruff` configured with line length 100, ruleset E/F/I/UP/B
- `mypy` strict where practical
- Pre-commit hooks enforce ruff lint + format, mypy, ESLint, trailing whitespace, lockfile sync
- TypeScript types for the API client are auto-generated from FastAPI's OpenAPI schema — run `make generate-types` after changing API contracts
- `uv.lock` and `pnpm-lock.yaml` are both committed and kept in sync

## SOLID.Jobs Integration

```python
# Canonical direct-HTTP pattern for SOLID.Jobs (app/connectors/solid_jobs.py)
payload = fetch_json(
    url, source_name="SOLID.Jobs", logger=logger, params=params, headers={"X-Api-Version": "1.0"}
)
offers = payload["jobs"]
```

recruFlow itself manages `campaign=recruflow` directly now (`Settings.solid_jobs_campaign`), passed as a required query param on every SOLID.Jobs API call.
