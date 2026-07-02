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
for the full schema. `make seed` loads a handful of sample offers and a stub profile; both
commands are safe to re-run.

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
```

TypeScript strict mode is enabled (`tsconfig.app.json` / `tsconfig.node.json`), and styling is
done exclusively with Tailwind CSS utility classes.

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
| `SWARM_GRADE_THRESHOLD` | Minimum Match Score grade a Swarm will send. |
| `SEND_QUEUE_INTER_SEND_DELAY_SECONDS` | Delay between consecutive sends in the Send Queue. |
| `SEND_QUEUE_DAILY_CAP` | Hard daily cap on the number of Applications sent. |
| `FORM_FILL_DAILY_CAP` | Hard daily cap on automated form-fill submissions. |
