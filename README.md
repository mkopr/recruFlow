# recruFlow

Local job-application automation system for the Polish job market. recruFlow ingests offers from
nine job boards, scores each one against your candidate profile with a local LLM, and (in
upcoming phases) tailors and sends applications for you. It runs entirely on your own machine via
Docker Compose — no cloud services, no data leaving your box.

> Single-user tool. No multi-tenant concerns, no auth system — it's designed to run on your
> laptop, for you.

> **Status**: Phases 0–3 shipped (ingestion, profile, matching). Application generation and
> Swarm mode (Phases 4–5) are next — see [Roadmap](#roadmap).

<!-- CI badge: pending a GitHub remote for this repo — see docs/architecture/deployment.md -->

---

## Contents

- [Screenshots](#screenshots)
- [Quick start](#quick-start)
- [Useful commands](#useful-commands)
- [Environment variables](#environment-variables)
- [Walkthrough](#walkthrough)
- [Architecture](#architecture)
- [Connectors](#connectors)
- [Standards & conventions](#standards--conventions)
- [Domain glossary](#domain-glossary)
- [Roadmap](#roadmap)

---

## Screenshots

_Coming soon — one screenshot per page below (Offers, Profile, Failures, Settings) plus an
architecture/infra diagram._

## Quick start

**Prerequisites**: [Docker](https://docs.docker.com/get-docker/) + Docker Compose,
[uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), Git.

```bash
git clone <repo-url> && cd recruFlow

cp .env.example .env          # fill in SMTP creds etc. later; defaults work for local dev

make install                  # uv sync --all-groups + pnpm install + pre-commit install
make up                       # docker compose up --build — api, frontend, db, ollama

# in another terminal, once the containers are healthy:
make migrate                  # alembic upgrade head — creates all tables
make seed                     # optional: load a handful of sample offers
```

Then open:

| Page | URL |
| --- | --- |
| Frontend (Offers page) | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| API health check | http://localhost:8000/health |

Offers start flowing in automatically — every connector is on its own schedule (5-minute default
interval) as soon as the `api` container boots, no manual trigger required. Use the **Fetch now**
buttons on the Offers page, or `POST /ingest/{source}`, to pull immediately instead of waiting.

## Useful commands

Setup & running:

| Command | Action |
| --- | --- |
| `make install` | Install Python + Node deps, register pre-commit hooks |
| `make up` | `docker compose up --build` — all four services, hot-reload for `api` and `frontend` |
| `make migrate` | Apply all Alembic migrations |
| `make seed` | Load sample offers + a stub profile (idempotent, safe to re-run) |
| `make generate-types` | Regenerate `frontend/src/api/schema.d.ts` from the running API's OpenAPI schema |

Code quality:

| Command | Action |
| --- | --- |
| `make lint` | `ruff check` + `mypy` + `pnpm lint` |
| `make format` | `ruff format` + `ruff check --fix` + `pnpm format` |
| `make typecheck` | `mypy` + `pnpm run typecheck` (`tsc -b`) |
| `make ci` | `format` → `lint` → `typecheck` → `test`, in order — the exact sequence GitHub Actions runs |

Testing:

| Command | Action |
| --- | --- |
| `make test` | Full Python test suite (brings up the dedicated `db_test` service first) |
| `make test-unit` | Python unit tests only (`-m "not integration"`) |
| `make test-integration` | Python integration tests only, against `db_test` — never the real dev DB |
| `make test-frontend` | `pnpm test` (vitest) — not yet wired into `make ci`, see `docs/adr/0007` |
| `uv run pytest tests/path/to/test_file.py::test_name` | Run a single Python test |

Other:

| Command | Action |
| --- | --- |
| `make clean` | Remove `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`, `build` |

## Environment variables

Copy `.env.example` to `.env` and fill in the blanks — every variable the project uses is
documented there with a comment. Highlights:

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async PostgreSQL connection string |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local LLM runtime + model for CV extraction |
| `MATCHER_OLLAMA_MODEL` | Model used by the LangChain Matcher |
| `SOLID_JOBS_CAMPAIGN` | Analytics attribution param sent on every SOLID.Jobs API call |
| `BATCH_SCORING_LIMIT` | Unscored offers processed per ingestion/scheduler cycle |
| `SMTP_*` | Outgoing mail credentials — used once application sending (Phase 4) lands |
| `VITE_API_BASE_URL` / `CORS_ALLOW_ORIGIN` | Frontend ↔ API wiring |

## Walkthrough

The frontend has four pages, linked from the nav bar at the top of every screen.

### Offers — `/`

The main screen: every ingested offer in a filterable, sortable table (source, remote, seniority,
minimum salary, minimum score). Each row shows a **Score** badge (red→yellow→green, colour
interpolated by match percentage) that opens a drawer with the per-dimension breakdown and
rationale on click. A **Fetch now** button per connector triggers an immediate ingestion run.
Rows you haven't opened yet that score above your alert threshold get a highlighted accent.

_Screenshot: coming soon_

### Profile — `/profile`

Upload a CV (PDF/DOCX) and a local LLM extracts a structured profile — skills, past roles,
education, certifications, languages — facts only, nothing invented. Edit any field by hand, then
**Save** (as a draft) or **Set as active** (the profile every offer gets scored against).

_Screenshot: coming soon_

### Settings — `/settings`

Per-connector cards (fetch cadence, fetch date range, auto-fetch, stop/start), offer cleanup
(bulk-delete offers older than a chosen date, with a dry-run preview), and notification
preferences (minimum score to alert on, sound, volume — all live via a Server-Sent Events
stream).

_Screenshot: coming soon_

### Failures — `/failures`

A dead-letter queue viewer for the ingestion and scoring pipelines. Every anticipated failure
that used to just log-and-drop now lands here as one durable row per failing resource, with a
**Retry** button that replays it through the original code path.

_Screenshot: coming soon_

## Architecture

| Layer | Technology |
| --- | --- |
| Backend | Python · FastAPI · SQLAlchemy (async) · Alembic |
| Frontend | React · Vite · TypeScript (strict) · Tailwind CSS |
| AI | Ollama (local LLM) · LangChain |
| Database | PostgreSQL |
| Scheduling | APScheduler, wired into the FastAPI lifespan |
| Package managers | `uv` (Python) · `pnpm` (Node) |

Key design decisions:

- **ELT, not ETL** — every connector stores the raw API/scrape payload before normalising it, so
  a mapping bug never loses data permanently.
- **Dedup** — hash on canonical URL, falling back to title + company + location.
- **One unified `MatchScore` schema** — every connector's offers are scored by the same LangChain
  Matcher into one table; there is no per-source scoring engine.
- **No auto-send** — an `Application` is never created or dispatched without explicit user
  approval (planned for Phase 4/5).
- **Connector registry is the single source of truth** — adding a job board requires touching
  `CONNECTOR_REGISTRY` (`app/ingestion/registry.py`) plus one new connector file; the scheduler,
  matcher, and frontend all read off the registry with zero further edits.
- **Dead letter queues, not silent logging** — handled failures in ingestion and scoring persist
  as retryable rows instead of disappearing into a log line.

<!-- Infra/architecture diagram: coming soon -->

Full documentation, split by subsystem so you only need to read what you're touching:

- [ARCHITECTURE.md](ARCHITECTURE.md) — repo layout, dependency groups, the core `app/` package (index for everything below)
- [docs/architecture/database.md](docs/architecture/database.md) — schema, the seven v1 tables
- [docs/architecture/ingestion.md](docs/architecture/ingestion.md) — Offer schema/dedup, scheduler, ingestion API, dead letter queues, fetch-range/auto-fetch, connector registry
- [docs/architecture/connectors.md](docs/architecture/connectors.md) — one file per job board connector
- [docs/architecture/profile.md](docs/architecture/profile.md) — profile data model, CV upload + LLM extraction
- [docs/architecture/matching.md](docs/architecture/matching.md) — Match Score schema, LangChain Matcher, batch scoring
- [docs/architecture/frontend.md](docs/architecture/frontend.md) — every frontend page in detail
- [docs/architecture/deployment.md](docs/architecture/deployment.md) — Makefile targets, pre-commit, Docker Compose, CI
- [docs/adr/](docs/adr/) — architecture decision records, one per hard-to-reverse call

## Connectors

Nine job boards ingested today, all dispatched through the same generic connector registry — no
per-connector code in the scheduler, matcher, or frontend:

| Connector | Method |
| --- | --- |
| [SOLID.Jobs](docs/architecture/connectors/solid-jobs.md) | Direct HTTP API |
| [JustJoin.it](docs/architecture/connectors/justjoinit.md) | Direct HTTP API |
| [NoFluffJobs](docs/architecture/connectors/nofluffjobs.md) | Direct HTTP API |
| [Bulldogjob](docs/architecture/connectors/bulldogjob.md) | Sitemap + embedded JSON |
| [Rocket Jobs](docs/architecture/connectors/rocket-jobs.md) | Sitemap + JSON-LD |
| [Pracuj.pl](docs/architecture/connectors/pracuj.md) | Playwright (Cloudflare-gated) |
| [RemoteOK](docs/architecture/connectors/remoteok.md) | Direct API |
| [Remotive](docs/architecture/connectors/remotive.md) | Direct API, per-category |
| [We Work Remotely](docs/architecture/connectors/we-work-remotely.md) | RSS feed |

One spike ([The Protocol](docs/architecture/connectors/the-protocol-spike-failed.md)) was
attempted and abandoned — Cloudflare's Managed Challenge persisted past every mitigation tried.

## Standards & conventions

- **Python**: `ruff` (line length 100, ruleset `E/F/I/UP/B/C90`, max cyclomatic complexity 10),
  `mypy` strict where practical.
- **TypeScript**: ESLint + Prettier, strict mode, the same complexity-10 rule as Python.
- **Pre-commit hooks** (installed by `make install`): trailing whitespace → `ruff check --fix` →
  `ruff format` → `eslint --fix` → `mypy` → `uv.lock`/`pnpm-lock.yaml` sync checks.
- **CI** (`.github/workflows/ci.yml`): runs `make ci` on every PR and push to `main` — the same
  command you run locally, so CI and local can never drift apart.
- **Types stay in sync**: `frontend/src/api/schema.d.ts` is generated from the backend's OpenAPI
  schema and committed. Run `make generate-types` after any API contract change.
- **Testing**: unit tests (`tests/`) touch no external services; integration tests
  (`tests/integration/`) run against a dedicated `db_test` Compose service, never the real dev
  database.
- **Commits**: `US<NN> <short message>` for user stories, `BUG<NN> <short message>` for bug
  fixes — single-line subject, no body, no trailers.

## Domain glossary

The full glossary lives in [CLAUDE.md](CLAUDE.md) (canonical terms) and
[CONTEXT.md](CONTEXT.md) (terms sharpened during design sessions, with alternatives rejected).
The essentials:

| Term | Definition |
| --- | --- |
| **Offer** | A normalised job posting, one per Source, deduped by canonical URL |
| **Source** | The DB row holding one Connector's schedule, fetch-range, and enabled state |
| **Profile** | The candidate's structured facts — skills, experience, preferences, constraints |
| **Match Score** | A 0–100 evaluation of one Offer against the active Profile, with per-dimension breakdown |
| **Application** | A record of intent/action to apply, moving through a status pipeline (Phase 4+) |
| **Swarm** | A batch-generate-then-send operation across multiple Offers, gated by a mandatory dry-run review (Phase 5) |

## Roadmap

Planning lives in `user stories/000 high level guide.md`, tracked outside this repository.

| Phase | Goal | Status |
| --- | --- | --- |
| 0 — Foundations | Project scaffold, Docker Compose, DB bootstrap, CI | ✅ Done |
| 1 — Ingestion | Connectors, scheduler, offer list UI | ✅ Done (grew from 3 to 9 connectors) |
| 2 — Profile | Candidate profile schema, CV upload + LLM extraction, editor UI | ✅ Done |
| 3 — Matching | Unified Match Score schema, LangChain Matcher, batch scoring, dead letter queues | ✅ Done |
| 4 — Application | CV tailoring, cover letter generation, review UI, SMTP send, status tracking | 🔜 Next |
| 5 — Swarm Mode | Batch draft generation, dry-run review gate, rate-limited send queue, Playwright form-fill | ⏳ Planned |
| 6 — Hardening | Source health monitoring, digest notifications, outcome dashboard, PDF/DOCX export | ⏳ Planned |
