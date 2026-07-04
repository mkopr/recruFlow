# recruFlow

Local job-application automation system for the Polish job market. Runs entirely on a
developer's machine via Docker Compose, uses a local LLM (Ollama) for AI work, and automates
ingestion, scoring, tailoring, and sending of job applications. Single-user tool, no
multi-tenant concerns.

This repository is bootstrapping (Phase 0). This README will be extended as later stories add
Docker Compose, the database, the frontend, and CI.

## Getting started

Install [uv](https://docs.astral.sh/uv/) first, then:

```bash
uv sync --all-groups   # install main, dev, and test dependency groups
uv run ruff check .    # lint
uv run mypy .          # type-check
uv run pytest          # run the test suite
```

Or via the Makefile:

```bash
make install
make lint
make typecheck
make test
```

## Running locally

The full stack runs via Docker Compose:

```bash
make up             # docker compose up --build
```

This starts four services, each with a health check:

| Service | Port | Notes |
| --- | --- | --- |
| `api` | 8000 | FastAPI + uvicorn, `--reload` enabled (bind-mounts `app/`) |
| `frontend` | 5173 | Vite dev server, `--host 0.0.0.0` (bind-mounts `frontend/`) |
| `db` | 5432 | PostgreSQL 16 |
| `ollama` | 11434 | Local LLM runtime |

Both `api` and `frontend` hot-reload on source changes since their directories are bind-mounted
into the containers. Check status with `docker compose ps`.

To confirm the `sjctl` binary installed inside the `api` container:

```bash
make sjctl-version   # docker compose exec api sjctl version
```

## Database

With `make up` running (the `api` container must exist for `docker compose exec` to work):

```bash
make migrate   # docker compose exec api alembic upgrade head
make seed      # docker compose exec api python -m app.db.seed
```

`make migrate` applies all Alembic migrations, creating the six v1 tables (`sources`, `offers`,
`profiles`, `cv_versions`, `match_scores`, `applications`) — see [ARCHITECTURE.md](ARCHITECTURE.md)
for the full schema. `make seed` loads a handful of sample offers; both commands are safe to
re-run.

## Frontend

The frontend is a React + Vite + TypeScript project under `frontend/`, managed with
[pnpm](https://pnpm.io/).

```bash
cd frontend
pnpm install        # install dependencies (writes/reads pnpm-lock.yaml)
pnpm dev            # start the Vite dev server at http://localhost:5173
pnpm lint           # ESLint
pnpm format         # Prettier — write mode
pnpm format:check   # Prettier — check mode, no writes
pnpm test           # vitest run — component tests
```

TypeScript strict mode is enabled (`tsconfig.app.json` / `tsconfig.node.json`), and styling is
done exclusively with Tailwind CSS utility classes plus the shared theme tokens/component classes
in `src/index.css`.

`pnpm test` is also runnable as `make test-frontend` from the repo root. It is **not** part of
`make test`/`make ci`/the GitHub Actions workflow yet — see
[docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md](docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md).

### Generating API types

`frontend/src/api/schema.d.ts` holds TypeScript types generated from the backend's OpenAPI
schema, and `frontend/src/api/client.ts` exports a shared `openapi-fetch` client (`apiClient`)
typed against them. Regenerate the types with the API running:

```bash
make up              # in another terminal, if the API isn't already running
make generate-types  # fetches http://localhost:8000/openapi.json -> frontend/src/api/schema.d.ts
```

`schema.d.ts` is committed to the repo, so **re-run `make generate-types` after any API contract
change** (new endpoint, changed request/response shape) and commit the result — otherwise the
frontend's types silently drift from the real backend contract.

## Pre-commit hooks

Hooks install automatically as part of `make install` (which now also runs
`uv run pre-commit install`). To install them manually:

```bash
uv run pre-commit install
```

Run all hooks against the full repository on demand:

```bash
uv run pre-commit run --all-files
```

Hooks enforced, in the order they run:

| Hook | What it checks |
| --- | --- |
| `trailing-whitespace` | Strips trailing whitespace from changed files |
| `ruff check --fix` | Python lint (auto-fixes what it can) |
| `ruff format` | Python formatting |
| `eslint --fix` | Frontend lint (auto-fixes what it can) |
| `mypy` | Python static types, strict mode |
| `uv lock --check` | Fails if `uv.lock` is out of sync with `pyproject.toml` |
| `pnpm install --frozen-lockfile` | Fails if `pnpm-lock.yaml` is out of sync with `package.json` |

Auto-fixing hooks may modify files during a commit attempt. When that happens the commit is
aborted and the fixed files are left unstaged — review the changes, `git add` them, and commit
again.

## Continuous Integration

GitHub Actions runs `make ci` on every pull request and every push to `main` (workflow file:
[.github/workflows/ci.yml](.github/workflows/ci.yml)). It installs Python dependencies via `uv`
and Node dependencies via `pnpm`, then auto-fixes formatting first (`ruff format`, Prettier) and
checks `ruff`, `mypy`, `pytest`, ESLint, and TypeScript types (`tsc -b`) — the build fails on the
first check that still fails after auto-fix. Run logs are visible under the repository's
**Actions** tab on GitHub.

> No GitHub remote is configured for this repository yet, so no CI status badge is shown here.
> Add one (`[![CI](.../ci.yml/badge.svg)](.../ci.yml)`) once the repo has a GitHub remote.

## Environment variables

Copy `.env.example` to `.env` and fill in the blanks. Every environment variable the project
requires is documented here, grouped by concern.

| Variable | Description |
| --- | --- |
| `DATABASE_URL` | Async PostgreSQL connection string (SQLAlchemy + asyncpg). |
| `OLLAMA_BASE_URL` | Base URL of the local Ollama server. |
| `OLLAMA_MODEL` | Default Ollama model tag used for LLM calls. |
| `SMTP_HOST` | SMTP server host used to send applications. |
| `SMTP_PORT` | SMTP server port. |
| `SMTP_USERNAME` | SMTP auth username. |
| `SMTP_PASSWORD` | SMTP auth password. |
| `SMTP_FROM_EMAIL` | From-address used on outgoing application emails. |
| `SJCTL_CAMPAIGN` | Campaign ID passed to `sjctl` / the SOLID.Jobs API (`recruflow`). |
| `APP_ENV` | Application environment name (e.g. `development`). |
| `LOG_LEVEL` | Root log level (e.g. `INFO`). |
| `API_HOST` | Host the FastAPI server binds to. |
| `API_PORT` | Port the FastAPI server binds to. |
| `VITE_API_BASE_URL` | Base URL the frontend uses to reach the API. |
| `CORS_ALLOW_ORIGIN` | Origin the API's CORS middleware allows (must match the URL you browse the frontend at, e.g. `http://localhost:5173` — not `http://127.0.0.1:5173`). |
| `SWARM_GRADE_THRESHOLD` | Minimum Match Score grade a Swarm will send. |
| `SEND_QUEUE_INTER_SEND_DELAY_SECONDS` | Delay between consecutive sends in the Send Queue. |
| `SEND_QUEUE_DAILY_CAP` | Hard daily cap on the number of Applications sent. |
| `FORM_FILL_DAILY_CAP` | Hard daily cap on automated form-fill submissions. |

## Claude Code skills

Skills live under `recruFlow/.claude/skills/` and are invoked as `/<skill-name>` in Claude Code.
Run Claude Code with `recruFlow/` as the working directory so they're picked up.

| Skill | Purpose | Source |
| --- | --- | --- |
| `/grill-with-docs` | Relentless interview to sharpen a plan or design; produces ADRs and a glossary as it goes. Internally runs `/grilling` + `/domain-modeling`. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `/grilling` | The interview mechanic used by `/grill-with-docs`. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `/domain-modeling` | Builds and maintains the `CONTEXT.md` glossary and `docs/adr/` decisions used by `/grill-with-docs`. | [mattpocock/skills](https://github.com/mattpocock/skills) |
| `/jobs-search` | Search SOLID.Jobs offers from a natural-language request. | [solid-company/solid-jobs-skills](https://github.com/solid-company/solid-jobs-skills) |
| `/jobs-evaluate` | Score a cached offer against the candidate profile (A–F grade). | [solid-company/solid-jobs-skills](https://github.com/solid-company/solid-jobs-skills) |
| `/jobs-digest` | Run saved searches (watches) and summarize new offers since the last check. | [solid-company/solid-jobs-skills](https://github.com/solid-company/solid-jobs-skills) |
| `/jobs-track` | Manage the application pipeline (saved → applied → interview → offer/rejected). | [solid-company/solid-jobs-skills](https://github.com/solid-company/solid-jobs-skills) |
| `/jobs-create-profile` | Turn a plain-language description or CV into a stored candidate profile. | [solid-company/solid-jobs-skills](https://github.com/solid-company/solid-jobs-skills) |

The `jobs-*` skills wrap the `sjctl` CLI (see `SJCTL_CAMPAIGN` above) and resolve it from `PATH`,
then `~/.solid-jobs-skills/bin/sjctl`, then a repo-local binary. If `sjctl` or a watch isn't
configured yet, the skill reports that clearly instead of failing silently.

These are vendored copies of upstream `SKILL.md` files. To update them, re-copy the relevant
file(s) from the source repos, or use each repo's own installer for an interactive picker:

```bash
npx skills@latest add mattpocock/skills
npx skills@latest add solid-company/solid-jobs-skills
```

## SOLID.Jobs connector

`app/connectors/solid_jobs.py` ingests offers from SOLID.Jobs via the `sjctl` subprocess into the
canonical `offers` table. It does not create, schedule, or expose itself over HTTP — that's left to
later stories (a scheduler and an ingestion API endpoint). Call it directly with an already-resolved
`Source` row:

```python
from app.connectors.solid_jobs import run_solid_jobs_ingestion

result = await run_solid_jobs_ingestion(session, source, campaign=settings.sjctl_campaign)
# IngestionResult(ok=True, fetched=3, created=2)
await session.commit()
```

`campaign` always comes from `Settings.sjctl_campaign` (`SJCTL_CAMPAIGN` env var, default
`recruflow`) and is passed as `--campaign` on every `sjctl` invocation.

By default (`force_refresh=False`) the connector runs `sjctl sync`, which only reports offers not
already seen by sjctl's own saved watches — no filters, cache-respecting. Pass `force_refresh=True`
to instead run `sjctl search` with filters read from the Source row's `config_json`, bypassing the
cache:

| `config_json` key | sjctl flag | Notes |
| --- | --- | --- |
| `division` | `-d` | Defaults to `IT` if absent |
| `cities` (list) | `--city` (repeated) | |
| `min_salary` | `--min-salary` | |
| `experience_levels` (list) | `--experience` (repeated) | |
| `terms` (list) | `--term` (repeated) | Free-text/technology filter, e.g. `["python"]` |

If the `sjctl` binary is missing, exits non-zero, or returns malformed JSON, the connector logs the
failure and returns `IngestionResult(ok=False, fetched=0, created=0)` rather than raising — it never
crashes the calling ingestion process.

## JustJoin.it connector

`app/connectors/justjoinit.py` ingests offers from JustJoin.it's own JSON API (confirmed live —
see `docs/adr/0003-justjoinit-json-endpoint-investigation.md` — no scraping needed) into the
canonical `offers` table. Like the SOLID.Jobs connector, it does not create, schedule, or expose
itself over HTTP. Call it directly with an already-resolved `Source` row:

```python
from app.connectors.justjoinit import run_justjoinit_ingestion

result = await run_justjoinit_ingestion(session, source)
# IngestionResult(ok=True, fetched=10, created=7)
await session.commit()
```

The connector paginates JustJoin.it's cursor-based offers endpoint, up to a bounded number of
pages per call (looping until the real end of results would mean up to ~100 requests per run at
the API's own default page size, and deep pagination was observed to occasionally fail server-side
— see ARCHITECTURE.md's JustJoin.it connector section). All of the following are read from the
`Source` row's `config_json`, with defaults if absent:

| `config_json` key | Default | Notes |
| --- | --- | --- |
| `endpoint_url` | JustJoin.it's confirmed offers API URL | Override for testing only |
| `page_size` | `100` | Offers requested per page (`itemsCount` query param) |
| `max_pages` | `5` | Upper bound on pages fetched per call — see the known-limitation note in ARCHITECTURE.md |
| `rate_limit_delay_seconds` | `1.0` | Delay between page fetches, for politeness towards JustJoin.it's API |

If the first page fetch fails (network error, non-2xx status, malformed JSON, or an unrecognised
response shape), the connector logs the failure and returns
`IngestionResult(ok=False, fetched=0, created=0)` rather than raising. A failure on a *later* page
(after at least one page already succeeded) stops pagination early but still reports success for
the offers already fetched — it never crashes the calling ingestion process.

## NoFluffJobs connector

`app/connectors/nofluffjobs.py` ingests offers from NoFluffJobs's own JSON API (confirmed live —
see `docs/adr/0004-nofluffjobs-json-endpoint-investigation.md` — no scraping needed) into the
canonical `offers` table. Like the other two connectors, it does not create, schedule, or expose
itself over HTTP. Call it directly with an already-resolved `Source` row:

```python
from app.connectors.nofluffjobs import run_nofluffjobs_ingestion

result = await run_nofluffjobs_ingestion(session, source)
# IngestionResult(ok=True, fetched=191, created=180)
await session.commit()
```

Unlike JustJoin.it's connector, this one does **not** paginate: NoFluffJobs's confirmed endpoint
(`/api/joboffers/main`) was verified to ignore its own `page` query parameter as an offset — every
`page` value returns the same result set — so looping over pages would not surface additional
offers. `pageSize` does control how many postings a single call returns (non-linearly — see
ARCHITECTURE.md's NoFluffJobs connector section), so the connector issues exactly one request per
run, sized by `config_json`:

| `config_json` key | Default | Notes |
| --- | --- | --- |
| `endpoint_url` | NoFluffJobs's confirmed offers API URL | Override for testing only |
| `page_size` | `100` | Requested `pageSize` query param — controls the volume of the single feed pull (observed ~327 postings at the default) |

There is no `rate_limit_delay_seconds` config key for this connector: because ingestion is a single
HTTP request per run, there is nothing to delay between.

If the fetch fails (network error, non-2xx status, malformed JSON, or an unrecognised response
shape), the connector logs the failure and returns `IngestionResult(ok=False, fetched=0,
created=0)` rather than raising — it never crashes the calling ingestion process.

## Scheduler

`app/scheduler/` wires [APScheduler](https://apscheduler.readthedocs.io/) into the FastAPI
lifespan (`app/main.py`) so all three connectors run automatically on their own schedule, plus
exposes a manual trigger and a status endpoint. On every process start, the three built-in sources
(`solid_jobs`, `justjoinit`, `nofluffjobs`) are provisioned idempotently if they don't already
exist — you don't need to run `make seed` first for the scheduler to have something to run against.

### Configuring a source's schedule

Each `sources` row's `config_json` JSONB column carries a reserved `"schedule"` key, alongside that
connector's own filter keys (`division`/`cities`/... for SOLID.Jobs, `page_size`/... for the other
two). Two shapes are supported, a tagged union on `"type"`:

```json
{"schedule": {"type": "interval", "seconds": 3600}}
{"schedule": {"type": "cron", "expression": "0 */2 * * *"}}
```

`expression` is a standard five-field crontab string. To change a source's schedule, update its row
directly (e.g. via `psql` or a future admin UI — there is no `PATCH /sources/{id}` endpoint yet) and
restart the API so `register_jobs` picks up the new trigger; a running scheduler does not hot-reload
config changes mid-process. A missing or malformed `"schedule"` value never crashes the app — it
logs a `WARNING` and falls back to a 1-hour interval.

The three built-in sources ship with these defaults (`app/scheduler/service.py`'s
`DEFAULT_SOURCE_CONFIGS`):

| Source | Schedule |
| --- | --- |
| `solid_jobs` | interval, every 3600s (1 hour) |
| `justjoinit` | interval, every 1800s (30 minutes) |
| `nofluffjobs` | cron, `0 */2 * * *` (every 2 hours, on the hour) |

### `POST /scheduler/run/{source}`

Triggers one source's ingestion immediately, outside its automatic schedule. `{source}` is a
connector identity string (`solid_jobs`, `justjoinit`, or `nofluffjobs`), not `sources.name`.

```bash
curl -X POST http://localhost:8000/scheduler/run/justjoinit
```

```json
{
  "id": 12,
  "source_id": 3,
  "connector": "justjoinit",
  "trigger_type": "manual",
  "status": "ok",
  "fetched": 42,
  "created": 7,
  "warning": false,
  "error_message": null,
  "started_at": "2026-07-03T10:15:00Z",
  "finished_at": "2026-07-03T10:15:04Z"
}
```

Returns `404` only when `{source}` isn't a recognised connector at all, or is a recognised
connector with no provisioned `Source` row — the detail message distinguishes the two. A `200` with
`"status": "error"` means the run itself failed (an unexpected exception from the connector); the
request still succeeded in the sense that a run was triggered and its outcome reported, mirroring
the connectors' own "return `ok=False`/an error result, don't raise" philosophy.

`fetched` vs. `created`: `fetched` is how many offers the connector's request round-trip returned;
`created` is how many of those were genuinely new rows after dedup. `created` reaching `0` on a
healthy, previously-ingested source is normal and expected. `fetched` reaching `0` is the real
signal something's wrong (source unreachable, API contract changed, filters too narrow) — a `0`
`fetched` count sets `"warning": true` and logs a `WARNING`, whether the run was automatic or
manual.

### `GET /scheduler/status`

Reports every provisioned source's configured schedule and last run outcome.

```bash
curl http://localhost:8000/scheduler/status
```

```json
{
  "sources": [
    {
      "source_id": 3,
      "connector": "justjoinit",
      "name": "justjoinit",
      "schedule": {"type": "interval", "seconds": 1800},
      "last_run_id": 12,
      "last_run_started_at": "2026-07-03T10:15:00Z",
      "last_run_finished_at": "2026-07-03T10:15:04Z",
      "last_run_status": "ok",
      "last_run_trigger_type": "manual",
      "last_run_fetched": 42,
      "last_run_created": 7,
      "last_run_warning": false,
      "last_run_error_message": null
    }
  ]
}
```

All `last_run_*` fields are `null`/`false` for a source that has never run yet. A source with
`connector` unset (e.g. `seed.py`'s `"seed"` fixture row) is not scheduled and does not appear here.

## Ingestion API

`POST /ingest/{source}`, `GET /offers`, and `GET /offers/{offer_id}` let a job seeker force an
out-of-band fetch and browse what's been ingested, outside the automatic schedule described above.

### `POST /ingest/{source}`

Triggers one source's ingestion immediately. `{source}` is a connector identity string
(`solid_jobs`, `justjoinit`, or `nofluffjobs`), not `sources.name`. Unlike
`POST /scheduler/run/{source}`, this does not write to the scheduler's `scheduler_runs` audit
trail — `GET /scheduler/status` will not reflect a run triggered this way.

```bash
curl -X POST http://localhost:8000/ingest/justjoinit
```

```json
{"source": "justjoinit", "ok": true, "fetched": 5, "created": 3, "error_message": null}
```

Returns `404` only when `{source}` isn't a recognised connector at all, or is a recognised
connector with no provisioned `Source` row. A `200` with `"ok": false` means the run itself failed
(an unexpected exception from the connector); the request still succeeded in the sense that a run
was triggered and its outcome reported.

### `GET /offers`

Lists stored offers, newest ingestion first is not guaranteed — no ordering is applied. Supports
filtering by query parameter, all combinable (AND semantics):

| Param | Meaning |
| --- | --- |
| `source` | Connector identity (`justjoinit`, `solid_jobs`, `nofluffjobs`) — exact match |
| `remote` | `true`/`false` |
| `seniority` | Canonical level (`junior`/`mid`/`senior`/`lead`/`expert`) — substring match |
| `min_salary` | Minimum salary (PLN, monthly gross); an offer's `salary_max` must meet or exceed it, falling back to `salary_min` when `salary_max` is unknown |
| `grade` | Single-letter match grade (A–F); matches if any `MatchScore` row for the offer has it (table is empty until Phase 3 ships a scorer) |

```bash
curl "http://localhost:8000/offers?source=justjoinit&remote=true&min_salary=15000"
```

```json
[
  {
    "id": 42,
    "source": "justjoinit",
    "external_id": "abc123",
    "canonical_url": "https://justjoin.it/offers/abc123",
    "title": "Senior Backend Engineer",
    "company": "Acme",
    "location": "Warsaw",
    "remote": true,
    "seniority": "senior, lead",
    "salary_min": 18000,
    "salary_max": 25000,
    "salary_currency": "PLN",
    "contract_type": "B2B",
    "posted_at": "2026-06-20T09:00:00Z",
    "created_at": "2026-06-21T08:00:00Z"
  }
]
```

An unrecognised `source` value returns `200` with an empty list, not an error — standard filtering
behaviour, distinct from `POST /ingest/{source}`'s strict 404 on an unknown connector.

### `GET /offers/{offer_id}`

```bash
curl http://localhost:8000/offers/42
```

Same fields as the list endpoint, plus `description`, `raw_payload` (the original ELT payload
stored at ingest time), and `updated_at`. Returns `404` with a clear message for an unknown id:

```json
{"detail": "offer 999999999 not found"}
```

## Offer list page

With `make up` running, open `http://localhost:5173` to browse ingested offers without calling
the API directly.

- **Filters** — source, remote, seniority, and minimum salary. Each control updates `GET /offers`
  with the corresponding query parameter as soon as it changes; combining filters is AND
  semantics (same as the API itself). Leaving a filter at its default (`All sources`/`Any`/blank)
  omits that query parameter entirely.
- **Fetch now** — one button per known source (SOLID.Jobs, JustJoin.it, NoFluffJobs), each calling
  `POST /ingest/{source}` independently. A button shows `Fetching...` (disabled) while its request
  is in flight, then a short `"Fetched N, M new"` summary, and refreshes the table on success. The
  three buttons never block each other.
- **Empty state** — if no offers match the current filters (or none have been ingested yet), the
  table is replaced with a short message instead of rendering an empty grid.
- Offers are sorted newest-first by posted date on the client, since `GET /offers` itself applies
  no ordering.
