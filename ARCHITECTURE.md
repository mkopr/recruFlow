# Architecture

## Repository layout

```
recruFlow/
├── app/            # Python application package (P0US4 added a /health stub; P0US6 adds the rest)
│   ├── main.py     # FastAPI app object: loads Settings, wires routers (P0US6)
│   ├── config.py   # Settings(BaseSettings) + get_settings(), env-driven (.env) (P0US6)
│   ├── api/        # HTTP layer: DI dependencies and routers (P0US6)
│   │   ├── deps.py         # get_db() session dependency, SessionDep annotation
│   │   └── routes/
│   │       └── health.py   # GET /health, GET /health/db
│   └── db/         # SQLAlchemy models, async engine/session, Alembic-shared base (P0US5)
│       ├── base.py     # Declarative base, shared by models.py and alembic/env.py
│       ├── models.py   # v1 schema: Source, Offer, Profile, CVVersion, MatchScore, Application
│       ├── session.py  # get_engine()/get_sessionmaker(), env-driven (DATABASE_URL)
│       └── seed.py     # idempotent fixture loader (make seed)
├── alembic/        # Migration environment (async template) (P0US5)
│   └── versions/   # Migration scripts; v1 schema migration creates all six tables
├── alembic.ini     # Alembic config; sqlalchemy.url left unset, injected by env.py at runtime
├── frontend/       # React + Vite + TypeScript frontend (P0US2)
│   ├── src/        # App source (main.tsx, App.tsx, index.css, vite-env.d.ts)
│   ├── nginx.conf  # SPA server block for the production Docker image (P0US4)
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json       # references-only root config
│   ├── tsconfig.app.json   # strict app config (src/)
│   ├── tsconfig.node.json  # config for vite.config.ts (node context)
│   ├── vite.config.ts
│   └── eslint.config.js
├── tests/          # Unit tests (pure filesystem/import checks, no external services)
│   └── integration/  # Tests requiring external services (DB, Ollama, sjctl, ...)
├── pyproject.toml
├── uv.lock
├── Makefile
├── .pre-commit-config.yaml
├── .env.example
├── .gitignore
├── Dockerfile            # multi-stage: builder (uv sync) -> runtime (uvicorn + sjctl)
├── Dockerfile.frontend   # multi-stage: dev (Vite dev server) -> build -> production (nginx)
├── .dockerignore
└── docker-compose.yml    # api, frontend, db, ollama — each with a health check
```

### Dependency groups (`pyproject.toml`)

- `main` — runtime dependencies of the FastAPI application: `fastapi`, `uvicorn`, the async
  SQLAlchemy stack (`sqlalchemy[asyncio]`, `asyncpg`), `alembic`, `pydantic`,
  `pydantic-settings`. Later phases add further runtime deps here incrementally
  (`langchain`/`langgraph`/`langchain-ollama` in P3US2, `playwright` in P5US6,
  `weasyprint`/`python-docx` in P4US4/P6US4) as the story that needs them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `httpx`, `pytest-cov`.

`[tool.ruff.lint]`'s `select` list adds `C90` (P0US8), enabling ruff's `mccabe`
cyclomatic-complexity checker, with `[tool.ruff.lint.mccabe] max-complexity = 10` — 10 is
SonarQube's own default cyclomatic-complexity threshold, and the closest available proxy for
"SonarQube standard" without adding a new dependency (ruff has no cognitive-complexity metric).
`frontend/eslint.config.js` sets the matching `complexity: ['error', 10]` rule so both stacks
enforce the same threshold.

### `app/` package

Exposes `__version__` (P0US1). As of P0US6, `app/main.py` is the real application entrypoint:

```python
settings = get_settings()
app = FastAPI(title="recruFlow API", version=__version__)
app.state.settings = settings
app.include_router(health_router)
```

`app/main.py` calls `get_settings()` once at import time — a missing/invalid `.env` (e.g. no
`DATABASE_URL`) fails the process at startup rather than on the first request, matching
`app/db/session.py`'s "fail loudly" precedent. `settings` is stashed on `app.state.settings` so
future routers can read it via `request.app.state.settings` without importing the module-level
singleton directly. `/docs` (Swagger UI) and `/openapi.json` require no extra configuration —
they are FastAPI defaults, enabled automatically once the `FastAPI()` app object exists.

### `app/config.py` (P0US6)

`Settings(BaseSettings)` (Pydantic v2, `pydantic-settings`) — one field per backend-relevant key
in `.env.example` (`database_url`, `ollama_base_url`, `ollama_model`, `smtp_*`, `sjctl_campaign`,
`app_env`, `log_level`, `api_host`, `api_port`). `model_config = SettingsConfigDict(env_file=".env",
extra="ignore")`: `extra="ignore"` because `.env` also carries frontend-only (`VITE_API_BASE_URL`)
and P5-only (`SWARM_*`, `SEND_QUEUE_*`, `FORM_FILL_*`) keys this model doesn't represent yet — those
fields get added by the story that first needs them. `database_url`, `ollama_base_url`, and
`ollama_model` have no default, so `Settings()` raises `pydantic.ValidationError` if they're unset,
mirroring `get_database_url()`'s fail-loud behaviour. `get_settings()` is `functools.lru_cache`d so
`.env` is parsed once per process, not once per request.

`pyproject.toml`'s `[tool.mypy]` enables `plugins = ["pydantic.mypy"]` — without it, strict mypy
cannot see Pydantic's dynamically generated `__init__` and flags every field-less `Settings()` call
as a missing-argument error, even though those fields are populated from the environment at
runtime, not from constructor arguments.

### `app/api/` package (P0US6)

- `deps.py` — `get_db() -> AsyncGenerator[AsyncSession, None]`, an async-generator FastAPI
  dependency built directly on `app.db.session.get_sessionmaker()` (no independent connection
  string derivation — `DATABASE_URL` stays the single source of truth). The `async_sessionmaker`
  itself is built once per process via an `lru_cache`d `_get_sessionmaker()`, so a fresh engine
  isn't constructed per request. `SessionDep = Annotated[AsyncSession, Depends(get_db)]` is the
  reusable DI annotation every endpoint needing a DB session should depend on (e.g.
  `async def handler(session: SessionDep) -> ...`) — the modern FastAPI idiom, required here
  because strict mypy with no FastAPI plugin doesn't type-check the older
  `session: AsyncSession = Depends(get_db)` default-value style cleanly.
- `routes/health.py` — `GET /health` (unchanged contract: `{"status": "ok"}`, no dependencies) and
  `GET /health/db` (depends on `SessionDep`, runs `SELECT 1` through the injected session). On a
  DB failure `GET /health/db` returns `503 Service Unavailable` with
  `{"detail": "database unavailable"}` rather than an unhandled 500 — 503 signals "a downstream
  dependency is unreachable", distinct from an application bug. The except clause catches both
  `sqlalchemy.exc.SQLAlchemyError` (query-time failures on an already-open connection, which
  SQLAlchemy wraps) and `OSError` (e.g. `ConnectionRefusedError`) — connection-establishment
  failures on the *first* use of a session are not wrapped by SQLAlchemy and propagate as the raw
  driver/socket exception, so both cases must be caught explicitly.

### `app/db/` package (P0US5)

- `base.py` — a single `Base(DeclarativeBase)` that every ORM model and Alembic's
  `target_metadata` share, so migrations autogenerate off the same metadata the app queries
  against.
- `models.py` — the six v1 tables (see "Database schema" below).
- `session.py` — `get_database_url() -> str` (reads `DATABASE_URL`, raises `RuntimeError` if
  unset — fails loudly rather than silently defaulting to the wrong database),
  `get_engine() -> AsyncEngine`, `get_sessionmaker(engine: AsyncEngine | None = None) ->
  async_sessionmaker[AsyncSession]`. No FastAPI dependency lives here — P0US6 builds its `get_db`
  dependency directly on top of `get_sessionmaker()`, so this module is the single reusable
  entrypoint for both Alembic and the application.
- `seed.py` — `run_seed(session: AsyncSession) -> None`, used by `make seed`. Uses Postgres
  `INSERT ... ON CONFLICT DO NOTHING` keyed on each table's natural unique column (`sources.name`,
  `offers.dedup_hash`, `profiles.name`) so it is safe to re-run.

## Database schema (P0US5)

Alembic (async template) is wired to `app/db/base.py`'s `Base.metadata` via `alembic/env.py`,
which reads `DATABASE_URL` from the environment at runtime rather than from `alembic.ini` (kept
blank) — matching `.env.example`, one source of truth for the connection string. The v1 migration
creates all six tables spanning every phase's domain nouns up front, so no later phase needs a
repeated foundational migration:

| Table | Purpose | Key columns / constraints |
| --- | --- | --- |
| `sources` | A job board connector (SOLID.Jobs, JustJoin.it, NoFluffJobs) | `name` unique; `config_json` (JSONB) per-source config |
| `offers` | A normalised job posting with exactly one Source | `dedup_hash` unique + indexed (dedup on canonical URL, P1US1 fallback to title+company+location); `raw_payload` (JSONB, ELT raw payload always populated at ingest) |
| `profiles` | Candidate's structured facts: skills, experience, preferences | `name` unique; `is_active` (only one row active at a time, enforced by application logic, not a DB constraint); `data` (JSONB) |
| `cv_versions` | Tailored CV + cover letter drafted for one Offer/Profile pair | FKs to `offers`/`profiles`; `status` string (no DB enum, so later statuses need no migration) |
| `match_scores` | Structured evaluation of one Offer against a Profile (grade A–F + dimensions) | FKs to `offers`/`profiles`; `engine` distinguishes LangChain vs. `sjctl` scoring |
| `applications` | Record of intent/action to apply | FKs to `offers`/`profiles`/`cv_versions`; `status` one of `drafted`/`reviewed`/`sent`/`failed`/`interview`/`offer`/`rejected` (unconstrained string, not a DB enum) |

`make migrate` runs `docker compose exec api alembic upgrade head` (mirrors the `sjctl-version`
pattern — `DATABASE_URL`'s `db` hostname only resolves inside the Compose network, not from the
host). `make seed` runs `docker compose exec api python -m app.db.seed`, loading three sample
offers and one active stub profile; both targets are idempotent.

### `frontend/` project

React + Vite + TypeScript, styled with Tailwind CSS, managed with `pnpm`.

- **TypeScript project references**: `tsconfig.json` is a references-only root (`files: []`)
  pointing at `tsconfig.app.json` (strict, browser `lib`, covers `src/`) and
  `tsconfig.node.json` (covers `vite.config.ts`, which runs in a Node context with different
  `lib`/`module` needs). This mirrors the official Vite React-TS template so editor tooling and
  build-time config type-check independently of app source.
- **Tailwind CSS v4**: wired via the `@tailwindcss/vite` plugin in `vite.config.ts` — no
  `tailwind.config.js` or `postcss.config.js`; content scanning is automatic and Tailwind is
  enabled by a single `@import "tailwindcss";` in `src/index.css`.
- **ESLint flat config** (`eslint.config.js`): `@eslint/js` recommended +
  `typescript-eslint` recommended + `eslint-plugin-react-hooks` +
  `eslint-plugin-react-refresh`, with `eslint-config-prettier` applied last so no ESLint
  stylistic rule conflicts with Prettier. `dist` is excluded via `ignores` so a local
  `pnpm build` doesn't break `pnpm lint`.
- **Prettier** (`.prettierrc.json`): `printWidth: 100` to mirror the Python side's
  `ruff` line-length 100.
- `pnpm-lock.yaml` is committed, same reproducible-install precedent as `uv.lock`.
- **`src/api/` directory (P0US7)**: `schema.d.ts` is generated by `make generate-types` from the
  live `/openapi.json` and committed to source control, since CI has no running API to regenerate
  it from. `client.ts` is the shared `openapi-fetch` client (`apiClient`), typed against
  `schema.d.ts`'s `paths` export — every future frontend feature reuses this single client rather
  than hand-rolling `fetch()` calls with hand-written response types.

### Makefile targets

- `install` — `uv sync --all-groups` + `cd frontend && pnpm install`.
- `format` — `uv run ruff format .` + `cd frontend && pnpm format`.
- `lint` — `uv run ruff check .` + `uv run mypy .` + `cd frontend && pnpm lint`.
- `typecheck` — `uv run mypy .` + `cd frontend && pnpm run typecheck` (`tsc -b`, i.e. build mode
  — plain `tsc --noEmit` is a no-op against the references-only root `tsconfig.json`, since it
  has `files: []` and only `-b`/`--build` traverses `references`; fixed in P0US7 after discovering
  `pnpm run typecheck` was silently passing regardless of real type errors in `src/`).
- `test` / `test-unit` / `test-integration` — `uv run pytest`, scoped by the `integration`
  marker. Python-only; no frontend test runner is in scope yet.
- `ci` — runs `format lint typecheck test` in sequence; now covers both stacks since `lint`,
  `format`, and `typecheck` each fan out to the frontend toolchain.
- `clean` — removes `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`,
  `build`.
- `up` — `docker compose up --build`; brings up all four Compose services with hot reload for
  `api` and `frontend` (P0US4).
- `sjctl-version` — `docker compose exec api sjctl version`; prints the `sjctl` binary version
  installed inside the `api` container (P0US4).
- `migrate` — `docker compose exec api alembic upgrade head` (P0US5).
- `seed` — `docker compose exec api python -m app.db.seed` (P0US5).
- `generate-types` — `cd frontend && pnpm run generate-types`, which runs `openapi-typescript`
  against `http://localhost:8000/openapi.json` and writes `frontend/src/api/schema.d.ts` (P0US7).
  Requires the API to already be running (`make up`). Its output is committed to source control
  — CI does not start the API, so it never regenerates this file itself — and must be re-run
  manually after any API contract change.

- `install` now also runs `uv run pre-commit install` after the dependency/frontend install
  steps, registering the git hooks defined in `.pre-commit-config.yaml`.

### Pre-commit hooks (`.pre-commit-config.yaml`)

Hook definitions live in `.pre-commit-config.yaml`. Every hook except `trailing-whitespace`
(from the upstream `pre-commit/pre-commit-hooks` repo) is a `local` hook with
`language: system`, calling the same commands `make lint` / `make format` / `make typecheck`
already use (`uv run --frozen ruff check --fix`, `uv run --frozen ruff format`,
`pnpm exec eslint . --fix`, `uv run --frozen mypy .`) plus two lockfile-sync checks
(`uv lock --check`, `pnpm install --frozen-lockfile`). Using the project's own
uv/pnpm-managed toolchain instead of hosted mirrors (e.g. `astral-sh/ruff-pre-commit`,
`mirrors-mypy`) means pre-commit and `make ci` can never disagree about tool versions.
`--frozen` is required on every `uv run` hook: by default `uv run` auto-syncs the environment
before running, which silently rewrites `uv.lock` to match `pyproject.toml` — that would mask
real drift before the `uv-lock-check` hook ever runs. `--frozen` runs against the lock file
as committed, so `uv-lock-check` is the sole source of truth on lock/pyproject sync. Hooks
are ordered so auto-fixers run before non-fixable checks, per the "auto fix before check"
requirement.

## Docker Compose services (P0US4)

`docker-compose.yml` defines four services, brought up together by `make up`. Service names,
ports, and credentials match `.env.example` exactly.

| Service | Image / build target | Port | Healthcheck |
| --- | --- | --- | --- |
| `api` | `Dockerfile` target `runtime` | 8000 | `curl -f http://localhost:8000/health` |
| `frontend` | `Dockerfile.frontend` target `dev` | 5173 | `wget --spider http://localhost:5173` |
| `db` | `postgres:16-alpine` | 5432 | `pg_isready -U recruflow -d recruflow` |
| `ollama` | `ollama/ollama:latest` | 11434 | `ollama list` |

Notes:

- `api` and `frontend` bind-mount their source directories (`./app`, `./frontend`) so
  `uvicorn --reload` and the Vite dev server pick up local edits without a container rebuild.
  `frontend` also declares an anonymous volume on `/app/node_modules` so the host bind mount
  doesn't shadow the dependencies installed inside the image.
- `api` depends on `db` with `condition: service_healthy`, so it won't start accepting
  connections until Postgres is actually ready.
- `db` and `ollama` persist state in named volumes (`pgdata`, `ollama_data`) so data survives
  `docker compose down` (but not `docker compose down -v`).
- The `Dockerfile` multi-stage build installs `sjctl` (the SOLID.Jobs CLI) into the `runtime`
  stage via its official install script
  (`scripts/install-sjctl.sh` from `solid-company/solid-jobs-skills`), with cosign signature
  verification skipped (`SJCTL_SKIP_COSIGN=1`, since `cosign` isn't installed in this image) —
  the script still verifies the release asset's sha256 checksum. `make sjctl-version` runs
  `sjctl version` inside the running `api` container.
- `Dockerfile.frontend` has three stages: `dev` (Vite dev server, used by `docker-compose.yml`),
  `build` (`pnpm build`, produces `frontend/dist`), and `production` (nginx serving the built
  static assets via `frontend/nginx.conf`, an SPA fallback for client-side routing added in
  later phases). Only `dev` is wired into Compose today; `production` is built but not yet
  deployed anywhere.

## CI (GitHub Actions) (P0US8)

`.github/workflows/ci.yml` defines a single workflow with a single job, triggered on every
`pull_request` and every `push` to `main`. Rather than re-implementing `ruff check`, `mypy`,
`pytest`, `eslint`, and TypeScript type-checking as separate `run:` steps, the job's final step
is `make ci` — the same target developers already run locally (`format lint typecheck test`, in
that order, `format`'s auto-fixers running before the non-fixable `lint`/`typecheck` gates). This
guarantees local `make ci` and the GitHub Actions run can never drift apart, the same rationale
`.pre-commit-config.yaml` uses for calling Make-equivalent commands directly (see "Pre-commit
hooks" above) instead of hosted-mirror actions.

Supporting setup, in order:

- **Postgres service container**: `services.postgres` uses `postgres:16-alpine` with
  `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` all `recruflow`, port `5432`, and a
  `pg_isready -U recruflow -d recruflow` health check — an exact mirror of `docker-compose.yml`'s
  `db` service, so there is only one definition of "a correctly configured recruFlow Postgres"
  across local dev and CI. GitHub Actions service containers publish to `localhost` on the
  runner (not a Compose network hostname), so the job-level `DATABASE_URL` points at
  `localhost:5432` — this happens to be the exact same default `tests/integration/conftest.py`
  falls back to when `DATABASE_URL` is unset.
- **Dependency install**: `astral-sh/setup-uv@v6` (pinned to `0.11.23`, the version in local use)
  + `uv sync --all-groups --frozen` (`--frozen` fails loudly on lockfile drift instead of
  rewriting `uv.lock`, the same rationale pre-commit's `uv-lock-check` hook relies on), then
  `pnpm/action-setup@v4` + `actions/setup-node@v4` + `pnpm install --frozen-lockfile` in
  `frontend/` (mirrors the `pnpm-lock-check` pre-commit hook exactly).
- **Settings env vars**: `app/main.py` calls `get_settings()` at import time, and `Settings` has
  no defaults for `database_url`, `ollama_base_url`, or `ollama_model` (see "`app/config.py`"
  above) — any process importing `app.main` without these set raises `pydantic.ValidationError`
  before a single test runs. The workflow copies `.env.example` to `.env` (`cp .env.example
  .env`) so every other Settings field has a valid placeholder, then sets `DATABASE_URL`,
  `OLLAMA_BASE_URL`, and `OLLAMA_MODEL` at the job level — `pydantic-settings` gives explicit
  environment variables precedence over the same key in `.env`, so the job-level `DATABASE_URL`
  (pointing at `localhost`) overrides `.env.example`'s Compose-network value (`db:5432`) without
  editing the copied file.
- **`tsc --noEmit` vs. `tsc -b`**: the story's acceptance criteria literally says "runs ... `tsc
  --noEmit`", but as documented above under "Makefile targets", plain `tsc --noEmit` silently
  no-ops against this project's references-only root `tsconfig.json` (the P0US7 discovery). The
  workflow does not invoke `tsc --noEmit` directly — it gets type-checking for free through
  `make ci` → `typecheck` → `pnpm run typecheck` (`tsc -b`), which is the only command that
  actually traverses `frontend/tsconfig.json`'s `references` and catches real TypeScript errors.
  Implementing the AC literally would make the "CI fails on type error" scenario silently pass.
- **README badge**: deferred — this repository has no GitHub remote configured yet (`git remote
  -v` returns nothing), so there is no `owner/repo` to build a badge URL from. README documents
  the CI workflow's behavior and notes the badge is pending a remote.
