# Architecture

## Repository layout

```
recruFlow/
├── app/            # Python application package (P0US4 added a /health stub; P0US6 adds the rest)
│   ├── main.py     # FastAPI app object: loads Settings, lifespan-wires the scheduler (P0US6, P1US6)
│   ├── config.py   # Settings(BaseSettings) + get_settings(), env-driven (.env) (P0US6)
│   ├── api/        # HTTP layer: DI dependencies and routers (P0US6)
│   │   ├── deps.py         # get_db() session dependency, SessionDep annotation
│   │   └── routes/
│   │       ├── health.py     # GET /health, GET /health/db
│   │       └── scheduler.py  # POST /scheduler/run/{source}, GET /scheduler/status (P1US6)
│   ├── cv/         # CV file parsing: extract_cv_text() (PDF/DOCX -> plain text) (P2US2)
│   ├── llm/        # LLM invocation: extract_profile_from_cv_text() (Ollama call boundary) (P2US2)
│   ├── db/         # SQLAlchemy models, async engine/session, Alembic-shared base (P0US5)
│   │   ├── base.py     # Declarative base, shared by models.py and alembic/env.py
│   │   ├── models.py   # v1 schema + SchedulerRun (P1US6): Source, Offer, Profile, CVVersion, MatchScore, Application, SchedulerRun
│   │   ├── session.py  # get_engine()/get_sessionmaker(), env-driven (DATABASE_URL)
│   │   └── seed.py     # idempotent fixture loader (make seed)
│   ├── schemas/
│   │   └── scheduler.py  # ManualRunResponse, SourceStatus, SchedulerStatusResponse (P1US6)
│   ├── ingestion/  # ELT pipeline + dispatch seam (P1US1-7, BUG04)
│   │   └── registry.py  # CONNECTOR_REGISTRY dispatch seam; dispatch_ingestion, resolve_source_by_connector
│   └── scheduler/  # APScheduler wiring only (P1US6, BUG04)
│       ├── triggers.py   # parse_schedule(): config_json["schedule"] -> APScheduler trigger, fail-soft
│       ├── runs.py       # SchedulerRun row read/write helpers (start_run, finish_run_ok/error, get_latest_run_by_source)
│       ├── service.py    # ensure_sources_exist, run_source_sync (plain def, see ADR 0005), run_source
│       └── lifecycle.py  # register_jobs(): one AsyncIOScheduler job per connector-tagged Source
├── alembic/        # Migration environment (async template) (P0US5)
│   └── versions/   # Migration scripts; v1 schema migration creates all six tables, P1US6 adds a seventh
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
  `python-docx`, `python-multipart` (the last five added in P2US2 for CV upload + LLM
  extraction — see below). Later phases add further runtime deps here incrementally (full
  `langchain`/`langgraph` orchestration in P3US2, `playwright` in P5US6) as the story that needs
  them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`, `reportlab` (added in
  P2US2 solely to synthesize tiny real PDF fixtures in tests — never imported from `app/`).

`httpx` moved from `test`-only to `main` in P1US3 (the JustJoin.it connector): it previously only
backed FastAPI's `TestClient` in tests, but `app/connectors/justjoinit.py` is production code that
imports it directly as its HTTP client.

`apscheduler` (`>=3.10`, the 3.x line — 4.x is alpha-only and not used) was added to `main` in
P1US6 for the ingestion scheduler. `apscheduler` ships no `py.typed` marker, so
`[[tool.mypy.overrides]]` sets `ignore_missing_imports = true` for `apscheduler.*` — every
`apscheduler` import elsewhere in `app/` is otherwise fully type-checked as normal, this only
suppresses the "missing library stubs" note on the import itself.

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
in `.env.example` (`database_url`, `ollama_base_url`, `ollama_model`, `smtp_*`, `solid_jobs_campaign`,
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
- `models.py` — the six v1 tables plus `scheduler_runs` (P1US6, see "Database schema" below).
- `session.py` — `get_database_url() -> str` (reads `DATABASE_URL`, raises `RuntimeError` if
  unset — fails loudly rather than silently defaulting to the wrong database),
  `get_engine() -> AsyncEngine`, `get_sessionmaker(engine: AsyncEngine | None = None) ->
  async_sessionmaker[AsyncSession]`. No FastAPI dependency lives here — P0US6 builds its `get_db`
  dependency directly on top of `get_sessionmaker()`, so this module is the single reusable
  entrypoint for both Alembic and the application.
- `seed.py` — `run_seed(session: AsyncSession) -> None`, used by `make seed`. Uses Postgres
  `INSERT ... ON CONFLICT DO NOTHING` keyed on each table's natural unique column (`sources.name`,
  `offers.dedup_hash`, `profiles.name`) so it is safe to re-run. `_seed_offers` (P1US1) builds a
  canonical `app.schemas.offer.Offer` per seed entry and calls `app.ingestion.persist.persist_offer`
  rather than hand-rolling its own dedup/insert statement — the seed path exercises the same
  ingestion code every connector will use, instead of a second, divergence-prone implementation.

## Database schema (P0US5)

Alembic (async template) is wired to `app/db/base.py`'s `Base.metadata` via `alembic/env.py`,
which reads `DATABASE_URL` from the environment at runtime rather than from `alembic.ini` (kept
blank) — matching `.env.example`, one source of truth for the connection string. The v1 migration
creates all six tables spanning every phase's domain nouns up front, so no later phase needs a
repeated foundational migration:

| Table | Purpose | Key columns / constraints |
| --- | --- | --- |
| `sources` | A job board connector (SOLID.Jobs, JustJoin.it, NoFluffJobs) | `name` unique; `config_json` (JSONB) per-source config; `connector` nullable `String(50)` (P1US6, see below) |
| `offers` | A normalised job posting with exactly one Source | `dedup_hash` unique + indexed (dedup on canonical URL, P1US1 fallback to title+company+location); `canonical_url` nullable (P1US1 — not every source guarantees a stable URL); `description` nullable `Text` (P1US1); `raw_payload` (JSONB, ELT raw payload always populated at ingest) |
| `profiles` | Candidate's structured facts: skills, experience, preferences | `name` unique; `is_active` (only one row active at a time, enforced by application logic, not a DB constraint); `data` (JSONB) |
| `cv_versions` | Tailored CV + cover letter drafted for one Offer/Profile pair | FKs to `offers`/`profiles`; `status` string (no DB enum, so later statuses need no migration) |
| `match_scores` | Structured evaluation of one Offer against a Profile (`score_percent` 0-100 + dimensions, P3US29) | FKs to `offers`/`profiles`; `engine` distinguishes LangChain vs. `sjctl` scoring; `score_percent` `Integer` not null (replaced `grade` `String(1)`, P3US29) |
| `applications` | Record of intent/action to apply | FKs to `offers`/`profiles`/`cv_versions`; `status` one of `drafted`/`reviewed`/`sent`/`failed`/`interview`/`offer`/`rejected` (unconstrained string, not a DB enum) |
| `scheduler_runs` (P1US6) | One row per ingestion run, automatic or manual — the scheduler's audit trail | FK to `sources`; index on `(source_id, started_at)` for cheap "latest row per source" lookups; `status` one of `running`/`ok`/`error` (unconstrained string, same no-DB-enum convention as `applications.status`); `fetched_count`/`created_count` nullable `Integer` (null only while `status="running"`); `warning` `Boolean` (zero-result flag, see below); see "Scheduler" below |

`make migrate` runs `docker compose exec api alembic upgrade head` (mirrors the pattern used by
other `docker compose exec api ...` Make targets — `DATABASE_URL`'s `db` hostname only resolves
inside the Compose network, not from the host). `make seed` runs
`docker compose exec api python -m app.db.seed`, loading three sample
offers; both targets are idempotent. (P2US1 removed this seed's previous stub-profile row — see
"Profile data model (P2US1)" below.)

A second migration (`aa3fa339111b`, chained after `df5297add8cb`) makes `offers.canonical_url`
nullable and adds `offers.description` (nullable `Text`). Both changes were deferred from the
P0US5 migration deliberately — P0US5 only had to create "all v1 tables", not pin the exact
`offers` shape — and are resolved by P1US1 (see below) once the canonical `Offer` schema and dedup
strategy needed to know the real constraints existed.

A third migration (`12bc4e296410`, chained after `aa3fa339111b`, P1US6) adds `sources.connector`
and creates `scheduler_runs` plus its `(source_id, started_at)` index — see "Scheduler" below.

### Offer schema and dedup strategy (P1US1)

- **`app/schemas/offer.py`** — `Offer(BaseModel)`, the canonical, source-agnostic shape every
  connector (P1US2–US4: SOLID.Jobs, JustJoin.it, NoFluffJobs) maps its source-specific payload
  into before persistence. Fields mirror every `offers` column except `id`, `dedup_hash`,
  `raw_payload`, `created_at`, `updated_at` — those are ingestion-pipeline concerns, not
  connector-mapping concerns: the persistence layer computes `dedup_hash`, attaches
  `raw_payload` (the source's original response) separately from the normalised fields, and lets
  the database assign `id`/timestamps. `model_config` sets `str_strip_whitespace=True` (so a
  blank required field can't hide behind leading/trailing whitespace) and `from_attributes=True`
  (a harmless default enabling future construction from an ORM row — it does not by itself make
  `Offer` a usable API response model, since it lacks `id`/timestamps; a later story's read
  schema would still need to add those). A `field_validator` normalises an empty/whitespace
  `canonical_url` to `None` (so "available" genuinely means non-empty); a `model_validator`
  rejects `salary_min > salary_max`.
- **ELT pattern, as implemented**: the raw payload a connector fetched from its source is passed
  into `persist_offer`/`ingest_offer` as a separate argument alongside the already-validated
  `Offer`, and both are written to the same `offers` row in the same `INSERT` — there is no
  separate raw-payload table. The raw payload is captured before normalisation; normalisation
  (mapping to `Offer`, computing `dedup_hash`) happens as a distinct step afterwards, but both
  forms persist together.
- **`app/ingestion/dedup.py`** — the two-tier dedup strategy. `normalize_canonical_url` lowercases
  scheme and host, strips the query string and fragment (tracking parameters must never affect
  dedup identity), and strips a trailing slash from the path — path *case* is preserved, since job
  slugs can be case-sensitive. A normalized URL is "comparable" when it has a non-empty path
  (`_is_comparable`): a bare domain like `https://example.com` doesn't identify a specific
  posting, so it can't anchor dedup. `compute_dedup_hash(offer: Offer) -> str` hashes the
  normalized canonical URL (SHA-256, hex) when one is present and comparable; otherwise it falls
  back to a hash of `title|company|location` (lowercased, whitespace-stripped) — this fallback is
  a known, accepted tradeoff: two genuinely distinct postings sharing all three fields will
  collide, but no source guarantees a stable per-posting URL.
- **`app/ingestion/persist.py`** — the entrypoints every future connector story calls:
  - `normalize_and_validate(raw: dict[str, Any]) -> Offer | None` — the validation boundary. A
    dict a connector already mapped from its source-specific format either becomes a valid
    `Offer`, or fails `pydantic.ValidationError` and is logged at `WARNING` (an anticipated,
    handled condition) and rejected via a `None` return — never raised — so a batch ingestion run
    can keep processing the rest of a page after one bad record.
  - `persist_offer(session, offer, raw_payload) -> tuple[OfferModel, bool]` — computes
    `dedup_hash`, then `INSERT ... ON CONFLICT (dedup_hash) DO NOTHING ... RETURNING id`
    (the same idempotent-upsert idiom `seed.py` already used pre-P1US1), followed by a re-`SELECT`
    by `dedup_hash` since `RETURNING` doesn't surface the pre-existing row's `id` on conflict. The
    returned `bool` is `True` only when a row was actually inserted, so a caller batching many
    offers (P1US5's scheduler) can report new-vs-seen counts. Deliberately out of scope: a
    re-ingested offer's fields are never refreshed (`DO NOTHING`, not `DO UPDATE`) — the first
    snapshot ingested is kept forever until a later story adds field-refresh-on-reingest; this
    matches the acceptance criteria's literal "does not create a duplicate row" and avoids the
    extra insert/update-detection complexity (`RETURNING (xmax = 0)`) `DO UPDATE` would need.
    Does not commit — the caller controls the transaction boundary, since a scheduled run may
    need to batch many offers in one transaction.
  - `ingest_offer(session, mapped_fields, raw_payload) -> tuple[OfferModel, bool] | None` — the
    single public per-offer entrypoint combining the two: `None` if validation rejected the
    record (already logged inside `normalize_and_validate` — never logged twice), otherwise
    `persist_offer`'s `(row, created)` tuple.

### SOLID.Jobs connector (P1US2, direct API since BUG10)

- **`app/connectors/solid_jobs.py`** — the first of three sibling connectors
  (P1US2–US4: SOLID.Jobs, JustJoin.it, NoFluffJobs). Originally a subprocess wrapper around the
  `sjctl` CLI; rewritten (BUG10, see
  `docs/adr/0012-solid-jobs-direct-api-replaces-sjctl-subprocess.md`) to call SOLID.Jobs' own
  public HTTP endpoint directly, once the vendor confirmed `sjctl` itself was just a thin wrapper
  over that same endpoint. Exposes
  `run_solid_jobs_ingestion(session, source, *, campaign, force_refresh=False) -> IngestionResult`
  as the single public entrypoint (unchanged signature) — it does not commit the session (same
  convention as `persist_offer`) and does not create or seed a `Source` row itself.
- **Endpoint**: `GET https://solid.jobs/public-api/offers/{division}` — `division` is a URL path
  segment (`build_offer_url`, defaulting to `"IT"`), not a query param. No auth; `campaign` is a
  required query param. `_fetch_solid_jobs_json` pins `X-Api-Version: 1.0` on every request (the
  only one of the three connectors that pins an API version — the other two have no such header
  to pin).
- **`config_json` schema for a SOLID.Jobs Source row** (mirrors JustJoin.it's own config surface):
  `division` (str, defaults to `"IT"`) → URL path segment; `cities` (list[str]) →
  `search.cities` (comma-joined); `min_salary` (int) → `search.minimumSalary`; `experience_levels`
  (list[str]) → `search.experiences` (comma-joined); `terms` (list[str]) → `search.searchTerm`
  (comma-joined), the technology/free-text filter (e.g. `["python"]`); plus `page_size`,
  `max_pages`, `already_seen_stop_threshold` (pagination config, same defaults and meaning as
  JustJoin.it's). `build_offer_params` does no validation of these — a malformed config value
  fails loudly via `str()` coercion rather than being silently dropped, since `config_json` is
  already-validated-at-write-time internal configuration, not user input. **Known live-API
  limitation** (see ADR 0012): `search.experiences` only accepts a single value in practice —
  multi-value input (comma-joined or repeated) returns `400` from the live API — even though
  `build_offer_params` will still comma-join more than one configured `experience_levels` entry;
  fixing this is an open follow-up, not part of this story.
- **Response envelope, confirmed live 2026-07-05** (see ADR 0012, resolving what was an open
  question before this ticket had live access): `{"jobs": [...], "pageIndex", "pageSize",
  "totalCount", "totalPages"}` — the same `"jobs"` key sjctl's own `search --json` used. `salary:
  {from, to, currency, employmentType}`, `locations: string[]`, `isRemote`/`isHybrid`,
  `experienceLevel`, `validFrom`, `description` all match the pre-BUG10 field shape almost
  field-for-field.
  - `_extract_offers(payload)` — single-arg now (no `list_key`/`item_key`; that was purely an
    artifact of the old sync-vs-search envelope split, which no longer exists). Reads a bare list
    directly, or the `"jobs"` key from a dict payload; anything else returns `None` so the caller
    can distinguish "zero offers" from "the response shape changed".
  - `map_solid_jobs_offer` (renamed from `map_sjctl_offer`, no field changes): `locations` (list) →
    `Offer.location` (single string) joined with `", "`. `isHybrid` is dropped from the normalised
    field — `Offer.remote` is `isRemote` only, not `isRemote OR isHybrid`, since folding hybrid
    into "remote" would misrepresent hybrid roles (raw `isHybrid` is still preserved in
    `raw_payload`). `contract_type` maps from `salary.employmentType` (`"UoP"`/`"B2B"`) rather than
    the top-level `contractTime` (`"full_time"`/`"part_time"`), since "contract type" in this
    domain means employment form, not work-time schedule (see the `Remote` and `Contract Type`
    glossary entries in `CLAUDE.md`). `description` is stored as the raw HTML the API returns,
    unstripped — HTML-to-text is deferred to whichever later phase actually needs plain text (CV
    tailoring).
- **Pagination and `force_refresh`, JustJoin.it's model, not NoFluffJobs' no-op** (BUG10): every
  request sets `sortActive=validFrom&sortDirection=desc`, giving the same newest-first
  precondition JustJoin.it's endpoint relies on (ADR 0009). `run_solid_jobs_ingestion` interleaves
  fetch-then-persist per page (`pageIndex`/`pageSize`, no cursor field — "fewer offers returned
  than `pageSize`" is the end-of-results signal) and stops early once
  `already_seen_stop_threshold` consecutive already-seen offers accumulate, exactly mirroring
  `run_justjoinit_ingestion`'s `_persist_offers` shape. `force_refresh=True` bypasses that
  checkpoint (ADR 0010's model) instead of switching sjctl subcommands — the old sjctl
  watch-scoped "sync" concept (ADR 0001) no longer exists in the direct API and has no
  replacement, since a "watch" was never a resource the direct API exposed.
- **`_fetch_solid_jobs_json`** is the sole HTTP boundary, structured identically to
  `_fetch_justjoinit_json`/`_fetch_nofluffjobs_json`: delegates to the shared
  `app.connectors.http.fetch_json`, which catches `httpx.HTTPError` (connection/timeout/non-2xx via
  `raise_for_status()`) and `json.JSONDecodeError` on `response.json()`, logging at `ERROR` and
  returning `None` in both cases — never raises. `run_solid_jobs_ingestion` turns a `None` from
  either `_fetch_solid_jobs_json` or `_extract_offers` into
  `IngestionResult(ok=False, fetched=0, created=0, error_message=...)` only when it happens on the
  first page; a later-page failure logs a warning and returns whatever was already fetched, same
  as JustJoin.it.

### JustJoin.it connector (P1US3)

- **Investigation finding (resolves OD-4 for JustJoin.it — NoFluffJobs's half of OD-4 is
  separately resolved by US13)**: JustJoin.it exposes a real, unauthenticated JSON endpoint, so
  Path A (thin HTTP client) was implemented — no Playwright scraper. The endpoint was found by
  downloading justjoin.it's own served Next.js JS bundles and grepping them for the API client
  code, since a local headless-Chromium network capture (the more direct "devtools Network tab"
  approach) never completed in this sandboxed environment. The obvious guesses were wrong: the
  page's own runtime config names `https://api.justjoin.it` as `baseApiUrl`, but
  `GET https://api.justjoin.it/offers` returns `404 Invalid endpoint`; `baseCpUrl`
  (`https://profile.justjoin.it`) redirects to a login page. The bundle code backing the public
  `/job-offers` listing page actually calls a gateway whose `baseURL` resolves to the *relative*
  path `/api/candidate-api` (proxied through justjoin.it's own server), giving the real endpoint:
  `GET https://justjoin.it/api/candidate-api/offers?from=<cursor>&itemsCount=<page size>` — see
  `docs/adr/0003-justjoinit-json-endpoint-investigation.md` for the full trail (mirrors ADR 0002's
  "verify against the live system" discipline).
- **`app/connectors/justjoinit.py`** — the second of three sibling connectors (P1US2–US4). Exposes
  `run_justjoinit_ingestion(session, source) -> IngestionResult` as the single public entrypoint;
  no `campaign` parameter (that's a SOLID.Jobs-specific concept, not applicable here). Does
  not commit the session and does not create or seed a `Source` row, matching `solid_jobs.py`'s
  conventions.
- **Response shape, confirmed live**: `{"data": [...offer objects...], "meta": {"from",
  "totalItems", "prev": {"cursor", "itemsCount"}, "next": {"cursor", "itemsCount"}}}`, cursor
  pagination — `meta.next.cursor` is `null` at the end of a page window.
  `_fetch_justjoinit_json` is the sole HTTP boundary: catches `httpx.HTTPError` (covers both
  connection/timeout failures and non-2xx status via `raise_for_status()`) and
  `json.JSONDecodeError` on `response.json()`, logging at `ERROR` and returning `None` in both
  cases — never raises. `_extract_offer_list` mirrors `_extract_offers`'s defensive shape
  handling (bare list, or dict wrapping the list under `"data"`; anything else returns `None` so
  the caller can tell "zero offers" from "the response shape changed").
- **Pagination early-stops on already-seen offers, with a hard ceiling as backstop (BUG02)**:
  `meta.totalItems` was observed as a flat `10000` regardless of actual result count — not an
  estimate, but a real enforced cap: probing live confirmed `from + itemsCount > 10000` always
  returns a bare `500` (checked at multiple `itemsCount` values), and `meta.next.cursor` does
  **not** reliably go `null` before that boundary (at `from=9900` it reports `next.cursor: 10000`,
  which itself 500s). Live sampling also confirmed the feed is newest-first (`publishedAt` strictly
  non-increasing across 30 consecutive items), which is what makes an early-stop strategy sound
  rather than a coincidence — see `docs/adr/0009-justjoinit-incremental-pagination-strategy.md` for
  the full trail. `run_justjoinit_ingestion` now interleaves fetch and persist per page (rather
  than accumulating all pages then persisting once at the end) and stops requesting further pages
  once `already_seen_stop_threshold` (default `20`) consecutive offers come back as `created=False`
  from `persist_offer`'s own `ON CONFLICT DO NOTHING` result — no separate pre-check query, since
  the insert's return value already carries that signal. `max_pages` remains a hard safety ceiling
  (raised from `5` to `100`, i.e. `100 × page_size 100 = 10,000`, matching the confirmed real limit
  exactly) for a cold/empty `Source` where nothing is ever already-seen. Pagination still stops
  gracefully — keeping whatever was already fetched — if a page fetch fails after the first page
  succeeded (this is what actually absorbs the `meta.next.cursor` lie at the 10,000 boundary); only
  a first-page failure marks the whole result `ok=False`.
- **`force_refresh=True` bypasses the early-stop checkpoint (BUG06)**:
  `run_justjoinit_ingestion(..., force_refresh=True)` skips the consecutive-already-seen check
  entirely, so pagination only stops on `cursor is None` or the `max_pages` ceiling — a genuine
  "re-walk the full catalog" behavior, not a no-op. See
  `docs/adr/0010-force-refresh-threaded-through-all-connectors.md`.
- **Field mapping** (`map_justjoinit_offer`), from the confirmed list-item shape:

  | `Offer` field | Source field(s) | Notes |
  |---|---|---|
  | `external_id` | `guid` | |
  | `canonical_url` | `slug` | Built as `https://justjoin.it/job-offer/{slug}` (singular `job-offer`; confirmed by following the `/offers/{slug}` → `/job-offer/{slug}` redirect live) — the list endpoint has no direct URL field |
  | `title` | `title` | |
  | `company` | `companyName` | |
  | `location` | `locations[].city` | Joined with `", "` (mirrors `map_solid_jobs_offer`'s location join); falls back to top-level `city` if `locations` is empty |
  | `remote` | `workplaceType` | JustJoin.it's own 3-value enum is `{"remote", "hybrid", "office"}` — mapped to a canonical `bool` via `app.ingestion.normalize.normalize_remote` (P1US5); this happens to already satisfy the `Remote` glossary rule that hybrid is not remote |
  | `seniority` | `experienceLevel` | Mapped to the shared canonical vocabulary via `app.ingestion.normalize.normalize_seniority` (P1US5) — see "Cross-connector schema consistency" below |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `employmentTypes[0].{from,to,currency,type,gross}` | **Known limitation**: a JustJoin.it offer can list several employment-type entries (e.g. both `b2b` and `permanent`, each further repeated per display currency); only the first/primary entry is mapped, matching the same simplification `map_solid_jobs_offer` was allowed for SOLID.Jobs's own multi-field shape. Salary values arrive as floats and are coerced to `int` for the `Integer` DB column; currency and the `gross` flag are passed through `normalize_salary` (P1US5), which logs (but does not fabricate a conversion for) non-`PLN` currencies and `gross: false` figures. `contract_type` remains a raw pass-through of `type` — permanently, not deferred — per the `Contract Type` glossary entry being explicitly out of scope for vocabulary unification |
  | `posted_at` | `publishedAt` | ISO datetime string, parsed by `Offer`'s pydantic validation |
  | `description` | *(not mapped — always `None`)* | **Known limitation**: the list endpoint's offer objects do not include the job description body; only the per-offer detail endpoint (`GET /api/candidate-api/offers/{slug}`) has it, and fetching that per offer would multiply request volume for every ingestion run. `description` is nullable on `Offer`, so this is schema-compliant; a later story could add a bounded per-offer detail fetch if the description text becomes necessary (e.g. for CV tailoring) |

### NoFluffJobs connector (P1US4)

- **Investigation finding (resolves the NoFluffJobs half of OD-4 — JustJoin.it's half was
  resolved by US12)**: NoFluffJobs exposes a real, unauthenticated JSON endpoint, so Path A (thin
  HTTP client) was implemented — no Playwright scraper. The endpoint was found by downloading
  `nofluffjobs.com`'s own served Angular bundle (`main.<hash>.js`) and grepping it for the
  `HttpClient` gateway code, then confirming every candidate against the live site with `curl` —
  see `docs/adr/0004-nofluffjobs-json-endpoint-investigation.md` for the full trail. Two candidates
  were wrong in different ways before the real one was found: `POST /api/search/posting` (the real
  search-results endpoint) requires `salaryCurrency`/`salaryPeriod` query params but then returns a
  bare `500` for every request body shape tried; `GET /api/posting` returns `200` but dumps the
  *entire* current listing inventory unpaginated (~89 MB). The endpoint actually used is:
  `GET https://nofluffjobs.com/api/joboffers/main?pageSize=<N>&salaryCurrency=PLN&salaryPeriod=month`
  — the site's own homepage "recommended offers" feed.
- **`app/connectors/nofluffjobs.py`** — the third of three sibling connectors (P1US2–US4). Exposes
  `run_nofluffjobs_ingestion(session, source) -> IngestionResult` as the single public entrypoint.
  Does not commit the session and does not create or seed a `Source` row, matching
  `solid_jobs.py`/`justjoinit.py`'s conventions.
- **No pagination loop, by design — not a simplification, a fact about the endpoint**: unlike
  JustJoin.it's cursor pagination, `page` was verified live to *not* behave as an offset — requests
  for `page` values `1` through `300` (fixed `pageSize`) returned effectively identical result sets.
  `pageSize` does scale the number of postings returned, but non-linearly and by more than the
  requested count (`pageSize=20` → 140 postings, `pageSize=100` → 327, `pageSize=500` → 2043),
  consistent with the endpoint aggregating multiple categories server-side rather than slicing one
  ordered, resumable list. `run_nofluffjobs_ingestion` therefore issues exactly one `GET` per call,
  sized by `page_size` from `config_json`. This is a documented known limitation: the connector
  surfaces a bounded, recommendation-ranked slice of NoFluffJobs's current listings (observed up to
  ~2000 postings at `page_size=500`), not the full ~12,000-offer catalog — a full backfill would
  need the still-broken `search/posting` endpoint (or a different strategy entirely) if a later
  story needs it. Because ingestion is a single HTTP request per run, no `rate_limit_delay_seconds`
  config key exists for this connector — there is nothing to delay between.
- **`Source.last_fetched_at` is deliberately *not* used to filter or skip offers here (BUG02)**: a
  tempting fix would be to skip persisting offers whose `posted_at` predates the last successful
  run, but because this endpoint is a re-ranked recommendation feed rather than a stable
  chronological list, an offer could re-enter the feed's ranking later without ever having been
  ingested before — filtering it out by an old `posted_at` would silently and permanently lose it,
  since nothing would ever retry it. `Source.last_fetched_at` is populated for this connector the
  same as any other (see "Scheduler" below), but is used purely as a staleness signal surfaced to
  the user, not as a fetch-side filter. See
  `docs/adr/0009-justjoinit-incremental-pagination-strategy.md` for the full reasoning.
- **`_fetch_nofluffjobs_json`** is the sole HTTP boundary, structured identically to
  `_fetch_justjoinit_json`: catches `httpx.HTTPError` (connection/timeout/non-2xx via
  `raise_for_status()`) and `json.JSONDecodeError` on `response.json()`, logging at `ERROR` and
  returning `None` in both cases — never raises. `_extract_offer_list` requires the response to be
  a dict with a `"postings"` key (a bare list, which JustJoin.it's endpoint can return, is not a
  shape NoFluffJobs's endpoint ever produces, and is treated as unexpected here); `None` postings is
  treated as zero offers, the same "explicit null means empty, not malformed" convention `_extract_offers` applies for SOLID.Jobs.
- **Field mapping** (`map_nofluffjobs_offer`), from the confirmed `postings[]` item shape:

  | `Offer` field | Source field(s) | Notes |
  |---|---|---|
  | `external_id` | `id` | The mixed-case, location-suffixed slug. **Not** `reference` — NoFluffJobs emits one posting entry per office location for the same underlying ad, and all of those duplicates share one `reference` code, which would collide as an `external_id`; `id`/`url` are unique per listing |
  | `canonical_url` | `url` | Built as `https://nofluffjobs.com/job/{url}` — confirmed live |
  | `title` | `title` | |
  | `company` | `name` | Not `company` — NoFluffJobs's own field name for the employer is `name` |
  | `location` | `location.places[].city` | Joined with `", "` (mirrors `map_justjoinit_offer`'s location join) |
  | `remote` | `location.fullyRemote` | Already a literal boolean matching the `Remote` glossary definition exactly (zero on-site presence) — routed through `app.ingestion.normalize.normalize_remote` (P1US5) unchanged, since a `bool` input is passed straight through. The top-level `fullyRemote` field on the posting itself was observed to always be `False` across a ~2000-record sample and is not used |
  | `seniority` | `seniority[]` | A list on the wire, observed always length 1 in live sampling; each item mapped to the shared canonical vocabulary via `app.ingestion.normalize.normalize_seniority` (P1US5), then joined with `", "` if ever multi-valued — see "Cross-connector schema consistency" below |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `salary.{from,to,currency,type}` | `salary.type` takes values `permanent`/`b2b`/`zlecenie` in the wild — passed through verbatim as `contract_type`, permanently no vocabulary translation (out of scope per the `Contract Type` glossary entry, not deferred). Salary values arrive as floats and are coerced to `int`; currency passed through `normalize_salary` (P1US5) |
  | `posted_at` | `posted` | A Unix **milliseconds** epoch integer (not an ISO string, unlike JustJoin.it's `publishedAt`) — divided by 1000 and converted with `datetime.fromtimestamp(..., tz=UTC)` |
  | `description` | *(not mapped — always `None`)* | **Known limitation**, same as JustJoin.it's: the listing payload has no full job-description field |

### Cross-connector schema consistency (P1US5)

- **Purpose**: P1US2–US4 built each connector in isolation; each one's own test file said so
  explicitly ("no cross-source vocabulary unification happens here — that is US14's job"). This
  story is the integration checkpoint — all three connectors were run and their output compared
  field by field before the scheduler (P1US6) and ingestion API (P1US7) start depending on them
  producing genuinely comparable `Offer` rows.
- **`app/ingestion/normalize.py`** — new shared module, mirroring `app/ingestion/dedup.py`'s style
  (small pure functions, a module logger, no I/O). Owns: seniority-vocabulary mapping,
  remote-flag/string-vocabulary mapping, salary currency/gross-flag normalisation, and null-safe
  numeric coercion (`to_int`, moved verbatim from the duplicated private `_to_int` previously in
  both `justjoinit.py` and `nofluffjobs.py`). Connector-specific concerns — `canonical_url`
  construction, location-string joining, `contract_type` passthrough, description handling, and
  HTTP/subprocess transport — remain in each connector, unchanged.
- **Source identity constants** (`SOLID_JOBS`, `JUSTJOINIT`, `NOFLUFFJOBS`) are separate from the
  free-text `Source.name` DB column, which is arbitrary per deployment — the vocabulary tables key
  off connector identity, passed explicitly by each connector's own module-level import, not off
  DB content.
- **Canonical seniority vocabulary**: `CANONICAL_SENIORITY_LEVELS = ("junior", "mid", "senior",
  "lead", "expert")`. `junior`/`mid`/`senior` match the lowercase convention already used by
  `tests/integration/conftest.py`'s seed data; `lead` and `expert` extend the set to cover
  JustJoin.it's `c_level`/`manager`-style values without collapsing them into `senior`.
  `normalize_seniority(source_name, raw_value)` accepts a bare string or a list (defensively, since
  NoFluffJobs's wire field is a list), maps each item case-insensitively through the per-source
  table below, de-duplicates, and joins the result with `", "` (mirroring the existing
  multi-value location join convention). An unrecognised label is logged at `WARNING` and dropped
  — never fabricated as a new placeholder value — and a fully-unmapped or missing input returns
  `None`.

  | Source | Raw label (as observed) | Canonical |
  |---|---|---|
  | SOLID.Jobs | `junior` | `junior` |
  | SOLID.Jobs | `regular` | `mid` |
  | SOLID.Jobs | `mid` | `mid` |
  | SOLID.Jobs | `senior` | `senior` |
  | SOLID.Jobs | `expert` | `expert` |
  | JustJoin.it | `junior` | `junior` |
  | JustJoin.it | `mid` | `mid` |
  | JustJoin.it | `senior` | `senior` |
  | JustJoin.it | `c_level` | `lead` |
  | JustJoin.it | `manager` | `lead` |
  | NoFluffJobs | `trainee` | `junior` |
  | NoFluffJobs | `junior` | `junior` |
  | NoFluffJobs | `mid` | `mid` |
  | NoFluffJobs | `senior` | `senior` |
  | NoFluffJobs | `expert` | `expert` |
  | NoFluffJobs | `c-level` | `lead` |

  **Concrete discrepancies fixed by this table**: SOLID.Jobs' own request-filter vocabulary uses
  `"Regular"` (confirmed live), previously passed straight into `Offer.seniority`
  unchanged — now mapped to canonical `"mid"`. JustJoin.it's `"manager"`/`"c_level"` (confirmed live
  and via fixture), previously passed straight through, are now mapped to canonical `"lead"`.
- **Remote-flag handling**: SOLID.Jobs' `isRemote` and NoFluffJobs' `location.fullyRemote` are
  already literal booleans matching the `Remote` glossary definition exactly (zero on-site
  presence) — `normalize_remote(source_name, raw_value)` passes a `bool` input straight through
  with no lookup, so both connectors now call the shared function per the "one abstraction, not
  three copies" requirement even though they need no translation. JustJoin.it's `workplaceType` is
  a 3-value string enum (`{"remote", "hybrid", "office"}`) — mapped via a per-source
  `_REMOTE_STRING_VOCAB` table (`remote → True`, `hybrid → False`, `office → False`). An
  unrecognised string label is logged at `WARNING` and defaults to `False` (never fabricated as
  `True`); a missing/non-string/non-bool value (the ordinary "field absent" case) returns `False`
  without logging.
- **Salary normalisation — PLN, monthly, gross is an investigation finding, not an assumption**:
  none of the three sources was observed emitting an explicit salary period field, so "monthly" was
  never a distinct value to normalise across — SOLID.Jobs' and NoFluffJobs' salary figures are
  monthly by convention of the Polish job market, and NoFluffJobs' own listing endpoint is queried
  with `salaryPeriod=month` explicitly (see the NoFluffJobs connector section above).
  `normalize_salary(source_name, salary_min, salary_max, raw_currency, *, raw_gross=None)`
  centralises the `currency = raw_currency or "PLN"` defaulting previously duplicated three times,
  and never mutates or converts the salary figures themselves — converting currency or a net figure
  without a real exchange-rate/tax source would fabricate a number, which the acceptance criteria
  for this story explicitly forbids.
  - **Known limitation — no FX conversion**: if `raw_currency` resolves to anything other than
    `"PLN"`, a `WARNING` is logged naming the source, the observed currency, and the salary figures;
    the figures are stored as-is in whatever currency the source reported. **Confirmed live, not
    just theoretical**: a manual verification run against the real JustJoin.it endpoint (see
    "Manual testing" below) observed a real, non-trivial number of live offers reporting `EUR` and
    `CHF` as `employmentTypes[0].currency` (JustJoin.it's own `currencySource: "conversion"` field
    on those entries confirms they are display conversions of an original non-PLN figure, not data
    errors) — these are stored with their observed currency code and a logged warning, not silently
    coerced to `"PLN"`.
  - **Known limitation — no net-to-gross conversion**: JustJoin.it's `employmentTypes[].gross`
    boolean was observed `False` on essentially every live entry sampled (see the manual
    verification run) — the `gross` field name is confusingly not a reliable "is this gross"
    signal in the live data, but its presence and `False` value are real. When `raw_gross is False`
    (checked with `is`, not truthiness, so a source that doesn't report this flag at all —
    SOLID.Jobs, NoFluffJobs — is never penalized for a field it doesn't have and `raw_gross=None`
    stays silent), a `WARNING` is logged naming the source and figures; recruFlow performs no
    net-to-gross conversion and stores the figures unchanged.

### Scheduler (P1US6)

- **Purpose**: all three connectors (P1US2–US4) exist and produce comparable `Offer` rows
  (P1US5), but nothing yet calls them automatically or on a schedule, and nothing reports on what
  happened when they ran. This story wires `APScheduler` into the FastAPI lifespan, gives each
  source its own configurable schedule, and adds a manual trigger endpoint plus a status endpoint.
  P1US7 (ingestion API endpoints, not part of this story) will add its own `POST /ingest/{source}`
  reusing this story's dispatch seam (see "Registry/dispatch design" below) — do not confuse this
  story's per-source ingestion scheduler with the later, separate P6US2 Digest job, and do not
  confuse this story's single-run zero-result warning with P6US1's later two-consecutive-run
  escalation and dedicated `/health/sources` endpoint — both are explicitly out of scope here.

- **Lifecycle within the FastAPI lifespan** (`app/main.py`): `app/main.py` gained a `lifespan`
  context manager — the first time this file has had one. On startup it builds its own long-lived
  `AsyncEngine`/sessionmaker (via `app.db.session.get_engine`/`get_sessionmaker`, *not* the
  request-scoped `SessionDep`), calls `ensure_sources_exist` once and commits, constructs an
  `AsyncIOScheduler(timezone="UTC")`, calls `register_jobs` to add one job per connector-tagged
  `Source`, then `scheduler.start()`. The scheduler instance is stashed on `app.state.scheduler` so
  tests and future endpoints can introspect `get_jobs()`/`running`. On shutdown, `scheduler.shutdown
  (wait=True)` runs before `engine.dispose()` — `wait=True` is APScheduler's default but is passed
  explicitly to document intent; it does not risk hanging indefinitely because every connector
  already enforces its own request timeout (all three connectors' `httpx.get` calls pass an
  explicit `timeout`), so an in-flight job always finishes or times out within a bounded window.
- **Real behavioral change, documented deliberately**: before this story, FastAPI could start even
  with the DB down (only `/health/db` would fail per request). After this story, startup itself
  calls `ensure_sources_exist`/`register_jobs`, so the app now fails to start if the DB is
  unreachable or unmigrated. `docker-compose.yml`'s `api` service `depends_on: db: condition:
  service_healthy` only guarantees Postgres itself is up, not that `alembic upgrade head` has
  already run — `make up` alone does not run migrations; `make migrate` must be run once against a
  fresh database before the `api` container will start cleanly. This is a real, new coupling
  introduced by this story, not a defect to silently work around.

- **`sources.connector` vs. `sources.name`**: a new nullable `String(50)` column,
  `sources.connector`, holds one of the three connector identity constants
  (`app.ingestion.normalize.SOLID_JOBS`/`JUSTJOINIT`/`NOFLUFFJOBS`) and is used purely as the
  scheduler's dispatch key. `sources.name` was deliberately **not** reused for dispatch — it is
  documented (see "Database schema" above) as an arbitrary, display-only, per-deployment label, and
  repurposing it for dispatch would silently break that invariant for any deployment that renamed a
  Source row. `connector` is nullable specifically so pre-existing/arbitrary `Source` rows (e.g.
  `seed.py`'s `"seed"` fixture row) remain valid with `connector=NULL` and are simply invisible to
  the scheduler — both `register_jobs` and `GET /scheduler/status` filter on `connector IS NOT
  NULL`.

- **Schedule config schema**: schedule configuration lives under a new reserved `"schedule"` key
  inside the existing `sources.config_json` JSONB blob, coexisting with each connector's own keys
  (`division`/`cities`/... for SOLID.Jobs, `page_size`/... for the other two) rather than adding new
  columns. `app/scheduler/triggers.py`'s `parse_schedule(config_json) -> BaseTrigger` supports a
  tagged union on `"type"`:
  - interval: `{"schedule": {"type": "interval", "seconds": 3600}}` → `IntervalTrigger(seconds=...)`
  - cron: `{"schedule": {"type": "cron", "expression": "0 */2 * * *"}}` →
    `CronTrigger.from_crontab(expression)`

  Any missing or malformed schedule value (missing `"schedule"` key, non-dict value, unknown
  `"type"`, missing/non-positive/non-numeric `"seconds"` for `interval`, missing/empty/unparseable
  `"expression"` for `cron`) **never raises** — it logs a `WARNING` via the module logger
  `app.scheduler.triggers` and falls back to `DEFAULT_INTERVAL_SECONDS = 3600`. This matches the
  connectors' established fail-soft philosophy: bad per-source config must never crash startup or
  block other sources' jobs from registering. The three built-in sources' shipped defaults
  (`app.scheduler.service.DEFAULT_SOURCE_CONFIGS`): `solid_jobs` — interval, 3600s (1h); `justjoinit`
  — interval, 1800s (30m); `nofluffjobs` — cron, `"0 */2 * * *"` (every 2 hours on the hour).
  **Superseded by P3US28**: all three built-in connectors now default to a uniform interval
  schedule of 300s (5 minutes) instead of the mixed values above, and every source's interval is
  user-editable at runtime via `PUT /scheduler/sources/{source}/interval` — see the P3US28 notes
  below.

- **`scheduler_runs` table, not `sources.last_run_*` columns**: a new table rather than columns on
  `sources`, matching the project's existing ELT/audit-trail instinct (raw payloads are always kept,
  not overwritten) — this keeps `GET /scheduler/status` queryable by "latest row per source" cheaply
  via the `(source_id, started_at)` index, and leaves headroom for P6US1's later two-consecutive-run
  escalation without a further migration. Columns: `id`, `source_id` (FK), `trigger_type`
  (`"automatic"`/`"manual"`), `status` (`"running"`/`"ok"`/`"error"`, unconstrained string, no DB
  enum — same convention as `applications.status`), `fetched_count`/`created_count` (nullable
  `Integer`, populated only once a run finishes), `warning` (`Boolean`), `error_message` (nullable
  `Text`), `started_at`/`finished_at` (`DateTime(timezone=True)`, `finished_at` nullable while
  `status="running"`). `app/scheduler/runs.py` is the sole read/write surface:
  `start_run`/`finish_run_ok`/`finish_run_error` set explicit Python-side `datetime.now(UTC)`
  values (rather than relying on the column's `server_default=now()`/an eager-refresh round-trip) so
  the caller has a real, immediately-usable timestamp on the in-memory row without an extra
  `SELECT`. None of `runs.py`'s functions commit — same transaction-boundary convention as
  `app.ingestion.persist`.

- **`Source.last_fetched_at` (BUG02) is not a violation of the "no `sources.last_run_*` columns"
  choice above** — it serves a different consumer. `scheduler_runs` remains the full, append-only
  audit trail (every run, including errors, warnings, and per-run counts) queried by `GET
  /scheduler/status`. `Source.last_fetched_at` is a single narrow checkpoint a connector reads back
  *for itself*, synchronously, before/while fetching — a concern the audit table was never designed
  to serve cheaply (it would mean a `SELECT ... ORDER BY started_at DESC LIMIT 1` per connector run
  just to answer "when did I last succeed"). It is set in `app/scheduler/service.py`'s
  `_run_source_async`, in the same success branch as `finish_run_ok`, to `datetime.now(UTC)`
  whenever a run completes with `ok=True` — regardless of `fetched`/`created` counts, mirroring
  `SchedulerRun.finished_at`'s own semantics rather than gating on "found something new." See
  `docs/adr/0009-justjoinit-incremental-pagination-strategy.md`.

- **Registry/dispatch design** (`app/ingestion/registry.py`, moved from `app/scheduler/registry.py`
  by BUG04 — the ingestion package now owns the dispatch seam its name always promised, and
  `app/scheduler` is left with only APScheduler job registration and run-tracking, per ADR 0006) —
  the seam every "run a connector" flow reuses, not reimplements: `CONNECTOR_REGISTRY: dict[str,
  Connector]` maps each connector constant to a private adapter (`_dispatch_solid_jobs`/
  `_dispatch_justjoinit`/`_dispatch_nofluffjobs`) satisfying the `Connector` protocol
  (`async def(session, source, force_refresh) -> IngestionResult`) that calls the matching
  `run_*_ingestion` through a qualified module reference (e.g. `solid_jobs.run_solid_jobs_ingestion`,
  not a name imported into `registry`'s own namespace) — a declared interface rather than an
  accident of import binding, and the reason tests now patch `app.connectors.<name>.run_*_ingestion`
  directly instead of `registry`'s copy of the name. `_dispatch_solid_jobs` is the odd one out — it
  reads `campaign=get_settings().solid_jobs_campaign` internally so all three adapters present the same
  `(session, source, force_refresh) -> IngestionResult` signature despite `solid_jobs` needing an
  extra keyword argument underneath. `resolve_source_by_connector(session, connector) -> Source`
  raises `UnknownConnectorError` if `connector` isn't a `CONNECTOR_REGISTRY` key at all,
  `SourceNotConfiguredError` if it's a known connector with no matching `Source` row yet, and
  otherwise returns the row; `dispatch_ingestion(session, source)` assumes the caller already
  resolved/validated `source.connector` (asserts non-`None`) and calls straight through the
  registry. Both `app.scheduler.service` and `app/api/routes/ingestion.py` call
  `resolve_source_by_connector` + `dispatch_ingestion` directly rather than duplicating
  connector-selection logic.

- **`force_refresh` is now genuinely threaded through every connector, not just `solid_jobs`
  (BUG06)** — `_dispatch_justjoinit`/`_dispatch_nofluffjobs` used to accept `force_refresh` (to
  satisfy the shared `Connector` protocol) and then silently drop it, so the interface promised
  uniform behavior none of the connectors but `solid_jobs` actually had. Fixed per-connector, not
  by dropping the parameter, since JustJoin.it turned out to have real meaning to give it:
  `run_justjoinit_ingestion(..., force_refresh=True)` now bypasses the BUG02/ADR0009 early-stop
  checkpoint, walking pagination all the way to `max_pages` regardless of the
  consecutive-already-seen streak — see `docs/adr/0010-force-refresh-threaded-through-all-connectors.md`.
  NoFluffJobs has no equivalent checkpoint to bypass (no pagination loop at all, per BUG02/ADR0009
  above), so `run_nofluffjobs_ingestion` accepts `force_refresh` for interface parity and documents
  in-line why it's a deliberate no-op rather than continuing to swallow it silently one layer down.

- **Non-blocking execution model — why job callables are plain `def`, not `async def`**: see
  `docs/adr/0005-scheduler-jobs-must-be-plain-sync-callables.md` for the full reasoning; summary
  here. `AsyncIOScheduler` shares uvicorn's single event loop and only offloads a job to its thread
  pool when the registered callable is a plain function — an `async def` job runs directly on the
  main loop instead. None of the three connectors are actually non-blocking on their own (all
  three call synchronous `httpx.get`, since BUG10 removed SOLID.Jobs' subprocess call), so an
  `async def` scheduler job would block the *entire* API for the duration of every run.
  `app.scheduler.service.run_source_sync` is therefore a plain `def`: it builds its own throwaway
  `AsyncEngine`/sessionmaker (via `get_engine()`/`get_sessionmaker()` — never the request-scoped,
  main-loop-pinned `SessionDep`) and drives the async work through a fresh `asyncio.run(...)`, since
  it executes inside a worker thread with no event loop of its own. `register_jobs`
  (`app/scheduler/lifecycle.py`) passes `run_source_sync` itself (not a coroutine function) to
  `scheduler.add_job(..., max_instances=1, coalesce=True)` — both non-optional: without them, a
  source whose run takes longer than its own interval would stack overlapping concurrent runs
  against the same source. The manual-trigger endpoint's async wrapper,
  `app.scheduler.service.run_source`, calls `run_source_sync` via `asyncio.to_thread(...)` for the
  identical reason, so automatic and manual runs share one code path and one `SchedulerRun`
  bookkeeping implementation, and neither blocks the main loop. Verified mechanically (not just by
  code inspection) by
  `tests/integration/test_scheduler_routes.py::test_health_endpoint_responds_during_scheduler_run`,
  which kicks off a deliberately slow mocked run and asserts `/health` still responds in well under
  the run's duration.

- **Zero-result warning semantics**: `run_source_sync` sets `warning=True` on `finish_run_ok`
  precisely when `result.fetched == 0` — **not** `result.created == 0`. Zero *created* offers after
  dedup is a normal, expected steady state once a source's inventory has already been ingested;
  zero *fetched* offers means the connector's own request round-trip returned nothing at all, which
  is the actual source-breakage signal the acceptance criteria describes. When the warning
  condition is hit, a `WARNING` is logged via the module logger `app.scheduler.service` naming the
  connector, and `GET /scheduler/status`'s `last_run_warning` reflects it. Note that a connector's
  own internally-handled failure (e.g. an HTTP transport error, malformed JSON) already
  returns `IngestionResult(ok=False, fetched=0, ...)` rather than raising (established connector
  convention from P1US2–US4) — from the scheduler's perspective this is indistinguishable from a
  "genuinely zero offers available" run: both surface as `status="ok"`, `warning=True`.
  `SchedulerRun.status="error"` is reserved for an actual Python exception escaping
  `dispatch_ingestion` (verified via a mocked `RuntimeError` in
  `test_run_source_now_connector_exception_records_error_status_not_stuck_running`) — the
  `try`/`except Exception` around the `dispatch_ingestion` call in `_run_source_async` guarantees a
  run is never left stuck at `status="running"` if a connector bug throws.

- **`POST /scheduler/run/{source}` and `GET /scheduler/status`** (`app/api/routes/scheduler.py`,
  bare `APIRouter()`, no prefix, full literal paths — mirrors `health.py`'s convention exactly).
  `trigger_run` deliberately does **not** take `SessionDep` — it calls the shared `run_source` async
  wrapper, which manages its own engine/session on a worker thread exactly like automatic runs; this
  is what makes manual and automatic runs one shared code path and what makes "the API stays
  responsive during a manual run" mechanically true, not just true for automatic runs. Status code
  convention: the endpoint returns **200 even when the resulting run's own `status` is `"error"`**
  (a connector failure or exception) — the HTTP request itself succeeded in the sense that a run was
  triggered and its outcome reported, mirroring the connectors' own "return `ok=False`, don't raise"
  philosophy. Only a `SchedulerLookupError` (unknown connector, or a known connector with no
  provisioned `Source` row) maps to `HTTPException(404, ...)`, with the detail message
  distinguishing "unknown connector" from "no configured source" so a caller (or test) can tell the
  two failure modes apart. `scheduler_status` selects every `Source` row with `connector IS NOT
  NULL`, calls `get_latest_run_by_source` once per source (an intentional N+1-per-source query
  pattern — acceptable given only three sources exist; not worth a window-function query), and
  defaults every `last_run_*` field to `None`/`False` when a source has never run.
  `SourceStatus.last_fetched_at` (BUG02) is read straight off `Source.last_fetched_at` (see above)
  rather than derived from the joined `SchedulerRun` — it is `None` for a source that has never
  completed a run.

### Ingestion API endpoints (P1US7)

- **Purpose**: all three connectors now run automatically on a schedule (P1US6) and produce
  comparable, deduplicated, persisted `Offer` rows, but nothing yet lets a job seeker force an
  out-of-band fetch through a dedicated ingestion-facing endpoint, or browse/inspect what has
  actually been stored. This story adds `POST /ingest/{source}`, `GET /offers`, and
  `GET /offers/{offer_id}` to close that gap. It is the direct dependency for P1US8 (offer list
  page, frontend), which builds a table against `GET /offers` and wires a "Fetch now" button per
  source to `POST /ingest/{source}`.

- **`POST /ingest/{source}`** (`app/api/routes/ingestion.py` + `app/ingestion/service.py`) reuses
  P1US6's dispatch seam directly — `resolve_source_by_connector` + `dispatch_ingestion`
  (`app/ingestion/registry.py`) — rather than `app.scheduler.service.run_source`, and deliberately
  does **not** write to `scheduler_runs`. This is a separate, lighter-weight, job-seeker-facing
  trigger, distinct from the scheduler subsystem's own audited manual trigger at
  `POST /scheduler/run/{source}`; see
  `docs/adr/0006-manual-ingest-trigger-is-not-scheduler-audited.md` for the full rationale and its
  consequence (`GET /scheduler/status` does not reflect `/ingest/{source}` runs, only automatic and
  `/scheduler/run/{source}` ones). `app.ingestion.service.trigger_ingest` structurally mirrors
  `run_source`/`run_source_sync`/`_run_source_async`: a throwaway `AsyncEngine`/sessionmaker via
  `get_engine()`/`get_sessionmaker()` (never the request-scoped `SessionDep`), `asyncio.run(...)`
  inside a plain (non-`async`) function, invoked via `asyncio.to_thread(...)` — the same
  non-blocking execution model P1US6/ADR 0005 established, and for the identical reason: none of
  the three connectors are internally non-blocking, so calling `dispatch_ingestion` directly from a
  `SessionDep`-based route handler would block `/health` and every other route for the run's
  duration. Verified mechanically by
  `tests/integration/test_ingestion_routes.py::test_health_endpoint_responds_during_ingest_run`.
  **`_trigger_ingest_async` also sets `source.last_fetched_at` on `result.ok` (BUG02)** — this is
  not a `scheduler_runs` write (ADR 0006's "not scheduler-audited" stance is unchanged and still
  applies to the run-history table) but a checkpoint on `Source` itself, and a job-seeker's
  on-demand "Fetch now" click is exactly the kind of successful fetch that checkpoint needs to
  reflect; leaving it scheduler-runs-only would make the Offers page's own source-status display
  go stale immediately after the button it sits next to was clicked.

- **Shared engine/session/dispatch lifecycle (BUG05)**: `_trigger_ingest_async` and
  `_run_source_async` both need the throwaway-engine/sessionmaker/`resolve_source_by_connector`/
  `dispatch_ingestion`/commit/`engine.dispose()` scaffolding described above; that plumbing now
  lives in one place, `app.ingestion.lifecycle.run_with_lifecycle(connector, force_refresh=...,
  before_dispatch=..., on_success=..., on_error=...)`, so the two flows differ only in the
  run-tracking hooks they pass — not in ~30 lines of copy-pasted lifecycle code. This does **not**
  change the ADR 0006 boundary: `_trigger_ingest_async` still passes no `before_dispatch` and an
  `on_success` that conditionally sets `last_fetched_at` (only if `result.ok`); `_run_source_async`
  still plugs `start_run` into `before_dispatch` and `finish_run_ok`/`finish_run_error` into
  `on_success`/`on_error`, unconditionally setting `last_fetched_at` in the success branch
  regardless of `result.ok` (see the zero-result-warning note above — this asymmetry between the
  two flows predates and is preserved by this refactor, not introduced by it). `on_error` owns its
  own commit/rollback rather than the helper doing it uniformly, because the two callers disagree:
  `_trigger_ingest_async`'s hook rolls back and logs without committing (matching its early-return
  shape), `_run_source_async`'s hook calls `finish_run_error` and commits — the one lifecycle stage
  that is not actually identical between the two flows.
  Response shape:

  ```bash
  curl -X POST http://localhost:8000/ingest/justjoinit
  ```

  ```json
  {"source": "justjoinit", "ok": true, "fetched": 5, "created": 3, "error_message": null}
  ```

  Status codes mirror `/scheduler/run/{source}`'s convention: `200` even when `"ok": false` (an
  unexpected exception escaped the connector — the request itself still succeeded in the sense that
  a run was triggered and its outcome reported, matching the connectors' own "return `ok=False`,
  don't raise" philosophy); `404` only when `{source}` isn't a recognised connector at all, or is a
  recognised connector with no provisioned `Source` row — same `SchedulerLookupError` hierarchy,
  same distinguishing detail messages, as `/scheduler/run/{source}`. There is no lock against two
  concurrent triggers for the same source (identical to `/scheduler/run/{source}`'s existing
  behaviour) — a double-tap of a future "Fetch now" button can start two overlapping runs; dedup
  still prevents duplicate rows, so the cost is wasted work, not data corruption. Debouncing that is
  a frontend concern for P1US8, not this endpoint's.

- **`force_refresh` defaults to `False` on `POST /ingest/{source}` (BUG18, reverses ADR 0008)**:
  `_trigger_ingest_async` used to hardcode `force_refresh=True` unconditionally — a decision ADR
  0008 made to work around SOLID.Jobs' old `sjctl sync`/`search` mode switch (fixed for BUG01).
  Once ADR 0012 replaced `sjctl` with a direct-HTTP connector, `force_refresh`'s only remaining
  effect for every connector (SOLID.Jobs, JustJoin.it) is bypassing the BUG02/ADR0009
  `consecutive_already_seen` early-stop, so the hardcoded `True` silently defeated that
  incremental checkpoint on every single "Fetch now" click — the only fetch action reachable from
  the UI, since `FetchNowButton.tsx` has no way to pass a flag through `triggerIngest`/
  `POST /ingest/{source}` (`frontend/src/api/offers.ts`). `POST /ingest/{source}` now accepts an
  optional `force_refresh` query param (`app/api/routes/ingestion.py`, default `False`), threaded
  through `trigger_ingest`/`_trigger_ingest_sync`/`_trigger_ingest_async`
  (`app/ingestion/service.py`) to `run_with_lifecycle`, so a normal button click now gets the same
  early-stop behaviour as `POST /scheduler/run/{source}` already had. A genuine full re-sync
  (recovering from a bad `dedup_hash` change, backfilling) is still reachable via
  `POST /ingest/{source}?force_refresh=true`, but is no longer the button's default — no UI control
  wires it up yet, so today it is curl/ops-only.

- **`GET /offers`** and **`GET /offers/{offer_id}`** (`app/api/routes/offers.py`) use `SessionDep`
  (plain read-only `SELECT`s, no blocking I/O underneath, unlike the ingest trigger) and join
  `Offer` to `Source` explicitly via `select(...).join(...)` — no ORM `relationship()` is defined
  anywhere in `app/db/models.py`, matching the codebase-wide convention. Two private, pure mapping
  helpers, `_offer_summary`/`_offer_detail`, are unit-tested without a database
  (`tests/test_offers_mapping.py`) since `OfferModel` instances can be constructed in memory.
  **Paginated, ordered, and scored inline (BUG26)**: `GET /offers` originally had no pagination
  ("acceptable at current single-machine data volumes") and no `ORDER BY` at all — fine until the
  backlog crossed ~18k rows, at which point an unfiltered request returned every row in one
  response and Postgres's scan order had no relationship to recency or scoring progress. It now
  takes `limit` (default 50, max 200) and `offset` (default 0) and always applies
  `ORDER BY posted_at DESC NULLS LAST, created_at DESC, id DESC` — the same ordering BUG24 already
  applied to `_fetch_unscored_offers` (`app/scoring/batch.py`), so "top of the table" and "scored
  first" are finally the same offers. The response is now an envelope,
  `{"items": [...], "total": <count ignoring limit/offset>}`, so a client can page without a
  second request. Each item also now carries `score_percent: int | null` (renamed/retyped from
  `grade: str | null` by P3US29, see that section below) — the active profile's most
  recent `MatchScore.score_percent` for that offer, joined in via a `ROW_NUMBER() OVER (PARTITION
  BY offer_id ORDER BY created_at DESC)` subquery scoped to the active profile (or to a sentinel
  `-1` profile id when there's no active profile, so the query shape never branches) — eliminating
  the one-`GET /offers/{id}/score`-request-per-offer fan-out the frontend previously did to render
  score badges for a loaded page.

  **`source`**: the response's `source` field is the connector identity string
  (`Source.connector`), falling back to `Source.name` when `connector` is `NULL` (covers
  non-scheduler-managed `Source` rows, e.g. `app/db/seed.py`'s `"seed"` fixture row) — a `source`
  field is never null in a response. The `?source=` query filter, however, matches **only**
  `Source.connector`, not `Source.name` — a deliberate asymmetry: a non-scheduler-managed source's
  offers are visible in an unfiltered `GET /offers` (displaying its `name` as `source`) but cannot
  be selected via `?source=`. This is accepted for v1 since only the three real connectors are ever
  filtered on in practice.

  **`seniority`**: substring match (`ILIKE '%value%'`) against the possibly comma-joined
  `Offer.seniority` column (see `normalize_seniority`, P1US5) — `?seniority=senior` matches an offer
  stored as `"senior, lead"`. Safe against false positives because none of the five canonical
  levels (`junior`/`mid`/`senior`/`lead`/`expert`) is a substring of another.

  **`min_salary`**: "meets or exceeds" semantics — matches when `salary_max >= min_salary`, or,
  when `salary_max` is unknown, falls back to `salary_min >= min_salary`.

  **`grade`** (deleted by P3US29): originally an `EXISTS`-style subquery — `Offer.id IN (SELECT
  offer_id FROM match_scores WHERE grade = :grade)` — against `match_scores`. Deliberately **not**
  scoped to the active `Profile` (`Profile.is_active`) or to a specific `engine`, and never
  consumed by the frontend; P3US29 removed the param outright rather than inventing a
  percentage-equivalent "exact match" concept nobody had asked for.

  **`min_score`** (renamed from `min_grade` by P3US29, int 0–100): a "minimum acceptable score"
  filter — `min_score=50` keeps offers scored 50 or higher, dropping lower and not-yet-scored
  offers. Scoped to the active profile only (it reuses the same inline-score join described
  above), matching what the frontend's "Minimum score %" input conceptually means: the active
  profile's own bar, not any profile's. Before P3US29 this was `min_grade` (BUG26), a five-value
  `GRADE_ORDER` slice; the underlying comparison is now a plain `score_percent >= min_score`.

  ```bash
  curl "http://localhost:8000/offers?source=justjoinit&remote=true&seniority=senior&min_salary=15000&min_score=50&limit=50&offset=0"
  ```

  ```json
  {
    "items": [
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
        "created_at": "2026-06-21T08:00:00Z",
        "score_percent": 92
      }
    ],
    "total": 1
  }
  ```

  `GET /offers/{offer_id}` returns the same fields plus `description`, `raw_payload` (the ELT raw
  payload stored at ingest time, returned byte-for-byte), and `updated_at`; `404` with
  `{"detail": "offer {offer_id} not found"}` for an unknown id. The path parameter is named
  `offer_id`, not `id`, to avoid shadowing the `id` builtin — this does not change the route's
  external shape.

### CORS (P1US8)

`app/main.py` gained `CORSMiddleware` (`fastapi.middleware.cors`), added immediately after
`app.state.settings = settings`. `Settings.cors_allow_origin` (`CORS_ALLOW_ORIGIN`, default
`http://localhost:5173`) is the single allowed origin — no wildcard, no list-parsing. Without
this, `frontend`'s Vite dev server (`http://localhost:5173`) cannot call the API
(`http://localhost:8000`) from a real browser; `curl`/content-only checks never surface this,
since CORS is enforced by the browser, not the server's business logic. `allow_credentials=False`
(no cookies/auth exist yet) and `allow_methods`/`allow_headers` are both wildcarded — only the
origin is restricted. Developers must browse the frontend via `http://localhost:5173`, not
`http://127.0.0.1:5173` — the two are different origins from a CORS perspective even though
`docker-compose.yml`'s own healthcheck targets `127.0.0.1` internally; this is a deliberate
simplicity tradeoff (single exact-match origin) rather than an allow-list.

### Offer list page (P1US8)

- **Purpose**: closes Phase 1 end-to-end — ingest -> normalise -> store -> browse -> manually
  refresh, all reachable from a browser. Consumes `GET /offers` and `POST /ingest/{source}`
  (P1US7) with no backend changes to either route.
- **`frontend/src/api/offers.ts`**: the sole module calling `/offers`/`/ingest/{source}` through
  the shared `apiClient` (`client.ts`, P0US7). Re-exports `OfferSummary`/`IngestResponse` as type
  aliases off `components['schemas']` rather than redeclaring shapes by hand, so a schema
  regeneration (`make generate-types`) surfaces any drift as a TypeScript error here first.
  `fetchOffers`/`triggerIngest` both collapse `openapi-fetch`'s `{data, error}` result into a
  throw-on-error `Promise<T>`, so every caller uses one `try`/`catch` rather than checking `error`
  at each call site.
- **`frontend/src/hooks/useOffers.ts`**: owns `offers`/`total`/`loading`/`error` state and
  re-fetches when `source`/`remote`/`seniority`/`minSalary`/`minGrade` **or** the page
  (`{limit, offset}`, BUG26) change. Structured around `react-hooks/set-state-in-effect` (part of
  `eslint-plugin-react-hooks`'s `recommended` config, already wired up since P0US7) — this rule
  statically rejects an effect calling any hoisted (e.g. `useCallback`) function that eventually
  calls a state setter, even past an `await`, so the automatic fetch-on-filter-change effect
  defines and invokes its own async function *inline*, duplicating (rather than delegating to)
  `refetch`'s fetch-and-setState logic. `refetch` itself is safe as a `useCallback` because it's
  only ever invoked from an event handler (`FetchNowButton`'s click) or `OfferListPage`'s
  scoring-finished effect, never from within an effect. **BUG26**: page changes share the same
  300ms debounce as filter changes (`OfferListPage` owns `page` state, resets it to `0` on any
  filter/minGrade change, and passes `{limit: PAGE_SIZE, offset: page * PAGE_SIZE}` down) —
  deliberately not special-cased to skip the debounce, since a Prev/Next click is a single
  low-frequency event where a 300ms delay is imperceptible, and one code path is simpler than two.
- **`frontend/src/hooks/useOfferScoreDetail.ts`** (BUG26, replaces `useOfferScores.ts`): fetches
  one offer's full score breakdown (rationale, dimensions) on demand — only when the score drawer
  opens for that specific offer id — rather than the old `useOfferScores`, which fired
  `GET /offers/{id}/score` once per *currently loaded* offer via `Promise.allSettled`. At the
  reported backlog size (18k+ offers, unpaginated) that fan-out became ~18,000 concurrent requests
  on a single page load; browsers cap concurrent connections per origin (~6), so only an arbitrary
  handful of scores ever resolved before the user gave up looking, and the visible "scored" count
  bore no relationship to real scoring progress. `GET /offers` now returns each offer's `grade`
  inline (see the backend section above), so the list/table render entirely off data from one
  request; this hook exists solely to fetch the *rest* of a score (rationale, per-dimension
  breakdown) for `ScoreDrawer`, which only ever needs one offer's detail at a time.
- **`frontend/src/components/OfferFilters.tsx`**: controlled filter bar
  (source/remote/seniority/min-salary), no local state duplication — every control's `onChange`
  produces a new `OfferListFilters` object from the parent-owned value. `remote` is modelled as a
  three-value `'' | 'true' | 'false'` DOM select, translated to `boolean | undefined`. Min-salary
  is clamped to `>= 0` client-side (`Math.max(0, Number(raw))`).
- **`frontend/src/components/FetchNowButton.tsx`**: one independent instance per known connector
  identity (`solid_jobs`/`justjoinit`/`nofluffjobs`, `frontend/src/constants.ts`). Owns its own
  loading/error/summary state so three buttons never block each other; guards against a
  double-click by returning early while already loading. On success, shows the `IngestResponse`
  counts inline (`"Fetched 12, 4 new"`) rather than silently refreshing the table — `fetched`/
  `created` were already computed by the API and otherwise discarded, and a `0`-new-offers outcome
  is otherwise invisible in the table.
- **`frontend/src/components/OfferTable.tsx`**: originally sorted client-side by `posted_at`
  descending (nulls last) because `GET /offers` (P1US7) had no `ORDER BY` at all; the backend now
  always applies that exact ordering server-side (BUG26), but the client-side
  `sortByPostedDateDesc` default stayed — it's now a no-op re-sort of an already-ordered page
  rather than the sole source of order, kept because the "click Grade header to sort" behavior
  (`sortByGrade`) already needed client-side re-sorting infrastructure regardless. Both sort
  helpers now read `offer.grade` directly (inline field, BUG26) instead of a separate `scores`
  lookup map. Salary formatting distinguishes a floor from a ceiling rather than collapsing both
  to the same string: `"20,000+ PLN"` (min only), `"up to 25,000 PLN"` (max only),
  `"15,000-25,000 PLN"` (both), `"-"` (neither); a `null` `salary_currency` on an offer with a
  known salary defaults to display `"PLN"` (matching the DB column's own `server_default`, see
  "Database schema" above), never left blank. Empty state (`offers.length === 0 && !loading`)
  renders a message instead of an empty `<table>` — a minimum-grade-filtered empty result gets its
  own message (`FilteredEmptyState`) naming the active `minGrade`, simplified by BUG26 to drop the
  old "N of M loaded offers haven't been scored yet" wording: that messaging existed only because
  minGrade filtering used to run against a partially-loaded, in-flight `scores` map client-side, an
  incompleteness that can't happen anymore now that `min_grade` filters server-side against a
  complete page. A bounded-height (`max-h-[70vh]`), `overflow-y-auto` wrapper keeps a rendered page
  scrollable; the table itself no longer needs to scroll through the *entire* backlog because
  `OfferListPage` now pages through it (BUG26) rather than loading everything at once.
- **`frontend/src/pages/OfferListPage.tsx`**: the page shell — holds `filters`, `minGrade`, and
  `page` state, renders the three `FetchNowButton`s, `OfferFilters`, `GradeFilter`, an inline error
  banner when `useOffers().error` is set, `OfferTable`, and (BUG26) a Prev/Next pagination footer
  driven by `useOffers().total`. Changing any filter or `minGrade` resets `page` to `0` (an
  in-range page for the old filters can be out of range for new ones); paging itself does not
  reset filters. The scoring-finished-triggers-a-refetch effect (BUG16) now calls `useOffers()`'s
  own `refetch` directly instead of a separate scores hook, since grades arrive inline with the
  page (BUG26) — there is no longer a second, scores-only fetch to re-trigger.
- **Routing**: `react-router-dom` was added even though this story ships only one route
  (`App.tsx`'s `<BrowserRouter><Routes><Route path="/" element={<OfferListPage />} /></Routes></BrowserRouter>`)
  — CLAUDE.md's own phase roadmap already documents further pages landing in Phase 2+ (profile,
  matching, etc.), so this is not speculative infrastructure for a hypothetical need; it avoids a
  routing-migration story later for near-zero cost today.
- **Theme (`frontend/src/index.css`)**: `:root` custom properties (`--color-bg`,
  `--color-surface`, `--color-text`, `--color-accent`, `--color-border`, ...) plus three
  `@layer components` classes (`.card`, `.btn`/`.btn-primary`, `.input`) that every new component
  composes instead of one-off Tailwind color utilities — the "single consistent color scheme, no
  page-local styles" acceptance criterion. `App.tsx`'s outer wrapper now reads
  `bg-[var(--color-bg)] text-[var(--color-text)]` instead of the previous hardcoded
  `bg-slate-900 text-white`.
- **Frontend testing (vitest, new in this story)** — see
  `docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md`: this is the first frontend
  story with real interactive behaviour (filters, async fetch, loading states) rather than static
  content, so `vitest` + `@testing-library/react` + `@testing-library/user-event` + `jsdom` were
  added, superseding the `tests/test_frontend_api_client.py`-style Python content-assertion
  approach for this story's components. `frontend/src/test/setup.ts` explicitly wires
  `@testing-library/jest-dom/vitest` matchers and an `afterEach(cleanup)` — required because
  `globals: true` is deliberately **not** set in `vite.config.ts`'s `test` block (tests import
  `describe`/`it`/`expect` explicitly from `vitest` rather than relying on ambient globals), and
  `@testing-library/react`'s automatic cleanup detection depends on a global `afterEach` existing.
  `pnpm test` (`vitest run`) and `make test-frontend` exist but are **not** wired into
  `make test`/`make ci`/the GitHub Actions workflow — a deliberate, temporary gap recorded in ADR
  0007, not an oversight.

### Profile data model (P2US1)

- **Purpose**: the first Phase 2 story. Defines `app/schemas/profile.py`'s `Profile`, the
  canonical, source-agnostic candidate-facts document that US19's LLM extraction, US20's frontend
  editor, and this story's own `PUT /profile` all validate against. No new migration is needed —
  the `profiles` table's existing `data` JSONB column (P0US5) already satisfies "profiles DB table
  stores these fields plus an `is_active` boolean flag"; the structured fields live inside `data`,
  validated at the application layer, the same ELT-adjacent split `offers.raw_payload` already
  uses.
- **Field list**: `skills` (`Skill`: `name`, `proficiency`, `years`, `category`), `past_roles`
  (`PastRole`: `title`, `company`, `start_date`, `end_date`, `description`), `education`
  (`Education`: `institution`, `degree`, `field_of_study`, `start_date`, `end_date`),
  `certifications` (`Certification`: `name`, `issuer`, `year`), `languages` (`Language`: `name`,
  `proficiency`), `projects` (`Project`: `name`, `description`, `tech_stack`, `client`,
  `team_size` — distinct from `past_roles`, for a CV's own "Selected Projects"-style section),
  `industry_tags` (`list[str]`), `headline`, `summary`, `email`, `phone`, `location`, `links`
  (`list[str]`), `contract_type_preference`, `salary_min`, `salary_target`,
  `location_preference`, `remote_preference`, `deal_breakers` (`list[str]`). `industry_tags` also
  exists on `Offer`/`OfferSummary` (`app/schemas/offer.py`, `offers.industry_tags` JSONB column)
  so postings can carry the same domain tags for future matching (BUG09).
- **Three deliberate looseness decisions**, required by the acceptance criteria's "no fixed/
  hardcoded values ... every list-type field accepts an arbitrary number of arbitrary entries":
  - `PastRole`/`Education` dates (`start_date`/`end_date`) are free-form strings (e.g. `"2019"`,
    `"Jan 2021"`, `"present"`), not a strict date type — CVs report dates in inconsistent, often
    partial formats, and a strict date type would make US19's LLM extraction fail on any CV using
    a non-ISO date phrase.
  - `Skill`/`Language` `proficiency` is a free string, not a `Literal`/enum — same reasoning, no
    fixed vocabulary is allowed for list-type field content.
  - Salary preference is modelled as `salary_min`/`salary_target` (not `salary_min`/`salary_max`
    as `Offer` uses) — "target" is the candidate's aspirational figure, not necessarily an upper
    bound, so `salary_max` would be the wrong name. A `model_validator` still checks
    `salary_target >= salary_min` when both are present, mirroring `Offer`'s own
    `_check_salary_range` pattern, because a target below the floor is a real, catchable input
    error, not a legitimate edge case.
- **Single-active-profile invariant**: exactly one `profiles` row may have `is_active=true` at a
  time — this is **Open Decision OD-3** from `user stories/000 high level guide.md` ("Profile:
  single active vs named profiles"), resolved as "one active Profile at a time, matching sjctl's
  own default behaviour". Enforced by `app/db/profile_repo.py`'s `activate_profile(session,
  profile_id)`: two `UPDATE` statements in the caller's existing transaction — clear every other
  row's flag first, then set the target row's flag — ordered this way so a crash between the two
  statements never leaves two rows simultaneously active, only ever zero or one. This is a
  reusable primitive, not `PUT /profile`-specific: it's the same function US19's CV-upload
  activation flow and US20's "Set as active" button will call later.
- **`GET /profile`** returns HTTP 200 with a JSON `null` body (`ProfileResponse | None`) when no
  profile is active, not a 404 — a 404 means "you asked for something identifiable that isn't
  there", but "no active profile yet" is an expected, normal steady state for a fresh install,
  mirroring `GET /offers`'s empty-list convention rather than an error.
- **`PUT /profile`** is an upsert: if no profile is currently active, it creates the first one
  (`name` defaults to `DEFAULT_PROFILE_NAME = "active-profile"`, an internal bookkeeping key, not
  "profile data" in the sense the no-seed acceptance criterion forbids) and activates it; if one
  is already active, it updates that row's `data` in place. This is necessary because this story
  ships no seed profile data, so a fresh database has zero profile rows, and `PUT /profile` must
  still work with no prior setup.
- **`profile_id`/`activate` query parameters (added in P2US3)**: `PUT /profile` gained two
  optional query parameters, `profile_id: int | None = None` and `activate: bool = True` — both
  default to the exact values that reproduce this story's original always-edit-and-activate-the-
  active-profile behavior, so every pre-existing caller and test is unaffected. They exist because
  P2US3 (the profile editor page) needs to edit a freshly-uploaded, not-yet-active draft (a
  separate row from whatever is currently active) without either force-activating it or clobbering
  the real active profile — a case the original single-active-row-only upsert had no way to
  express. `app/db/profile_repo.py`'s `upsert_profile(session, profile, *, profile_id, activate)`
  is the underlying primitive: when `profile_id` is given, it loads that exact row (raising
  `ProfileNotFoundError` — mapped to `404` in the route — if it doesn't exist) instead of looking
  up "the" active profile; `activate` gates whether `row.status`/`is_active` are touched at all.
  `activate=False` leaves every row's `is_active` flag completely untouched, which is what makes
  "Save" a true no-side-effect-on-activation operation. `upsert_active_profile` (US18's original
  entrypoint) is now a one-line wrapper — `upsert_profile(session, profile, profile_id=None,
  activate=True)` — so its signature and behavior are unchanged for existing callers.
- **Idempotent default-row lookup**: when `profile_id` is `None` and no profile is currently
  active, `upsert_profile` now checks for an existing row named `DEFAULT_PROFILE_NAME` (not just
  "is any row active") before creating a new one. Without this, two consecutive `activate=False`
  saves with nothing yet active (e.g. a user clicking "Save" twice before ever clicking "Set as
  active") would each try to `INSERT` a row named `"active-profile"` and the second would fail
  `profiles.name`'s unique constraint — caught via manual browser testing of this story, not by
  the initial test suite, since the repo/route tests each start from an explicitly seeded fixture
  row rather than the "truly zero profile rows" state a fresh install and repeated unactivated
  saves reach.
- **No seed/default profile data**: this story removed `app/db/seed.py`'s previous stub-profile
  seeding (`SEED_PROFILE_NAME`, `_seed_profile`) — the acceptance criteria explicitly forbid
  shipping any seed/default profile content; a profile's content must always originate from a CV
  upload (US19) or manual entry.

### CV upload + LLM extraction (P2US2)

- **Purpose**: `POST /profile/upload` turns an uploaded CV file (PDF or DOCX) directly into a
  draft `Profile`, via a local LLM, so a candidate doesn't have to hand-retype their whole work
  history. Request: multipart form upload, one `file` field. Response: `ProfileResponse` (the
  same shape `GET`/`PUT /profile` return — `id`, `name`, `status`, `is_active`, `profile`,
  `created_at`, `updated_at`), with `status: "draft"` and `is_active: false`.
- **Two new packages, split by failure domain**: `app/cv/text_extraction.py` owns file-format
  parsing (`extract_cv_text(filename, content) -> str`, dispatching on file extension to a
  private `_extract_pdf_text`/`_extract_docx_text`); `app/llm/cv_extraction.py` owns LLM
  invocation (`extract_profile_from_cv_text(cv_text) -> Profile`). These are separate failure
  domains — a corrupt/unsupported file and an unreachable/misbehaving LLM are unrelated error
  conditions with different causes, different remediations, and (per below) different HTTP status
  codes, so keeping them in different modules keeps each one's error handling legible on its own.
- **`CVExtraction` vs. `Profile`**: the LLM's structured-output target is `CVExtraction`
  (`app/schemas/profile.py`), a schema containing only the CV-derived fields (`skills`,
  `past_roles`, `education`, `certifications`, `languages`, `projects`, `industry_tags`,
  `headline`, `summary`, `email`, `phone`, `location`, `links`) — it deliberately omits `Profile`'s
  preference fields (`contract_type_preference`, `salary_min`, `salary_target`,
  `location_preference`, `remote_preference`, `deal_breakers`), because a CV's text has no basis
  for those and the LLM must never be given a schema slot it could be tempted to fill with an
  inference. `extract_profile_from_cv_text` maps `CVExtraction` into a full `Profile` via
  `Profile(**extraction.model_dump())`, leaving every preference field at its own default (`None`
  or `[]`).
- **Three-way split LLM call (BUG09)**: `_call_llm` no longer asks the model to fill all of
  `CVExtraction` in a single structured-output call. Manual testing against a real two-page CV
  (`user stories/CV.pdf`) showed that once the schema grew to cover projects/industry
  tags/contact/headline on top of the original five list fields, the local 8B model
  (`llama3.1:8b`) silently returned empty lists for whatever didn't fit in its context budget,
  rather than erroring — first dropping everything but the header fields, then (after trimming
  to a two-way split) still dropping `projects`/`industry_tags` specifically. Raising Ollama's
  `num_ctx` to compensate was tried and rejected: it triggered a hard `CUDA error: unspecified
  launch failure` that crashed the model server mid-request. The fix instead runs three small,
  focused calls sequentially against the *same* CV text — `_build_core_chain`
  (skills/past_roles/education/certifications/languages, the original proven schema),
  `_build_contact_chain` (headline/summary/email/phone/location/links), and
  `_build_projects_chain` (projects/industry_tags) — then merges the three results into one
  `CVExtraction`. Each call's schema and expected output stay small enough for the model to fill
  reliably at the default context window, at the cost of three sequential LLM round-trips instead
  of one.
- **Facts-only enforcement**: there is no code-level guardrail beyond each call's system prompt
  and `temperature=0` — `app/llm/cv_extraction.py`'s `_CORE_SYSTEM_PROMPT` /
  `_CONTACT_SYSTEM_PROMPT` / `_PROJECTS_SYSTEM_PROMPT` each instruct the model to extract only
  what is explicitly present, never infer/embellish/guess, and leave absent sections as empty
  lists; `ChatOllama(..., temperature=0)` removes sampling randomness for this facts-extraction
  task. No automated test targets extraction *quality* (i.e. whether the model actually stays
  facts-only on a real CV) — that is verified manually against the real Ollama
  container, not asserted in CI, matching this story's own acceptance-criteria scope.
- **The LLM-call boundary diverges from the connectors' pattern deliberately**: background
  ingestion connectors (e.g. `app/connectors/solid_jobs.py`'s `_fetch_solid_jobs_json`) catch expected
  failures and return `None`/`ok=False`, because nothing is waiting synchronously on them.
  `POST /profile/upload` is a synchronous, user-waited request (why ADR 0011 picked an 8B model
  over a 70B one), so its boundary function, `_call_llm`, instead catches every failure
  (`httpx.HTTPError`/`OSError` for connectivity, a catch-all `Exception` for structured-output
  parse failures or other client-library errors) and re-raises a typed `CVExtractionError` — the
  route turns that into a clear HTTP error rather than an unhandled 500, mirroring
  `GET /health/db`'s driver-exception-to-503 pattern.
- **Status codes**: `415 Unsupported Media Type` for a file whose extension isn't `.pdf`/`.docx`
  (raised as `UnsupportedFileTypeError`, caught in the route) — the precise standard code for "the
  payload's format is one the server doesn't handle", distinct from FastAPI's own `422` for a
  malformed request body. `503 Service Unavailable` for a `CVExtractionError` — mirrors
  `GET /health/db`'s existing precedent for "a downstream dependency (here, Ollama) is unreachable
  or failed", not an application bug.
- **`create_draft_profile`** (`app/db/profile_repo.py`) always creates a new row —
  `name=f"draft-{uuid4()}"`, `status="draft"`, `is_active=False` — and never activates it,
  distinct from `PUT /profile`'s `upsert_active_profile`, which updates the single active row in
  place. Every CV upload gets its own independent draft (since `profiles.name` is unique) rather
  than clobbering a prior unreviewed one; the user reviews the draft (US20) before choosing to
  activate it.
- **Explicit LLM request timeout**: `ChatOllama` is constructed with
  `client_kwargs={"timeout": 120}` (seconds) — every other external call in this codebase has an
  explicit timeout (ADR 0005); 120s is generous for the 8B model ADR 0011 selected on this
  machine's hardware.
- **No model-selection logic here**: the model name comes from `settings.ollama_model`
  (`app/config.py`), already resolved by ADR 0011 — this story adds no model-detection/fallback
  logic and no test targeting model choice.

### Profile editor page (P2US3)

- **Purpose**: closes Phase 2's CV-upload/edit loop end-to-end — until this story, US18/US19's
  `GET`/`PUT /profile` and `POST /profile/upload` were API-only, with no way for a human to see or
  edit a profile. `frontend/src/pages/ProfileEditorPage.tsx` composes a CV upload control with a
  full `Profile`-field form (skills, past roles, education, certifications, languages,
  preferences, deal-breakers) and Save/"Set as active" actions, mirroring the
  page/component/hook/API-wrapper layering P1US8's `OfferListPage` established.
- **localStorage-plus-`profile_id` draft-persistence design**: "Save" deliberately never activates
  (see the `PUT /profile` `activate` parameter above), so a saved-but-not-active draft has no
  `GET /profile`-reachable identity — a plain reload would otherwise lose track of which row was
  just edited and fall back to whatever *is* active (or a blank form). `frontend/src/hooks/
  useProfileEditor.ts` closes this gap by caching the full last-known `ProfileResponse` (`id`,
  `is_active`, `profile`, ...) to `localStorage` (key `recruflow.profileEditor`) after every
  successful save/activate/upload, and preferring that cached copy over a fresh `GET /profile` on
  mount. This is why the hook does not call `fetchProfile()` at all when a cached response exists
  — the cached copy already reflects the last save, which is the entire point of caching it. This
  is a deliberate, documented complexity (not an accidental one): the alternative would have been
  a new "get profile by id" GET endpoint plus a URL-based `?profileId=` scheme, rejected as
  unnecessary API surface for what a client-side cache already solves for a single-user local tool.
- **`frontend/src/api/profile.ts`**: mirrors `api/offers.ts`'s shape — `fetchProfile`,
  `saveProfile(profile, { profileId, activate })`, `uploadCv(file)`, each collapsing
  `openapi-fetch`'s `{data, error}` into a throw-on-error `Promise<T>`. `uploadCv` uses a custom
  `bodySerializer` to build a `FormData` from the picked `File` (openapi-fetch's documented pattern
  for a `multipart/form-data` operation) rather than JSON-encoding it. Error messages prefer the
  backend's own `detail` string (e.g. the `415`/`503` messages `POST /profile/upload` raises) over
  a generic fallback, falling back only when `detail` isn't a plain string (the `422` validation
  error shape is a list, not a string, and isn't declared in the generated schema for the `415`/
  `503` cases since FastAPI only documents responses it's told about via `responses=`).
- **`frontend/src/hooks/useProfileEditor.ts`**: owns all state and persistence logic so
  `ProfileEditorPage` only renders. `save()`/`activate()` set `attemptedSubmit=true` and run
  `validateProfile` first; if `hasValidationErrors`, the API is never called — this is what makes
  required-field validation actually block a save rather than merely visually warn. Initial
  hydration reads the `localStorage` cache via a lazy `useState` initializer (not inside a
  `useEffect` calling `setState` synchronously — `eslint-plugin-react-hooks`'s
  `react-hooks/set-state-in-effect` rule rejects that pattern) so the cached branch never touches
  the network at all; the effect only runs (and only calls `fetchProfile()`) when nothing was
  cached.
- **`frontend/src/lib/profileValidation.ts`**: pure functions, no I/O (mirrors
  `app/ingestion/normalize.py`'s "small pure functions" style on the Python side).
  `validateProfile(profile)` flags each list entry's required sub-field
  (`Skill.name`/`PastRole.title`+`company`/`Education.institution`/`Certification.name`/
  `Language.name` — the only "required fields" concept `Profile` has) as blank-after-trim;
  `hasValidationErrors` reduces that to a single boolean gate.
- **`frontend/src/lib/triStateBoolean.ts`**: extracted from `OfferFilters.tsx`'s previously
  locally-defined `remoteToSelectValue`/`selectValueToRemote` now that `PreferencesFields`'s
  `remote_preference: bool | null` needs the identical `'' | 'true' | 'false'` DOM-select mapping
  — `boolToSelectValue` treats both `null` and `undefined` as `''` (the wire type is `bool | None`,
  but the helper accepts either so it composes with `OfferListFilters.remote`'s `boolean |
  undefined` too). `OfferFilters.tsx` was updated to import this instead of its own copy, since a
  second real consumer existing is what justifies deduplicating now rather than pre-emptively.
- **`frontend/src/components/profile/`**: one list-editor component per repeating `Profile` field
  (`SkillsTable`, `RolesList`, `EducationList`, `CertificationsList`, `LanguagesList`,
  `DealBreakersList`), each taking the current array plus an `onChange` and performing only
  immutable updates (`map`/`filter`/spread, never in-place mutation), plus `PreferencesFields`
  (the non-repeating preference fields) and `CvUploadControl` (a hidden `<input type="file"
  accept=".pdf,.docx">` plus a visible button, self-contained loading/error state like
  `FetchNowButton.tsx`). Required-field errors are passed in as parallel boolean (or, for
  `RolesList`'s two required sub-fields, `{title, company}`) arrays rather than computed inside
  each component, so `profileValidation.ts` remains the single source of truth for what "invalid"
  means.
- **No hardcoded/placeholder form content**: every field starts from either an uploaded draft, a
  fetched active profile, or a genuinely empty value (`''`/`null`/`[]`) — there is no seed/sample
  data anywhere in the editor, satisfying this story's own acceptance criterion the same way
  P2US1 forbade seed profile data at the API layer.
- **Routing/nav**: `App.tsx` gained a second route (`/profile` → `ProfileEditorPage`) and a small
  `<nav>` with two links ("Offers"/"Profile") — `OfferListPage` previously had no navigation
  anywhere else since it was the only page; this is the minimum needed to make two pages mutually
  reachable, not a general navigation system built ahead of need.

### Unified Match Score schema (P3US21)

- **Purpose**: the foundational Phase 3 story. Every other Phase 3 story (US22's LangChain Matcher,
  US23's `sjctl evaluate` wrapper, US24's cross-engine consistency checks, US25's batch scoring job,
  US26's frontend score display) constructs or reads a `MatchScore` row against this schema, so the
  schema, the read endpoint, and the insert-never-overwrite invariant had to be locked in first. No
  new migration is needed — `match_scores` has existed since the original P0US5 migration but was
  never written to or read from until this story.
- **`MatchScore`/`MatchScoreResponse` split (`app/schemas/match_score.py`)**: mirrors `Offer`/
  `OfferSummary` exactly — `MatchScore` is the domain-input model an engine constructs before
  persistence (no `id`, since the DB assigns it on insert), `MatchScoreResponse`
  (`from_attributes=True`) is the plain, already-validated read model `GET /offers/{id}/score`
  returns straight off an ORM row (`engine`/`score_percent` as plain values, no re-validation on
  the way out).
- **`score_percent: int` (`ge=0, le=100`), not a letter grade** — as of P3US29, `MatchScore`
  reports the Matcher's rounded `weighted_total` directly rather than bucketing it into a
  five-letter grade; see the P3US29 section below for the full rationale and the migration off the
  original `Literal["A", "B", "C", "D", "F"]` design this bullet used to describe. `engine` is
  `Literal["langchain", "sjctl"]`, still a `Literal` for the same "let the type system reject an
  out-of-vocabulary value" reason (e.g. `Offer`'s `_check_salary_range`) — only `grade`'s
  categorical shape went away, not that general preference.
- **`dimensions: dict[str, float]` is an open dict by design** — no fixed key set, so either
  scoring engine can populate whatever per-dimension breakdown it produces without a schema change
  or migration, satisfying the acceptance criterion directly.
- **`GET /offers/{offer_id}/score`** (`app/api/routes/offers.py`) returns the single most recent
  `MatchScore` for the offer against whichever `Profile` is currently active
  (`app/db/profile_repo.py`'s existing `get_active_profile`, reused rather than duplicated),
  ordered by `created_at` descending — this is the one place recency is enforced, since no write
  path exists yet to enforce it on insert. Status/body contract: `404` only when `offer_id` itself
  doesn't exist (identical wording to the existing `GET /offers/{offer_id}` 404); `200` with a JSON
  `null` body when there is no active profile at all, or an active profile exists but this offer has
  no `MatchScore` row for it yet (mirrors `GET /profile`'s existing 200-with-null convention rather
  than treating either as an error); `200` with the row's fields otherwise.
- **No MatchScore-writing/persistence helper exists yet** — this story is schema-plus-read-endpoint
  only, per its own acceptance criteria; US22/US23 will each need an insert path once they exist and
  can share one if warranted then. Introducing one now would have been speculative code with no
  caller.
- **No uniqueness constraint on `(offer_id, profile_id)`** — deliberately left alone; the
  acceptance criteria require multiple `MatchScore` rows per offer over time (re-scores, or scores
  against different profiles), so a new score is always inserted, never overwritten.

### LangChain Matcher (P3US22)

- **Purpose**: built directly on P3US21's schema and read endpoint. Scores offers from all three
  sources (SOLID.Jobs, JustJoin.it, NoFluffJobs) against the active `Profile` and writes
  `MatchScore` rows. A second `sjctl evaluate` engine for SOLID.Jobs was originally planned but
  abandoned before implementation — see P3US23/P3US24 below — so this is the only scoring engine;
  US25's batch job is the entry point that will call it.
- **Module**: `app/llm/matcher.py`, structured like `app/llm/cv_extraction.py` (private
  `_build_llm`/`_build_chain`, a typed `MatcherError` wrapping `httpx.HTTPError`/`OSError` plus a
  catch-all, a module logger, a `_describe(exc)` helper). Unlike `cv_extraction.py`, this chain stays
  a **single** structured-output call: `cv_extraction.py` splits into three calls because open-ended
  list fields silently dropped items under combined input/schema/output size pressure on this local
  8B model, but `_MatcherOutput` has no list fields — six fixed floats plus one string, always
  exactly seven fields, so there's no cardinality for the model to shortcut.
- **Model**: `Settings.matcher_ollama_model`, independent of `Settings.ollama_model` (CV extraction's
  setting) so the two chains can diverge without touching each other's config. Set to `llama3.1:8b`,
  reusing CV extraction's model — see `docs/adr/0013-ollama-model-for-langchain-matcher.md`, which
  resolves OD-2 for this chain specifically rather than repeating ADR 0011's hardware reasoning: a
  looser (batch, not synchronous-request) latency budget doesn't raise the 8GB VRAM ceiling, so the
  same 7-8B-class model tier applies regardless.
- **`_MatcherOutput`** is the LLM's structured-output target: `skill_match`, `salary_fit`,
  `seniority_fit`, `work_mode_location`, `contract_type`, `red_flags` (each `float`, `0`-`1`) plus
  `rationale: str`. Field names deliberately match `DIMENSION_WEIGHTS` keys 1:1 so
  `_weighted_total`/dimension-dict-building iterate one source of truth instead of a hand-maintained
  mapping.
- **Dimension weights** (`DIMENSION_WEIGHTS`, mirrors `sjctl`'s rubric): skill match 30%, salary fit
  25%, seniority fit 15%, work mode/location 15%, contract type 10%, red flags 5%.
- **`score_percent = round(_weighted_total(output) * 100)`** (as of P3US29) — the Matcher's
  internal 0.0–1.0 weighted total is surfaced directly as a 0–100 integer, with no threshold table
  or letter-grade bucketing in between. This module originally shaped a `GradeScale` class (a
  seam explicitly built for P3US27's later configurable grade thresholds) here; P3US29 deleted
  both `GradeScale` and P3US27's `scoring_config` entirely once there was no letter left to
  calibrate — see the P3US29 section below. `DIMENSION_WEIGHTS` stays a plain dict, unaffected by
  that change — no story has ever needed configurable weights.
- **Deal-breaker cap, enforced in code, not left to the LLM**: any `Profile.deal_breakers` entry
  matched in the offer's text caps `score_percent` at a fixed `40` (`_cap_score_for_deal_breaker`,
  only ever lowers, never raises — an already-low score is left unchanged). Before P3US29 this
  capped a letter grade at `D`; the mechanism changed to a numeric ceiling but the rule itself
  (deterministic, code-level, never LLM-judged) did not.
- **Deal-breaker detection is itself deterministic, never an LLM-judged field** — see
  `docs/adr/0014-deal-breaker-detection-deterministic-not-llm.md`. Folding detection into
  `_MatcherOutput` was considered and rejected: `Offer.description`/`title`/`company` are adversarial
  third-party text, and a listing could manipulate the model into denying a real deal-breaker match,
  defeating the cap's entire purpose. `_deal_breaker_hit` instead tokenizes the deal-breaker phrase
  (lowercase, split on hyphen/underscore/slash/whitespace) and matches with an *optional* separator
  between tokens, so `"on-site only"` matches `"on-site only"`, `"onsite only"`, and `"on site only"`
  alike, while a single-token deal-breaker like `"Java"` keeps plain word-boundary anchors and so
  never matches inside `"JavaScript"`.
- **Missing-field conservatism is a code-level backstop, not prompt-only** —
  `_apply_missing_salary_conservatism` clamps `salary_fit` to `<= 0.5` and appends a note to the
  rationale whenever `Profile.salary_min` and `Profile.salary_target` are both absent, regardless of
  what the (mocked-in-tests, non-deterministic-in-production) LLM output claims. This is scoped to
  salary only, per this story's acceptance criteria; `seniority_fit` has no backing `Profile` field
  at all to be conservative about, and `work_mode_location`/`contract_type` don't get an equivalent
  backstop yet — tracked as **OD-9** in `user stories/000 high level guide.md`.
- **Routing**: `LANGCHAIN_SOURCES = frozenset({SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS})` and the pure
  predicate `is_langchain_source(connector)` decide which offers this chain scores — all three real
  connectors route here (see P3US23 below); only a `None`/unrecognised connector (e.g. a manually
  seeded `Source` row with no connector identity) is excluded.
  **`score_offers_with_langchain(session, profile_row, offers)`** is the batch entry point US25 will
  call by name: it filters to langchain-routed offers, scores each, `session.add()`s the resulting
  `MatchScore` rows, and returns them — never committing (the caller controls the transaction
  boundary, matching `app.ingestion.persist` and `app.db.profile_repo`'s convention). A single
  offer's `MatcherError` is logged at WARNING and skipped; it never aborts the rest of the batch.
- **Prompt-injection defense**: the system prompt treats `Offer.title`/`description`/`company` as
  untrusted third-party data, never as instructions, mirroring the `jobs-evaluate` skill's rubric —
  a listing that tries to instruct the model to change its scoring behavior is itself scored as a
  red flag rather than obeyed.

### SOLID.Jobs Matcher verification (P3US23)

- **Purpose**: the originally-planned second scoring engine (`sjctl evaluate`, for SOLID.Jobs only)
  was abandoned before it was ever built — P3US24 records there is only one engine, the LangChain
  Matcher, covering all three sources. This story fixed the one place P3US22 still encoded the
  abandoned two-engine plan: `LANGCHAIN_SOURCES` was `frozenset({JUSTJOINIT, NOFLUFFJOBS})`, so
  `is_langchain_source("solid_jobs")` returned `False` and `score_offers_with_langchain` silently
  skipped every SOLID.Jobs offer passed to it, with no error and no log line.
- **Fix**: `LANGCHAIN_SOURCES` now includes `SOLID_JOBS`; no other control flow in
  `app/llm/matcher.py` changed. `score_offer_with_langchain`'s per-offer logic (deal-breaker cap,
  missing-salary conservatism, structured-output call) was already source-agnostic — it operates
  purely on `Offer`/`Profile` schema fields, never on the connector string — so SOLID.Jobs offers
  needed no special-casing once routed through at all.
- **Field-mapping verification**: `app/connectors/solid_jobs.py`'s `map_solid_jobs_offer` (confirmed
  live-accurate per `docs/adr/0012-solid-jobs-direct-api-replaces-sjctl-subprocess.md`) maps every
  SOLID.Jobs field the Matcher reads onto the same `Offer` schema JustJoin.it/NoFluffJobs populate.
  When SOLID.Jobs omits an optional field (e.g. `salary`, `locations`, `experienceLevel`), the
  mapper already returns `None` for the corresponding `Offer` field rather than a placeholder, so
  the existing missing-salary conservatism (P3US22) and the LLM's own "score conservatively when a
  field is missing" instruction apply exactly as they do for the other two sources — no
  SOLID.Jobs-specific handling exists or is needed anywhere in the scoring path.

### Batch scoring job (P3US25)

- **Purpose**: US21-US24 left a schema, a read endpoint, and a fully working
  source-agnostic scoring function (`score_offers_with_langchain`), but nothing called it
  automatically, on demand, or queried which offers actually need scoring. This story is a
  pure caller/orchestration layer on top — it does not touch `app/llm/matcher.py`'s scoring
  logic at all.
- **`app/scoring/batch.py`**: `run_batch_scoring(session) -> BatchScoringSummary` is the single
  entrypoint both the scheduler hook and `POST /score/batch` call. `BatchScoringSummary` is a
  frozen dataclass (`scored`, `skipped`, `failed`). Logic: look up the active Profile
  (`app.db.profile_repo.get_active_profile`); if none, log at INFO and return an all-zero
  summary (mirrors `GET /profile`'s and `GET /offers/{id}/score`'s "no active profile is a
  normal steady state" convention). Otherwise, `_fetch_unscored_offers` and
  `_count_already_scored` both filter on `Source.connector.in_(LANGCHAIN_SOURCES)` (imported
  from `app.llm.matcher`, not re-derived) — this makes "eligible" and "what
  `score_offers_with_langchain` will actually attempt" the same set by construction, so
  `failed = len(unscored) - len(results)` never miscounts a connector-filtered offer as a
  failure. `run_batch_scoring` never commits — same convention as
  `score_offers_with_langchain` and `app.ingestion.persist`; the caller controls the
  transaction boundary. A single-line INFO log (`"batch scoring run complete: scored=%d
  skipped=%d failed=%d"`) is the per-run summary the acceptance criteria require.
- **Re-scoring on Profile change**: because `_fetch_unscored_offers` filters on
  `MatchScore.profile_id`, not a global "has this offer ever been scored" flag, switching the
  active Profile automatically makes every previously-scored Offer "unscored" again for the new
  Profile on the next run — no explicit re-scoring logic exists or is needed; it falls out of
  the query shape. Old `MatchScore` rows against the previous Profile are never deleted (US21's
  original "always insert, never overwrite" design).
- **`POST /score/batch`** (`app/api/routes/scoring.py`, `app/schemas/scoring.py`'s flat
  `BatchScoringResponse`): calls `run_batch_scoring`, commits, returns the counts. Always `200`
  — there's no per-connector routing to 404 on the way `POST /ingest/{source}` has, and
  `run_batch_scoring` never raises (mirrors `score_offers_with_langchain`'s own
  never-raise-out-of-a-batch convention).
- **Automatic post-ingestion trigger (BUG16), removed again by BUG29**: the trigger used to live
  in `app/scheduler/service.py`, called only from `_run_source_async` — meaning
  `POST /ingest/{source}` (the *only* fetch action `FetchNowButton.tsx` actually calls) never
  scored anything, ever, since it goes through a sibling code path
  (`app/ingestion/service.py`'s `_trigger_ingest_async`) that never called it. BUG16's fix moved
  `_trigger_batch_scoring_after_ingestion()` into `app/ingestion/lifecycle.py`'s
  `run_with_lifecycle` — the one call site shared by manual `/ingest`, manual `/scheduler/run`,
  and automatic APScheduler jobs alike — calling it unconditionally after `dispatch_ingestion`
  returns, on both the success and error branches. Once BUG24 added the dedicated
  `scoring:backlog` job on its own independent interval, this made *two* unsynchronized triggers
  race the same unscored backlog: an ingestion run and a `scoring:backlog` tick landing close
  together could each fetch the same "unscored" offers before either committed, producing
  duplicate `MatchScore` rows for the same offer/profile pair (BUG29, measured at ~43% wasted
  duplicate LLM calls against the live backlog). BUG29 removes
  `_trigger_batch_scoring_after_ingestion()` and both call sites in `run_with_lifecycle` entirely
  — `scoring:backlog` is now the *only* automatic trigger, exactly matching BUG24's original
  intent of a backlog-drain "fully independent of any source's ingestion schedule." Ingestion
  itself no longer scores anything; a freshly-ingested offer is picked up on the backlog job's
  next tick (or immediately via manual `POST /score/batch`), not synchronously with the fetch.
- **Mutual exclusion inside `run_batch_scoring` itself (BUG29)**: rather than trust every current
  and future caller to never overlap, `app/scoring/batch.py` now serializes all calls on a
  module-level `asyncio.Lock` (`_scoring_lock`) — `run_batch_scoring` is a thin wrapper that
  acquires the lock and delegates to `_run_batch_scoring_locked`. This is what actually closes
  the race: the scheduled `scoring:backlog` tick and a manual `POST /score/batch` call are still
  two independent callers, each opening its own session, so removing BUG16's trigger alone only
  removed one of several possible overlaps. With the lock, a second caller's own
  `_fetch_unscored_offers` query runs only after the first caller's transaction has committed, so
  it never sees an offer the first call is still in the middle of scoring.
- **No unique constraint added on `match_scores (offer_id, profile_id)`**: BUG29's own writeup
  suggested one, but P3US21 (above) already documents a deliberate decision to allow multiple
  `MatchScore` rows per offer over time (re-scores), with reads always taking the most recent row
  — `tests/integration/test_offers_routes.py`'s `test_rescoring_offer_inserts_new_row_without_overwriting_existing`
  and its two sibling "most recent score" tests exercise exactly this. A hard uniqueness
  constraint would foreclose that intentional future capability for no real benefit now that the
  actual race is closed at the trigger and lock level. BUG29 instead ships a one-off data-only
  migration (`134e4fa8b06d`) that deletes the accidental duplicate rows the race had already
  produced, keeping the newest row per `(offer_id, profile_id)` pair — pure cleanup, no schema
  change.
- **Bounded batch size and live progress (BUG16)**: with the trigger now firing on every
  ingestion door, a single manual `/ingest` call could otherwise try to score an unbounded
  backlog synchronously (this repo's dev database had ~15k offers ingested-but-never-scored by
  the time this bug was fixed, since nothing had ever scored them). `run_batch_scoring` now takes
  a `limit` (default `Settings.batch_scoring_limit`, `BATCH_SCORING_LIMIT` env var, 20) applied
  via `.limit()` on `_fetch_unscored_offers`'s query (now also `.order_by(OfferModel.id)` for
  determinism), and `BatchScoringSummary` gains a `remaining` count (`_count_unscored_offers`
  taken *before* the limited fetch, minus what was just scored) so callers know how much backlog
  is left. A module-level `ScoringProgress` singleton in `app/scoring/batch.py`
  (`get_scoring_progress()`) tracks `running`/`processed`/`total`/`remaining_backlog` for the
  current or most recent run — a local single-user tool with one API process, so no DB-backed
  job state is needed just to answer "is scoring running right now." `score_offers_with_langchain`
  (`app/llm/matcher.py`) takes an optional `on_progress: Callable[[int], None]` invoked after each
  offer (scored, failed, or skipped) so `processed` updates live during a run, not just at the
  end. `GET /scoring/status` (`app/api/routes/scoring.py`, `ScoringStatusResponse`) exposes this
  state read-only, no DB session needed.
- **Test isolation from the dev database**: this repo's local Postgres is a long-lived,
  real recruFlow instance — the live scheduler has already ingested thousands of real offers
  under the real `justjoinit`/`nofluffjobs`/`solid_jobs` connectors by the time any test runs.
  A brand-new, never-scored Profile would otherwise see every historical Offer as "unscored",
  making `scored`/`skipped`/`failed` counts nondeterministic and, worse, triggering a real
  Matcher call per historical offer. `tests/integration/test_batch_scoring.py` sidesteps this
  by monkeypatching `LANGCHAIN_SOURCES` in both `app.llm.matcher` and `app.scoring.batch` to a
  unique fake per-test connector identity, scoping each test to only the Source/Offer rows it
  creates itself, and cleans up those fake-connector Source/Offer/MatchScore rows in a
  `finally` block afterward (mirroring `test_offers_routes.py`'s own
  `_delete_sources_with_offers`, since `test_scheduler_ensure_sources.py` asserts an exact set
  of non-null connectors). `tests/integration/conftest.py` used to also carry an autouse fixture
  stubbing `batch.run_batch_scoring` to a no-op for every other integration test, plus an eager
  `import app.main` at collection time to stop that stub from being permanently baked into
  `app/api/routes/scoring.py`'s name-bound import — both existed solely to stop an
  ingestion-focused test's scheduler run from triggering a real batch-scoring pass, back when
  ingestion itself triggered scoring (BUG16). BUG29 removed that trigger entirely (see above), so
  neither guard has anything left to protect against and both were deleted along with it.

### Offer list with scores (P3US26)

- **Purpose**: purely additive on the existing US17 offer list page — zero backend changes.
  Every piece a frontend score display needs (`MatchScoreResponse` schema, the per-offer
  `GET /offers/{offer_id}/score` read endpoint, an engine that populates rows, and an automatic
  post-ingestion trigger that keeps populating them) already existed as of P3US21-P3US25; this
  story only surfaces it.
- **`frontend/src/api/schema.d.ts` regeneration**: the file was stale relative to the backend —
  no story since P3US21 had regenerated it, so it predated the score endpoint/type entirely. This
  story ran `make generate-types` against a live API before writing any code that imports
  `MatchScoreResponse` or calls the score endpoint.
- **`frontend/src/lib/grade.ts`** (deleted by P3US29, see below): originally a pure, React-free
  single source of truth for grade ordering/colour, shared by `GradeBadge`/`OfferTable`/
  `GradeFilter`. Its replacement, `frontend/src/lib/scoreColor.ts`, is described in the P3US29
  section below.
- **`frontend/src/api/offerScore.ts`**: mirrors `offers.ts`'s shape exactly —
  `fetchOfferScore(offerId): Promise<MatchScoreResponse | null>` collapses `openapi-fetch`'s
  `{data, error}` into throw-on-error, but a `null` body (no active Profile, or no MatchScore yet)
  is returned as-is, not thrown, matching the endpoint's own "`null` is a normal state" contract.
- **`frontend/src/hooks/useOfferScores.ts`**: `useOfferScores(offerIds): { scores, loading,
  refetch }`, structured like `useOffers.ts`'s inline-effect convention
  (`react-hooks/set-state-in-effect`). Keyed on `offerIds.join(',')` rather than the array
  reference itself, since a new `offerIds` array is created on every parent re-render. Uses
  `Promise.allSettled`, not `Promise.all` — mirrors `score_offers_with_langchain`'s own "one
  failure never aborts the batch" convention — so one offer's rejected fetch degrades that offer
  to `null` (the same neutral "not yet scored" state `GradeBadge` already renders for a missing
  score) without discarding any other offer's already-resolved score. `refetch` (BUG16) exists
  because the effect above only re-runs when the *offer-id list itself* changes, never just
  because a score for one of those same offers arrived later — `OfferListPage` calls it whenever
  `useScoringStatus`'s `finished_at` changes, so a score badge can appear once background scoring
  completes without the user reloading the page.
- **`frontend/src/api/scoring.ts`, `frontend/src/hooks/useScoringStatus.ts`,
  `frontend/src/components/ScoringStatusBanner.tsx` (BUG16)**: `useScoringStatus` self-paces its
  own polling of `GET /scoring/status` via `setTimeout` (not `setInterval`, so a slow response
  can't pile up overlapping requests) — 1.5s while a run is `running`, 5s otherwise. Failed polls
  are swallowed silently (best-effort; the offer list and Fetch Now button already surface their
  own errors) and keep the last-known status rather than clearing it. `ScoringStatusBanner`
  renders nothing until a run has happened at least once this session (`status.running` or
  `status.finished_at` set), then either a live `processed`/`total` progress bar or the last
  run's summary (scored/failed count, remaining backlog) — this is what surfaces the
  previously-silent "no active profile" / "LLM call failed" no-ops from
  `run_batch_scoring`/`score_offers_with_langchain` as something a user can actually see, per
  this bug's suggested fix.
- **`frontend/src/components/GradeBadge.tsx`** (replaced by `ScoreBadge.tsx`, see the P3US29
  section below): originally rendered the neutral "Not yet scored" state for
  `null`/`undefined`/any string that failed `isGrade`, otherwise a coloured badge — a `<button>`
  when the caller passes `onClick` (a scored offer), a non-interactive `<span>` otherwise (used
  standalone inside `ScoreDrawer`).
- **`frontend/src/components/ScoreDrawer.tsx`**: the first drawer/modal in this codebase, built
  with no new npm dependency — a fixed backdrop (click closes) plus a right-anchored `.card`
  panel (`role="dialog" aria-modal="true"`), an `Escape`-key listener via a `window` `keydown`
  effect, the offer title, a non-clickable score badge (`ScoreBadge` as of P3US29), the rationale
  text (falling back to `"No rationale recorded."` when `null`, since the backend schema allows
  it), and a per-dimension breakdown formatted as a percentage — unaffected by P3US29, since
  per-dimension scores stayed 0–1 floats throughout.
- **`frontend/src/components/GradeFilter.tsx`** (replaced by `ScoreFilter.tsx`, see the P3US29
  section below): originally the minimum-grade control, deliberately a separate component from
  `OfferFilters`/`OfferListFilters` rather than a new field on either.
- **`frontend/src/components/OfferTable.tsx`**: gained `scores`/`minGrade` props plus two new
  pure helpers. `filterByMinGrade` ran first, then either `sortByGrade` (if the Grade column
  header had been clicked at least once) or the existing `sortByPostedDateDesc` — filter-then-sort
  so the two composed correctly. `sortByGrade` always appended unscored offers last regardless of
  direction, mirroring `sortByPostedDateDesc`'s existing nulls-last convention; the Grade header
  was a two-state ascending/descending toggle (never back to "no sort"). Clicking a scored badge
  sets `selectedOfferId`, rendering a `ScoreDrawer` alongside the table — this part is unchanged by
  P3US29, only the badge/sort helper underneath it (see below).
- **Client-side filter/sort, not a backend change**: mirrors US17's own "sort `GET /offers`
  client-side rather than add an `ORDER BY`" precedent. `GET /offers` already had an incidental
  exact-match `grade` query parameter from P3US21, but it was unrelated to this story's
  minimum-grade filter (exact-match vs. minimum-grade are different semantics) and was
  deliberately not reused; P3US29 later deleted the exact-match param outright (see below).
- **`frontend/src/pages/OfferListPage.tsx`**: now owns `minGrade` state alongside `filters`,
  calls `useOfferScores(offers.map(o => o.id))`, and renders `GradeFilter` next to `OfferFilters`.
  The hook's own `loading` flag is intentionally not surfaced as a separate page-level loading
  state — the score badge's neutral state already covers the in-flight case.
- **Theme (`frontend/src/index.css`)**: new `--color-grade-a`/`-b`/`-c`/`-d`/`-f`/`-none` custom
  properties (A reuses the existing accent green, F reuses the existing danger red) plus a
  `.badge` base class and `.badge-grade-*` variants in the existing `@layer components` block —
  no one-off Tailwind colour utilities, per this story's own acceptance criterion. P3US29 later
  replaced the five fixed variants with a single continuous colour function (see below).
- **Superseded by BUG26**: the "client-side filter/sort, not a backend change" design above (`grade`
  vs. minimum-grade being "different semantics" so `GradeFilter`/`minGrade` deliberately stayed
  client-only) held only while `GET /offers` returned every offer unpaginated. Once the backlog
  reached 18k+ rows, an unfiltered client-side `minGrade` filter over `useOfferScores`'s
  still-arriving, per-offer-fetch `scores` map meant "10 shown" could mean "10 of thousands
  resolved so far" — not "10 actually meeting the filter" (the exact bug this table's stale
  comments predicted was possible: partial data masquerading as complete). BUG26 added a real,
  server-side `min_grade` query param (scoped to the active profile, distinct from the pre-existing
  exact-match `grade` param, which is unchanged) and moved grade data onto `GET /offers` itself, so
  `GradeFilter`/`minGrade` now drove a real API filter instead of a client-side derived one, and
  `OfferTable` no longer took `scores`/ran `filterByMinGrade` at all. **Superseded again by
  P3US29**: `min_grade` became `min_score`, and the exact-match `grade` param was deleted outright
  (no percentage-equivalent "exact match" concept was ever requested) — see the P3US29 section
  below for the current shape.

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

### Configurable grade thresholds (P3US27) — superseded by P3US29

This story added a `scoring_config` table, `ScoringConfig` schema, `scoring_config_repo.py`, a
`GET`/`PUT /scoring-config` pair, `app/llm/matcher.py`'s `build_grade_scale`, and a "Grade cutoffs"
Settings card, all in service of making US22's letter-grade thresholds user-editable. P3US29
deleted every piece of it outright rather than migrating it: once `MatchScore` reports a plain
0–100 percentage instead of a letter, there is no shared "what does B mean" calibration left for a
threshold table to hold — a minimum-score filter and an alert threshold are now each just a
number the user types in, no persisted config in between. See the P3US29 section below.

### Configurable auto-fetch cadence + Grade A sound alert (P3US28)

- **Purpose**: two independent additions bundled into one story — (1) each connector's fetch
  interval (P1US6) becomes user-editable at runtime instead of a hardcoded per-source default, and
  (2) a live, in-browser sound alert fires the moment a new offer is scored Grade A, so the user
  doesn't have to keep the offer list open to notice a strong match. (2) is also this app's first
  SSE endpoint, and per `CLAUDE.md`'s OD-8 ("SSE, not WebSocket, for push-style updates") it
  establishes the `sse-starlette` + in-process broadcaster pattern the future swarm-progress story
  (Phase 5) is expected to reuse rather than inventing its own.

- **Fetch cadence — `PUT /scheduler/sources/{source}/interval` / `PUT /scheduler/sources/interval`**
  (`app/api/routes/scheduler.py`): both take `IntervalUpdateRequest { seconds: int }`
  (`app/schemas/scheduler.py`, `Field(ge=60)` — FastAPI turns anything below the 60s floor into a
  `422` automatically, so nobody can accidentally hammer a job board). `app/scheduler/service.py`'s
  `set_source_interval`/`set_all_source_intervals` reuse `resolve_source_by_connector` (so an
  unknown connector raises the same `SchedulerLookupError` → `404` path as the existing manual
  trigger endpoint) and always write `config_json["schedule"] = {"type": "interval", "seconds":
  ...}` — this **converts** a source currently on a cron schedule (NoFluffJobs, historically) to an
  interval schedule, same as one already on interval; there is no cron-write path left in this
  story. `Source.config_json` is a plain JSONB column with no SQLAlchemy `Mutable` wrapper, so both
  functions reassign the attribute to a new dict (`source.config_json = {**source.config_json,
  "schedule": {...}}`) rather than mutating the existing dict in place — an in-place `.update()`
  would silently fail to persist, since the ORM's unit-of-work never sees the change.
- **Live rescheduling, not just a persisted config change**: both routes call
  `request.app.state.scheduler.reschedule_job(build_job_id(connector), trigger=IntervalTrigger
  (seconds=...))` immediately after committing, reusing `app/scheduler/lifecycle.py`'s existing
  `build_job_id` — the same live `AsyncIOScheduler` instance P1US6 already stashed on
  `app.state.scheduler`. The new interval therefore takes effect on that job's very next tick, not
  only after an app restart.
- **New uniform default**: `DEFAULT_SOURCE_CONFIGS` (`app/scheduler/service.py`) now seeds all three
  built-in connectors at a 300-second (5 minute) interval schedule, replacing the mixed
  interval/cron defaults P1US6 originally shipped (see the "Superseded by P3US28" note on that
  section above).
- **Frontend**: `frontend/src/api/scheduler.ts` gained `updateSourceInterval`/
  `updateAllSourceIntervals` (same throw-on-error shape as the existing `fetchSchedulerStatus`).
  `frontend/src/hooks/useFetchCadence.ts` wraps the existing `useSchedulerStatus()` (reused, not
  reimplemented) for the source list/refetch, and tracks a per-connector `saving: Record<string,
  boolean>` map plus a shared `error` string — each row saves independently, and a successful save
  calls `refetch()` so the row reflects the persisted value without a full reload.
  `frontend/src/components/FetchCadenceSection.tsx` renders one row per connector (labelled via the
  existing `KNOWN_SOURCES` constant), a minutes `<input>` pre-filled from that connector's current
  `schedule.seconds / 60`, and a single "apply to all" control that pushes one value to every
  connector via the bulk endpoint (minutes→seconds conversion happens at this UI boundary — the API
  layer only ever deals in seconds). `SettingsPage.tsx` renders this alongside the existing
  scoring-config card; the pre-existing scoring-config "Save" button gained `aria-label="Save
  scoring config"` purely to keep it distinguishable from each cadence row's own "Save" button in
  tests, with no visible UI change.

- **Grade A sound alert — `app/scoring/events.py`** (new module; renamed/generalised by P3US29,
  see below): the in-process Grade A broadcaster, and the reference implementation for OD-8's
  SSE-not-WebSocket seam. A module-level `_subscribers: set[asyncio.Queue[GradeAEvent]]`,
  `subscribe()`/`unsubscribe()`/`publish_grade_a()` — deliberately a plain global, the same "local
  single-user tool, one API process" justification `app/scoring/batch.py`'s `ScoringProgress`
  singleton already uses. `publish_grade_a` used `put_nowait` on an unbounded `asyncio.Queue`, so
  it never blocked and never raised — a slow/stalled SSE client could never stall the scoring
  pipeline that publishes to it. P3US29 kept this exact mechanism and only renamed the
  dataclass/functions and added a field — see below.
- **Publish call sites**: `BatchScoringSummary` (`app/scoring/batch.py`) gained a fifth field,
  `grade_a_events: tuple[GradeAEvent, ...] = ()`, following the exact precedent BUG16 set when it
  added `remaining: int = 0` to this same frozen dataclass. `run_batch_scoring` computed it after
  scoring completes, via an explicit `await session.flush()` (required: `score_offers_with_langchain`
  only `session.add()`s each new `MatchScore`, never flushes, so `row.id` is `None` until something
  forces a flush). The two places that already call `run_batch_scoring` and commit —
  `POST /score/batch` and the dedicated backlog-draining job's `_run_scoring_job_async` (BUG24) —
  both looped over `summary.grade_a_events` and called `publish_grade_a`. P3US29 renamed the field
  to `score_events` and dropped the Grade-A-only filter — see below.
- **`GET /scoring/events`** (`app/api/routes/scoring.py`): an `EventSourceResponse`
  (`sse-starlette`) whose generator `subscribe()`s on connect, loops on
  `asyncio.wait_for(queue.get(), timeout=15)` (the timeout only bounds how often it re-checks
  `request.is_disconnected()` when nothing has been published — it does not add latency to a
  genuinely published event, since `queue.get()` returns immediately once something is enqueued),
  and `unsubscribe()`s in a `finally` so a disconnected client's queue is always removed. This SSE
  mechanism, the "no replay/catch-up/baseline" delivery guarantee, and the timeout/disconnect
  handling are all unchanged by P3US29 — only the event's name and payload shape changed (see
  below).
- **Frontend**: `frontend/src/api/client.ts`'s `baseUrl` constant is now exported (the only change
  to that file) since `EventSource` cannot go through `openapi-fetch` and needs the same base URL
  `apiClient` already uses. `frontend/src/hooks/useGradeAAlerts.ts` (replaced by `useScoreAlerts.ts`
  in P3US29, see below) opened exactly one `new EventSource(`${baseUrl}/scoring/events`)` in a
  `useEffect` with an empty dependency array, called once from `App.tsx` above the `<Routes>`
  switch — so exactly one connection exists per browser tab regardless of which page is active, and
  it closes on unmount. This connection-lifecycle shape is unchanged by P3US29.
- **`frontend/src/lib/sound.ts`**: a small, dependency-free Web Audio synth (not a literal port of
  ZzFX, which optimizes for byte count over readability) — `playAlertSound(sound, volume)`
  constructs a `new AudioContext()`, schedules 1–3 short square/triangle-wave oscillator notes via a
  `GainNode` set from `volume`, and closes the context once the last note's envelope ends; `volume
  <= 0` is a no-op guard (belt-and-braces alongside the caller's own mute gate) that never
  constructs an `AudioContext` at all. Completely untouched by P3US29 — only its caller changed
  what gates the call.
- **`frontend/src/lib/gradeAlertPrefs.ts`** (replaced by `scoreAlertPrefs.ts` in P3US29, see
  below): pure, React-free `localStorage` read/write, mirroring the precedent set by
  `grade.ts`/`scoringConfigValidation.ts`. Sound choice, volume, and mute lived under a single JSON
  blob at `localStorage["recruflow.gradeAlertPrefs"]` — **client-only UX preference, not
  server-side domain state** — there was deliberately no backend table or endpoint for these three
  fields, a design P3US29 kept and extended.
- **`frontend/src/components/NotificationsSection.tsx`**: a sound dropdown (`ALERT_SOUNDS`), a
  volume slider, a mute checkbox, and a "Test sound" button that calls `playAlertSound` directly —
  bypassing the SSE stream entirely, since it's a local preview, not a simulated event. Every change
  handler updates local state and persists immediately; unlike the scoring-config and cadence
  sections, there is no separate explicit Save step for this section. P3US29 added a fourth control
  (minimum score for alert) to this same pattern — see below.

### Percentage-based match score (P3US29)

- **Purpose**: every prior Phase 3 story hardcoded, threaded through, or built UI around a
  five-bucket letter grade, even though the Matcher already computed a continuous 0.0–1.0
  `weighted_total` internally (P3US22) and discarded it the moment a letter was picked. This story
  stops discarding it: `MatchScore.score_percent = round(weighted_total * 100)` is now the
  headline field everywhere a `grade` used to be. It fully supersedes P3US27 (a plain percentage
  needs no shared calibration table) and revises the grade-shaped acceptance criteria of
  P3US21/P3US26/P3US28 to their percentage equivalents, without reopening any of their unrelated
  design decisions (the "200 with null body" convention, the deal-breaker-detection-is-deterministic
  ADR, the SSE broadcaster mechanism, the bounded-batch-plus-drain-job design) — those all stay
  exactly as described above.
- **Schema/DB**: `match_scores.grade` (`String(1)`) is dropped and `match_scores.score_percent`
  (`Integer`, not null) added via two chained Alembic migrations
  (`ae533f38f5b2_match_scores_score_percent`, `ae9db2ab1e4a_drop_scoring_config`). Because this
  repo's real dev database already carried scored rows with no persisted `weighted_total` (only
  the letter), the first migration backfills `score_percent` from a deterministic midpoint of each
  grade's original default threshold band (A→92, B→77, C→62, D→47, F→20) before adding the
  `NOT NULL` constraint — a one-time, documented approximation for pre-existing rows only; every
  row scored after this migration runs gets a real computed value, and old rows are treated as
  immutable historical records either way (this codebase's existing "never rewrite a persisted
  score" convention). The second migration drops the now-orphaned `scoring_config` table outright
  (no backfill needed — nothing downstream reads it anymore). `MatchGrade`/`GRADE_ORDER`
  (`app/schemas/match_score.py`) are deleted; `GradeScale`/`_GRADE_THRESHOLDS`/`build_grade_scale`
  and the `grade_scale` parameter on both `score_offer_with_langchain`/`score_offers_with_langchain`
  (`app/llm/matcher.py`) are deleted outright — nothing constructs a grade from a threshold table
  anymore. `_cap_grade_for_deal_breaker` is replaced by a pure `_cap_score_for_deal_breaker`, which
  does exactly `min(score_percent, 40)` — the old grade-D cutoff, now a plain constant
  (`_DEAL_BREAKER_SCORE_CAP`), not user-configurable.
- **`scoring_config` deleted outright, not migrated**: the `ScoringConfig` schema,
  `scoring_config_repo.py`, and `GET`/`PUT /scoring-config` are all removed — see the P3US27
  section above.
- **Offer list**: `app/schemas/offer.py`'s `OfferSummary.grade: str | None` is renamed/retyped to
  `score_percent: int | None` (`ge=0, le=100`); `GET /offers`'s exact-match `grade` query param is
  deleted outright (never consumed by the frontend, and no percentage-equivalent "exact match"
  concept was ever requested); `min_grade` is replaced by `min_score: int` (0–100). The
  `min_score` filter reuses the existing `latest_score` per-offer subquery, just comparing
  `score_percent >= min_score` instead of a `GRADE_ORDER`-slice membership check — simpler than the
  letter-grade version, and correct by construction for "unscored offers excluded": SQL's
  `NULL >= min_score` evaluates to unknown/false, so no separate `IS NOT NULL` clause is needed.
  Frontend: `GradeBadge`/`GradeFilter`/`lib/grade.ts` are deleted; `ScoreBadge`
  (`frontend/src/components/ScoreBadge.tsx`) renders the numeric percentage (`"82%"`) with a
  colour computed by a new `frontend/src/lib/scoreColor.ts` — a continuous
  red→yellow→green HSL interpolation (`hue = score/100 * 120`, fixed 70%/42% saturation/lightness)
  computed directly from `score_percent`, not a five-bucket class lookup, so no configuration is
  involved in what colour a score renders. `ScoreFilter` replaces `GradeFilter` with a plain
  0–100 numeric input (defaulting to unset). `OfferTable.tsx`'s `sortByGrade` becomes `sortByScore`
  — a pure numeric comparison, still appending unscored offers last regardless of sort direction,
  matching the prior nulls-last convention. The score drawer (`ScoreDrawer.tsx`) is otherwise
  untouched: per-dimension scores stay 0–1 floats, rationale text is unaffected.
- **Sound alert generalised, not just renamed**: `app/scoring/events.py`'s `GradeAEvent`/
  `publish_grade_a` become `ScoreEvent`/`publish_score`, keeping the exact same
  `asyncio.Queue`-per-subscriber broadcaster mechanism, plus one new field, `score_percent`. The
  behavioural change is in *when* an event fires: `run_batch_scoring`'s `score_events` tuple
  (renamed from `grade_a_events`) is now built unconditionally over every scored result, not
  filtered to `row.grade == "A"` — every `MatchScore` committed by the batch job or
  `POST /score/batch` now publishes exactly one `score` SSE event (renamed from `grade_a`),
  carrying `{score_id, offer_id, title, company, score_percent}`. The "what counts as worth
  alerting on" decision moves entirely to the client: `useScoreAlerts.ts` (replacing
  `useGradeAAlerts.ts`) still opens exactly one `EventSource`, but now parses every event's JSON
  payload and only calls `playAlertSound` when `score_percent >= ` the user's configured threshold,
  read fresh from `localStorage` via `loadScoreAlertPrefs()` on *each* incoming event (not once at
  mount) — this is what makes a threshold change in Settings take effect on the very next event
  without the hook reconnecting. `frontend/src/lib/scoreAlertPrefs.ts` (renamed from
  `gradeAlertPrefs.ts`, storage key `recruflow.scoreAlertPrefs` — a hard rename, not a migration;
  any value under the old key is simply orphaned) gains a fourth field, `minScorePercent`
  (default `90`). `NotificationsSection.tsx` gains a matching "Minimum score for alert (%)" numeric
  input, using the same load-merge-persist pattern as the existing sound/volume/mute controls.
  Muting and "Test sound" behave exactly as before — the threshold only gates whether an incoming
  event plays a sound, never whether the SSE stream itself runs.
- **Settings page cleanup**: the entire "Grade cutoffs" card (four `grade_a`..`grade_d` inputs,
  `useScoringConfig`, `scoringConfigValidation.ts`) is removed from `SettingsPage.tsx` — there is
  nothing left to configure at the domain level once grading is gone. The page now renders only
  Fetch cadence (P3US28, unchanged) and Notifications (this story's updated section).
- **Theme (`frontend/src/index.css`)**: the five `--color-grade-*` custom properties and
  `.badge-grade-*` classes are removed (colour is now computed inline via a `style` prop, not a
  CSS class); `--color-grade-none`/`.badge-grade-none` are renamed to `--color-score-none`/
  `.badge-score-none`, keeping their declarations unchanged — the neutral "not yet scored" state
  itself is unaffected by this story.

### Makefile targets

- `install` — `uv sync --all-groups` + `cd frontend && pnpm install`.
- `format` — `uv run ruff format .` + `cd frontend && pnpm format`.
- `lint` — `uv run ruff check .` + `uv run mypy .` + `cd frontend && pnpm lint`.
- `typecheck` — `uv run mypy .` + `cd frontend && pnpm run typecheck` (`tsc -b`, i.e. build mode
  — plain `tsc --noEmit` is a no-op against the references-only root `tsconfig.json`, since it
  has `files: []` and only `-b`/`--build` traverses `references`; fixed in P0US7 after discovering
  `pnpm run typecheck` was silently passing regardless of real type errors in `src/`).
- `test` / `test-unit` / `test-integration` — `uv run pytest`, scoped by the `integration`
  marker. Python-only.
- `test-frontend` (P1US8) — `cd frontend && pnpm test` (`vitest run`). Deliberately **not** part
  of `ci`/`test` yet — see `docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md`.
- `ci` — runs `format lint typecheck test` in sequence; now covers both stacks since `lint`,
  `format`, and `typecheck` each fan out to the frontend toolchain.
- `clean` — removes `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`,
  `build`.
- `up` — `docker compose up --build`; brings up all four Compose services with hot reload for
  `api` and `frontend` (P0US4).
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
- The `Dockerfile` runtime stage installs `curl`/`ca-certificates` via `apt-get` — kept solely for
  the `api` healthcheck above (`CMD curl -f http://localhost:8000/health`), not for anything
  SOLID.Jobs-related anymore (BUG10 removed the sjctl installer that used to be this block's other
  reason to exist; removing the block entirely broke the healthcheck, since nothing else in the
  image provides `curl` — caught by this story's own manual end-to-end test, not by `make ci`).
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
