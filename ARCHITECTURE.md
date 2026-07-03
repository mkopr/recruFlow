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
  `pydantic-settings`, `httpx`. Later phases add further runtime deps here incrementally
  (`langchain`/`langgraph`/`langchain-ollama` in P3US2, `playwright` in P5US6,
  `weasyprint`/`python-docx` in P4US4/P6US4) as the story that needs them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`.

`httpx` moved from `test`-only to `main` in P1US3 (the JustJoin.it connector): it previously only
backed FastAPI's `TestClient` in tests, but `app/connectors/justjoinit.py` is production code that
imports it directly as its HTTP client.

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
| `sources` | A job board connector (SOLID.Jobs, JustJoin.it, NoFluffJobs) | `name` unique; `config_json` (JSONB) per-source config |
| `offers` | A normalised job posting with exactly one Source | `dedup_hash` unique + indexed (dedup on canonical URL, P1US1 fallback to title+company+location); `canonical_url` nullable (P1US1 — not every source guarantees a stable URL); `description` nullable `Text` (P1US1); `raw_payload` (JSONB, ELT raw payload always populated at ingest) |
| `profiles` | Candidate's structured facts: skills, experience, preferences | `name` unique; `is_active` (only one row active at a time, enforced by application logic, not a DB constraint); `data` (JSONB) |
| `cv_versions` | Tailored CV + cover letter drafted for one Offer/Profile pair | FKs to `offers`/`profiles`; `status` string (no DB enum, so later statuses need no migration) |
| `match_scores` | Structured evaluation of one Offer against a Profile (grade A–F + dimensions) | FKs to `offers`/`profiles`; `engine` distinguishes LangChain vs. `sjctl` scoring |
| `applications` | Record of intent/action to apply | FKs to `offers`/`profiles`/`cv_versions`; `status` one of `drafted`/`reviewed`/`sent`/`failed`/`interview`/`offer`/`rejected` (unconstrained string, not a DB enum) |

`make migrate` runs `docker compose exec api alembic upgrade head` (mirrors the `sjctl-version`
pattern — `DATABASE_URL`'s `db` hostname only resolves inside the Compose network, not from the
host). `make seed` runs `docker compose exec api python -m app.db.seed`, loading three sample
offers and one active stub profile; both targets are idempotent.

A second migration (`aa3fa339111b`, chained after `df5297add8cb`) makes `offers.canonical_url`
nullable and adds `offers.description` (nullable `Text`). Both changes were deferred from the
P0US5 migration deliberately — P0US5 only had to create "all v1 tables", not pin the exact
`offers` shape — and are resolved by P1US1 (see below) once the canonical `Offer` schema and dedup
strategy needed to know the real constraints existed.

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
- **Pagination is bounded, not exhaustive, by design**: `meta.totalItems` was observed as a flat
  `10000` regardless of actual result count (almost certainly a capped/estimated figure), and a
  deep cursor (`from=9999`) returned a bare `500` from JustJoin.it's own API — looping until
  `meta.next.cursor` is `null` would be both slow (potentially 100 pages at the default page size)
  and fragile. `run_justjoinit_ingestion` instead loops up to a configurable `max_pages` (default
  `5`), sleeping `rate_limit_delay_seconds` (default `1.0`) between page fetches for politeness,
  and stops gracefully — keeping whatever was already fetched — if a page fetch fails after the
  first page succeeded; only a first-page failure marks the whole result `ok=False`. This is a
  documented known limitation: a full backfill of JustJoin.it's entire listed inventory is out of
  scope for this story and would need a smarter incremental strategy (e.g. an early-stop once N
  consecutive already-seen `dedup_hash`es are encountered, similar in spirit to sjctl's `sync`
  mode) if a later story needs it.
- **Field mapping** (`map_justjoinit_offer`), from the confirmed list-item shape:

  | `Offer` field | Source field(s) | Notes |
  |---|---|---|
  | `external_id` | `guid` | |
  | `canonical_url` | `slug` | Built as `https://justjoin.it/job-offer/{slug}` (singular `job-offer`; confirmed by following the `/offers/{slug}` → `/job-offer/{slug}` redirect live) — the list endpoint has no direct URL field |
  | `title` | `title` | |
  | `company` | `companyName` | |
  | `location` | `locations[].city` | Joined with `", "` (mirrors `map_sjctl_offer`'s location join); falls back to top-level `city` if `locations` is empty |
  | `remote` | `workplaceType == "remote"` | JustJoin.it's own 3-value enum is `{"remote", "hybrid", "office"}` — passed through directly, not translated to a new vocabulary (US14's job); this happens to already satisfy the `Remote` glossary rule that hybrid is not remote |
  | `seniority` | `experienceLevel` | Raw pass-through (e.g. `"manager"`), no vocabulary translation |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `employmentTypes[0].{from,to,currency,type}` | **Known limitation**: a JustJoin.it offer can list several employment-type entries (e.g. both `b2b` and `permanent`, each further repeated per display currency); only the first/primary entry is mapped, matching the same simplification `map_sjctl_offer` was allowed for SOLID.Jobs's own multi-field shape. Salary values arrive as floats and are coerced to `int` for the `Integer` DB column |
  | `posted_at` | `publishedAt` | ISO datetime string, parsed by `Offer`'s pydantic validation |
  | `description` | *(not mapped — always `None`)* | **Known limitation**: the list endpoint's offer objects do not include the job description body; only the per-offer detail endpoint (`GET /api/candidate-api/offers/{slug}`) has it, and fetching that per offer would multiply request volume for every ingestion run. `description` is nullable on `Offer`, so this is schema-compliant; a later story could add a bounded per-offer detail fetch if the description text becomes necessary (e.g. for CV tailoring) |

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
