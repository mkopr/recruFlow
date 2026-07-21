# Architecture

This file covers foundational, rarely-changing structure: repo layout, dependency groups, and
the core `app/` package (config, DI). Everything else lives under `docs/architecture/`, split by
subsystem so a story touching one area doesn't require reading the whole architecture doc:

- [Database schema](docs/architecture/database.md) — `app/db/` package, the six v1 tables + `scheduler_runs`
- [Ingestion pipeline](docs/architecture/ingestion.md) — Offer schema/dedup, scheduler, ingestion API, CORS, dead letter queues, fetch-range/auto-fetch toggle, connector registry/extensibility
- [Connectors](docs/architecture/connectors.md) — one file per job board connector (SOLID.Jobs, JustJoin.it, NoFluffJobs, Bulldogjob, Rocket Jobs, Pracuj.pl, RemoteOK, Remotive, We Work Remotely) + the failed The Protocol spike
- [Profile](docs/architecture/profile.md) — profile data model, CV upload + LLM extraction, profile editor page
- [Matching](docs/architecture/matching.md) — Match Score schema, LangChain Matcher, batch scoring job, grade thresholds
- [Offer list & frontend](docs/architecture/frontend.md) — offer list page, scores, applied/hide/notes, highlight, connector settings sub-pages
- [Deployment & CI](docs/architecture/deployment.md) — Makefile targets, pre-commit hooks, Docker Compose services, GitHub Actions CI

When a story changes a subsystem, update that subsystem's file, not this one — this file should only
change when the repo layout, dependency groups, or the core `app/` package itself changes.

## Repository layout

```
recruFlow/
├── app/            # Python application package
│   ├── main.py     # FastAPI app object: loads Settings, lifespan-wires the scheduler
│   ├── config.py   # Settings(BaseSettings) + get_settings(), env-driven (.env)
│   ├── api/        # HTTP layer: DI dependencies and routers
│   │   ├── deps.py         # get_db() session dependency, SessionDep annotation
│   │   └── routes/
│   │       ├── health.py     # GET /health, GET /health/db
│   │       └── scheduler.py  # POST /scheduler/run/{source}, GET /scheduler/status
│   ├── cv/         # CV file parsing: extract_cv_text() (PDF/DOCX -> plain text)
│   ├── llm/        # LLM invocation: extract_profile_from_cv_text() (Ollama call boundary)
│   ├── db/         # SQLAlchemy models, async engine/session, Alembic-shared base
│   │   ├── base.py     # Declarative base, shared by models.py and alembic/env.py
│   │   ├── models.py   # v1 schema + SchedulerRun: Source, Offer, Profile, CVVersion, MatchScore, Application, SchedulerRun
│   │   ├── session.py  # get_engine()/get_sessionmaker(), env-driven (DATABASE_URL)
│   │   └── seed.py     # idempotent fixture loader (make seed)
│   ├── schemas/
│   │   └── scheduler.py  # ManualRunResponse, SourceStatus, SchedulerStatusResponse
│   ├── ingestion/  # ELT pipeline + dispatch seam
│   │   └── registry.py  # CONNECTOR_REGISTRY dispatch seam; dispatch_ingestion, resolve_source_by_connector
│   └── scheduler/  # APScheduler wiring only
│       ├── triggers.py   # parse_schedule(): config_json["schedule"] -> APScheduler trigger, fail-soft
│       ├── runs.py       # SchedulerRun row read/write helpers (start_run, finish_run_ok/error, get_latest_run_by_source)
│       ├── service.py    # ensure_sources_exist, run_source_sync (plain def, see ADR 0005), run_source
│       └── lifecycle.py  # register_jobs(): one AsyncIOScheduler job per connector-tagged Source
├── alembic/        # Migration environment (async template)
│   └── versions/   # Migration scripts; v1 schema migration creates all six tables, a later migration adds a seventh
├── alembic.ini     # Alembic config; sqlalchemy.url left unset, injected by env.py at runtime
├── frontend/       # React + Vite + TypeScript frontend
│   ├── src/        # App source (main.tsx, App.tsx, index.css, vite-env.d.ts)
│   ├── nginx.conf  # SPA server block for the production Docker image
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json       # references-only root config
│   ├── tsconfig.app.json   # strict app config (src/)
│   ├── tsconfig.node.json  # config for vite.config.ts (node context)
│   ├── vite.config.ts
│   └── eslint.config.js
├── tests/          # Unit tests (pure filesystem/import checks, no external services)
│   └── integration/  # Tests requiring external services (DB, Ollama, ...)
├── pyproject.toml
├── uv.lock
├── Makefile
├── .pre-commit-config.yaml
├── .env.example
├── .gitignore
├── Dockerfile            # multi-stage: builder (uv sync) -> runtime (uvicorn)
├── Dockerfile.frontend   # multi-stage: dev (Vite dev server) -> build -> production (nginx)
├── .dockerignore
└── docker-compose.yml    # api, frontend, db, ollama — each with a health check
```

### Dependency groups (`pyproject.toml`)

- `main` — runtime dependencies of the FastAPI application: `fastapi`, `uvicorn`, the async
  SQLAlchemy stack (`sqlalchemy[asyncio]`, `asyncpg`), `alembic`, `pydantic`,
  `pydantic-settings`, `httpx`, `apscheduler`, `langchain-ollama`, `langchain-core`, `pypdf`,
  `python-docx`, `python-multipart` (the last five added for CV upload + LLM
  extraction — see below). Later phases add further runtime deps here incrementally (full
  `langchain`/`langgraph` orchestration in Phase 3, `playwright` in Phase 5) as the story that needs
  them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`, `reportlab` (added
  solely to synthesize tiny real PDF fixtures in tests — never imported from `app/`).

`httpx` moved from `test`-only to `main` when the JustJoin.it connector was added: it previously only
backed FastAPI's `TestClient` in tests, but `app/connectors/justjoinit.py` is production code that
imports it directly as its HTTP client.

`apscheduler` (`>=3.10`, the 3.x line — 4.x is alpha-only and not used) was added to `main` for
the ingestion scheduler. `apscheduler` ships no `py.typed` marker, so
`[[tool.mypy.overrides]]` sets `ignore_missing_imports = true` for `apscheduler.*` — every
`apscheduler` import elsewhere in `app/` is otherwise fully type-checked as normal, this only
suppresses the "missing library stubs" note on the import itself.

`[tool.ruff.lint]`'s `select` list adds `C90`, enabling ruff's `mccabe`
cyclomatic-complexity checker, with `[tool.ruff.lint.mccabe] max-complexity = 10` — 10 is
SonarQube's own default cyclomatic-complexity threshold, and the closest available proxy for
"SonarQube standard" without adding a new dependency (ruff has no cognitive-complexity metric).
`frontend/eslint.config.js` sets the matching `complexity: ['error', 10]` rule so both stacks
enforce the same threshold.

### `app/` package

Exposes `__version__`. `app/main.py` is the real application entrypoint:

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

### `app/config.py`

`Settings(BaseSettings)` (Pydantic v2, `pydantic-settings`) — one field per backend-relevant key
in `.env.example` (`database_url`, `ollama_base_url`, `ollama_model`, `smtp_*`, `solid_jobs_campaign`,
`app_env`, `log_level`, `api_host`, `api_port`). `model_config = SettingsConfigDict(env_file=".env",
extra="ignore")`: `extra="ignore"` because `.env` also carries frontend-only (`VITE_API_BASE_URL`)
and later-phase-only (`SWARM_*`, `SEND_QUEUE_*`, `FORM_FILL_*`) keys this model doesn't represent yet — those
fields get added by the story that first needs them. `database_url`, `ollama_base_url`, and
`ollama_model` have no default, so `Settings()` raises `pydantic.ValidationError` if they're unset,
mirroring `get_database_url()`'s fail-loud behaviour. `get_settings()` is `functools.lru_cache`d so
`.env` is parsed once per process, not once per request.

`pyproject.toml`'s `[tool.mypy]` enables `plugins = ["pydantic.mypy"]` — without it, strict mypy
cannot see Pydantic's dynamically generated `__init__` and flags every field-less `Settings()` call
as a missing-argument error, even though those fields are populated from the environment at
runtime, not from constructor arguments.

### `app/api/` package

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
