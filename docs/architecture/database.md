# Database schema

[Architecture index](../../ARCHITECTURE.md)

### `app/db/` package

- `base.py` — a single `Base(DeclarativeBase)` that every ORM model and Alembic's
  `target_metadata` share, so migrations autogenerate off the same metadata the app queries
  against.
- `models.py` — the six v1 tables plus `scheduler_runs` (see "Database schema" below).
- `session.py` — `get_database_url() -> str` (reads `DATABASE_URL`, raises `RuntimeError` if
  unset — fails loudly rather than silently defaulting to the wrong database),
  `get_engine() -> AsyncEngine`, `get_sessionmaker(engine: AsyncEngine | None = None) ->
  async_sessionmaker[AsyncSession]`. No FastAPI dependency lives here — the API's `get_db`
  dependency builds directly on top of `get_sessionmaker()`, so this module is the single reusable
  entrypoint for both Alembic and the application.
- `seed.py` — `run_seed(session: AsyncSession) -> None`, used by `make seed`. Uses Postgres
  `INSERT ... ON CONFLICT DO NOTHING` keyed on each table's natural unique column (`sources.name`,
  `offers.dedup_hash`, `profiles.name`) so it is safe to re-run. `_seed_offers` builds a
  canonical `app.schemas.offer.Offer` per seed entry and calls `app.ingestion.persist.persist_offer`
  rather than hand-rolling its own dedup/insert statement — the seed path exercises the same
  ingestion code every connector will use, instead of a second, divergence-prone implementation.

## Database schema

Alembic (async template) is wired to `app/db/base.py`'s `Base.metadata` via `alembic/env.py`,
which reads `DATABASE_URL` from the environment at runtime rather than from `alembic.ini` (kept
blank) — matching `.env.example`, one source of truth for the connection string. The v1 migration
creates all six tables spanning every phase's domain nouns up front, so no later phase needs a
repeated foundational migration:

| Table | Purpose | Key columns / constraints |
| --- | --- | --- |
| `sources` | A job board connector (SOLID.Jobs, JustJoin.it, NoFluffJobs) | `name` unique; `config_json` (JSONB) per-source config; `connector` nullable `String(50)` (see below) |
| `offers` | A normalised job posting with exactly one Source | `dedup_hash` unique + indexed (dedup on canonical URL, with a fallback to title+company+location); `canonical_url` nullable (not every source guarantees a stable URL); `description` nullable `Text`; `raw_payload` (JSONB, ELT raw payload always populated at ingest) |
| `profiles` | Candidate's structured facts: skills, experience, preferences | `name` unique; `is_active` (only one row active at a time, enforced by application logic, not a DB constraint); `data` (JSONB) |
| `cv_versions` | Tailored CV + cover letter drafted for one Offer/Profile pair | FKs to `offers`/`profiles`; `status` string (no DB enum, so later statuses need no migration) |
| `match_scores` | Structured evaluation of one Offer against a Profile (`score_percent` 0-100 + dimensions) | FKs to `offers`/`profiles`; `engine` distinguishes LangChain vs. `sjctl` scoring; `score_percent` `Integer` not null (replaced an earlier `grade` `String(1)` column) |
| `applications` | Record of intent/action to apply | FKs to `offers`/`profiles`/`cv_versions`; `status` one of `drafted`/`reviewed`/`sent`/`failed`/`interview`/`offer`/`rejected` (unconstrained string, not a DB enum) |
| `scheduler_runs` | One row per ingestion run, automatic or manual — the scheduler's audit trail | FK to `sources`; index on `(source_id, started_at)` for cheap "latest row per source" lookups; `status` one of `running`/`ok`/`error` (unconstrained string, same no-DB-enum convention as `applications.status`); `fetched_count`/`created_count` nullable `Integer` (null only while `status="running"`); `warning` `Boolean` (zero-result flag, see below); see "Scheduler" below |

`make migrate` runs `docker compose exec api alembic upgrade head` (mirrors the pattern used by
other `docker compose exec api ...` Make targets — `DATABASE_URL`'s `db` hostname only resolves
inside the Compose network, not from the host). This is now mostly a manual escape hatch — the
`api` container's entrypoint (see "Docker Compose services" in deployment.md) already runs
`alembic upgrade head` on every start, including against a fresh database, so `make up` alone is
enough for a clean checkout. `make seed` runs
`docker compose exec api python -m app.db.seed`, loading three sample
offers; both targets are idempotent. (A later story removed this seed's previous stub-profile row — see
"Profile data model" in profile.md.)

A second migration (`aa3fa339111b`, chained after `df5297add8cb`) makes `offers.canonical_url`
nullable and adds `offers.description` (nullable `Text`). Both changes were deferred from the
initial migration deliberately — that migration only had to create "all v1 tables", not pin the exact
`offers` shape — and are resolved once the canonical `Offer` schema and dedup
strategy needed to know the real constraints existed.

A third migration (`12bc4e296410`, chained after `aa3fa339111b`) adds `sources.connector`
and creates `scheduler_runs` plus its `(source_id, started_at)` index — see "Scheduler" in ingestion.md.
