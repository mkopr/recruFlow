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
  `pydantic-settings`, `httpx`, `apscheduler`. Later phases add further runtime deps here
  incrementally (`langchain`/`langgraph`/`langchain-ollama` in P3US2, `playwright` in P5US6,
  `weasyprint`/`python-docx` in P4US4/P6US4) as the story that needs them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`.

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
| `match_scores` | Structured evaluation of one Offer against a Profile (grade A–F + dimensions) | FKs to `offers`/`profiles`; `engine` distinguishes LangChain vs. `sjctl` scoring; `GET /offers?grade=` (P1US7) is its first read-side consumer, but the table remains write-side-empty until Phase 3 ships a scorer |
| `applications` | Record of intent/action to apply | FKs to `offers`/`profiles`/`cv_versions`; `status` one of `drafted`/`reviewed`/`sent`/`failed`/`interview`/`offer`/`rejected` (unconstrained string, not a DB enum) |
| `scheduler_runs` (P1US6) | One row per ingestion run, automatic or manual — the scheduler's audit trail | FK to `sources`; index on `(source_id, started_at)` for cheap "latest row per source" lookups; `status` one of `running`/`ok`/`error` (unconstrained string, same no-DB-enum convention as `applications.status`); `fetched_count`/`created_count` nullable `Integer` (null only while `status="running"`); `warning` `Boolean` (zero-result flag, see below); see "Scheduler" below |

`make migrate` runs `docker compose exec api alembic upgrade head` (mirrors the `sjctl-version`
pattern — `DATABASE_URL`'s `db` hostname only resolves inside the Compose network, not from the
host). `make seed` runs `docker compose exec api python -m app.db.seed`, loading three sample
offers and one active stub profile; both targets are idempotent.

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

### SOLID.Jobs connector (P1US2)

- **`app/connectors/solid_jobs.py`** — the first of three sibling connectors
  (P1US2–US4: SOLID.Jobs, JustJoin.it, NoFluffJobs), and the only one needing no scraping
  investigation since sjctl already handles fetch/cache/rate-limiting. Exposes
  `run_solid_jobs_ingestion(session, source, *, campaign, force_refresh=False) -> IngestionResult`
  as the single public entrypoint later stories (P1US6 scheduler, P1US7 ingestion API endpoint)
  will call — it does not commit the session (same convention as `persist_offer`) and does not
  create or seed a `Source` row itself.
- **`sync` vs `search` subcommand selection drives cache behavior** (see
  `docs/adr/0001-solid-jobs-sync-vs-search-cache-strategy.md`): sjctl has no single "bypass cache"
  flag, so `force_refresh=False` (default) runs `sjctl sync` — which only reports offers not
  already seen by sjctl's own saved watches, take no config-derived filters, and is what
  satisfies "respects the local cache unless explicitly requested" — while `force_refresh=True`
  runs `sjctl search` with filters read from the Source row's `config_json`, always hitting the
  live API. These are not two variations of the same query: `sync` is scoped to whatever watches
  were separately configured via `sjctl watch add`; `search` is scoped to `config_json` and does
  not consult watches at all.
- **`config_json` schema for a SOLID.Jobs Source row** (de facto until a later story formalises
  it further): `division` (str, defaults to `"IT"`) → `-d`; `cities` (list[str]) → repeated
  `--city`; `min_salary` (int) → `--min-salary`; `experience_levels` (list[str]) → repeated
  `--experience`; `terms` (list[str]) → repeated `--term`, the technology/free-text filter (e.g.
  `["python"]`). `build_search_args` does no validation of these — a malformed config value fails
  loudly via `str()` coercion rather than being silently dropped, since `config_json` is
  already-validated-at-write-time internal configuration, not user input.
- **`--campaign` is a real, global sjctl flag** (confirmed against a live `sjctl v0.3.0` install,
  not just the vendored skill docs), appended to every invocation from `Settings.sjctl_campaign`.
- **The sjctl JSON contract was verified against a live binary, not trusted from the skill
  docs** (see `docs/adr/0002-sjctl-contract-verified-against-live-binary.md`) — the vendored
  `jobs-search`/`jobs-digest` `SKILL.md` prose names fields (`companyName`, flat `salaryFrom`,
  `city`, `remote`, `publishedAt`) that do not match what sjctl v0.3.0 actually emits. Real shape,
  as mapped by `map_sjctl_offer`:
  - `search --json` wraps offers under `"jobs"` (not `"offers"`); an offer has `company` (not
    `companyName`), an array `locations` (not a single `city`), a boolean `isRemote` plus a
    separate `isHybrid` with no equivalent in `Offer`, a nested `salary: {from, to, currency,
    employmentType}` (not flat `salaryFrom`/`salaryTo`/`salaryCurrency`), and `validFrom` (not
    `publishedAt`).
  - `sync --json` wraps each new offer as `{"watch": "<name>", "offer": {...}}` — a structural
    difference the skill docs don't mention at all — and reports `"new": null` (not `[]`) when
    there are no new offers, which `_extract_offers` treats as zero results, not a malformed
    response.
  - `_extract_offers(payload, list_key, *, item_key=None)` handles both shapes: `item_key=None`
    for `search` (bare offer dicts under `"jobs"`), `item_key="offer"` for `sync` (unwraps the
    `{watch, offer}` envelope under `"new"`) — so `map_sjctl_offer` only ever sees a bare offer
    dict regardless of which subcommand produced it.
  - `locations` (list) → `Offer.location` (single string): joined with `", "`. `isHybrid` is
    dropped from the normalised field — `Offer.remote` is `isRemote` only, not `isRemote OR
    isHybrid`, since folding hybrid into "remote" would misrepresent hybrid roles (raw `isHybrid`
    is still preserved in `raw_payload`). `contract_type` maps from `salary.employmentType`
    (`"UoP"`/`"B2B"`) rather than the top-level `contractTime` (`"full_time"`/`"part_time"`), since
    "contract type" in this domain means employment form, not work-time schedule (see the
    `Remote` and `Contract Type` glossary entries in `CLAUDE.md`). `description` is stored as the
    raw HTML sjctl returns, unstripped — HTML-to-text is deferred to whichever later phase
    actually needs plain text (CV tailoring).
- **`_run_sjctl`** is the sole subprocess boundary and the only place that can fail without
  crashing the caller: catches `OSError` (covers a missing binary and permission failures, wider
  than just `FileNotFoundError`) and `subprocess.TimeoutExpired` around the `subprocess.run` call
  itself, then separately checks `returncode != 0` and `json.JSONDecodeError` on the parsed
  stdout — every one of these paths logs at `ERROR` and returns `None` rather than raising.
  `run_solid_jobs_ingestion` turns a `None` from either `_run_sjctl` or `_extract_offers` into
  `IngestionResult(ok=False, fetched=0, created=0)`.

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
  no `campaign` parameter (that's a SOLID.Jobs/sjctl-specific concept, not applicable here). Does
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
- **Field mapping** (`map_justjoinit_offer`), from the confirmed list-item shape:

  | `Offer` field | Source field(s) | Notes |
  |---|---|---|
  | `external_id` | `guid` | |
  | `canonical_url` | `slug` | Built as `https://justjoin.it/job-offer/{slug}` (singular `job-offer`; confirmed by following the `/offers/{slug}` → `/job-offer/{slug}` redirect live) — the list endpoint has no direct URL field |
  | `title` | `title` | |
  | `company` | `companyName` | |
  | `location` | `locations[].city` | Joined with `", "` (mirrors `map_sjctl_offer`'s location join); falls back to top-level `city` if `locations` is empty |
  | `remote` | `workplaceType` | JustJoin.it's own 3-value enum is `{"remote", "hybrid", "office"}` — mapped to a canonical `bool` via `app.ingestion.normalize.normalize_remote` (P1US5); this happens to already satisfy the `Remote` glossary rule that hybrid is not remote |
  | `seniority` | `experienceLevel` | Mapped to the shared canonical vocabulary via `app.ingestion.normalize.normalize_seniority` (P1US5) — see "Cross-connector schema consistency" below |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `employmentTypes[0].{from,to,currency,type,gross}` | **Known limitation**: a JustJoin.it offer can list several employment-type entries (e.g. both `b2b` and `permanent`, each further repeated per display currency); only the first/primary entry is mapped, matching the same simplification `map_sjctl_offer` was allowed for SOLID.Jobs's own multi-field shape. Salary values arrive as floats and are coerced to `int` for the `Integer` DB column; currency and the `gross` flag are passed through `normalize_salary` (P1US5), which logs (but does not fabricate a conversion for) non-`PLN` currencies and `gross: false` figures. `contract_type` remains a raw pass-through of `type` — permanently, not deferred — per the `Contract Type` glossary entry being explicitly out of scope for vocabulary unification |
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
  treated as zero offers, matching sjctl's `"new": null` handling.
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
  `"Regular"` (confirmed live via `sjctl search`), previously passed straight into `Offer.seniority`
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
  already enforces its own request timeout (`sjctl`'s subprocess call and both HTTP connectors'
  `httpx.get` calls all pass an explicit `timeout`), so an in-flight job always finishes or times
  out within a bounded window.
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
  reads `campaign=get_settings().sjctl_campaign` internally so all three adapters present the same
  `(session, source, force_refresh) -> IngestionResult` signature despite `solid_jobs` needing an
  extra keyword argument underneath. `resolve_source_by_connector(session, connector) -> Source`
  raises `UnknownConnectorError` if `connector` isn't a `CONNECTOR_REGISTRY` key at all,
  `SourceNotConfiguredError` if it's a known connector with no matching `Source` row yet, and
  otherwise returns the row; `dispatch_ingestion(session, source)` assumes the caller already
  resolved/validated `source.connector` (asserts non-`None`) and calls straight through the
  registry. Both `app.scheduler.service` and `app/api/routes/ingestion.py` call
  `resolve_source_by_connector` + `dispatch_ingestion` directly rather than duplicating
  connector-selection logic.

- **Non-blocking execution model — why job callables are plain `def`, not `async def`**: see
  `docs/adr/0005-scheduler-jobs-must-be-plain-sync-callables.md` for the full reasoning; summary
  here. `AsyncIOScheduler` shares uvicorn's single event loop and only offloads a job to its thread
  pool when the registered callable is a plain function — an `async def` job runs directly on the
  main loop instead. None of the three connectors are actually non-blocking on their own (`sjctl`
  via blocking `subprocess.run`; the two HTTP connectors via synchronous `httpx.get`), so an
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
  own internally-handled failure (e.g. `sjctl` binary missing, an HTTP transport error) already
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

- **`GET /offers`** and **`GET /offers/{offer_id}`** (`app/api/routes/offers.py`) use `SessionDep`
  (plain read-only `SELECT`s, no blocking I/O underneath, unlike the ingest trigger) and join
  `Offer` to `Source` explicitly via `select(...).join(...)` — no ORM `relationship()` is defined
  anywhere in `app/db/models.py`, matching the codebase-wide convention. Two private, pure mapping
  helpers, `_offer_summary`/`_offer_detail`, are unit-tested without a database
  (`tests/test_offers_mapping.py`) since `OfferModel` instances can be constructed in memory.
  `GET /offers` has no pagination in this story — acceptable at current single-machine data volumes;
  add `limit`/`offset` if/when P1US8's table needs it, which is a backwards-compatible addition.

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

  **`grade`**: an `EXISTS`-style subquery — `Offer.id IN (SELECT offer_id FROM match_scores WHERE
  grade = :grade)` — against `match_scores`, a table that has no writer until Phase 3 ships (so this
  filter matches nothing against real data today). Deliberately **not** scoped to the active
  `Profile` (`Profile.is_active`) or to a specific `engine`: it matches if *any* recorded
  `MatchScore` row for the offer has the given grade, regardless of which profile or engine produced
  it. Revisit this scoping once Phase 3 defines how `MatchScore` rows actually relate to
  profiles/engines over time (e.g. whether a profile edit re-scores or leaves stale grades behind).

  ```bash
  curl "http://localhost:8000/offers?source=justjoinit&remote=true&seniority=senior&min_salary=15000"
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
- **`frontend/src/hooks/useOffers.ts`**: owns `offers`/`loading`/`error` state and re-fetches when
  `source`/`remote`/`seniority`/`minSalary` change. Structured around
  `react-hooks/set-state-in-effect` (part of `eslint-plugin-react-hooks`'s `recommended` config,
  already wired up since P0US7) — this rule statically rejects an effect calling any hoisted (e.g.
  `useCallback`) function that eventually calls a state setter, even past an `await`, so the
  automatic fetch-on-filter-change effect defines and invokes its own async function *inline*,
  duplicating (rather than delegating to) `refetch`'s fetch-and-setState logic. `refetch` itself
  is safe as a `useCallback` because it's only ever invoked from an event handler
  (`FetchNowButton`'s click), never from within an effect.
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
- **`frontend/src/components/OfferTable.tsx`**: `GET /offers` (P1US7) has no `ORDER BY` — this
  component sorts client-side by `posted_at` descending (nulls last) before rendering, rather than
  the backend gaining an `ORDER BY` (kept as "reuse without modification" per this story's scope).
  Salary formatting distinguishes a floor from a ceiling rather than collapsing both to the same
  string: `"20,000+ PLN"` (min only), `"up to 25,000 PLN"` (max only), `"15,000-25,000 PLN"`
  (both), `"-"` (neither); a `null` `salary_currency` on an offer with a known salary defaults to
  display `"PLN"` (matching the DB column's own `server_default`, see "Database schema" above),
  never left blank. Empty state (`offers.length === 0 && !loading`) renders a message instead of
  an empty `<table>`; a bounded-height (`max-h-[70vh]`), `overflow-y-auto` wrapper keeps a large
  result set scrollable rather than requiring pagination, since `GET /offers` has none.
- **`frontend/src/pages/OfferListPage.tsx`**: the page shell — holds `filters` state, renders the
  three `FetchNowButton`s, `OfferFilters`, an inline error banner when `useOffers().error` is set,
  and `OfferTable`.
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
  marker. Python-only.
- `test-frontend` (P1US8) — `cd frontend && pnpm test` (`vitest run`). Deliberately **not** part
  of `ci`/`test` yet — see `docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md`.
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
