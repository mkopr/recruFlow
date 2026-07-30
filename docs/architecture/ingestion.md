# Ingestion pipeline

[Architecture index](../../ARCHITECTURE.md)

### Offer schema and dedup strategy

- **`app/schemas/offer.py`** — `Offer(BaseModel)`, the canonical, source-agnostic shape every
  connector (SOLID.Jobs, JustJoin.it, NoFluffJobs) maps its source-specific payload
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
    (the same idempotent-upsert idiom `seed.py` already used previously), followed by a re-`SELECT`
    by `dedup_hash` since `RETURNING` doesn't surface the pre-existing row's `id` on conflict. The
    returned `bool` is `True` only when a row was actually inserted, so a caller batching many
    offers (the scheduler, described below) can report new-vs-seen counts. Deliberately out of scope: a
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

### Content-based duplicate detection (company + title + salary)

- **Purpose**: `dedup_hash` only catches re-ingesting the *same posting from the same source*
  (or, via its fallback, an exact title/company/location match). It misses the same job reposted
  on a *different* job board under a *different* canonical URL — a real, growing problem now that
  9 connectors are registered. `_find_content_duplicate` (`app/ingestion/persist.py`) adds a
  second, independent signal for exactly that case.
- **Mechanism**: a plain `SELECT` (no unique index behind it) run at the top of `persist_offer`,
  before the existing `dedup_hash`/insert logic. It matches on `OfferModel.company == offer.company`,
  `OfferModel.title == offer.title` (both exact-string, post-trim, case-sensitive — no
  normalization in this pass), and `salary_min`/`salary_max`/`salary_currency` all equal via
  Postgres's `IS NOT DISTINCT FROM` rather than `=`, since ordinary SQL equality never matches
  `NULL = NULL` and two postings that both omit a salary should still count as matching on it. A
  hit short-circuits `persist_offer` and returns `(existing_row, False)` — the same return
  contract as a `dedup_hash` hit, so every caller (`ingest_offer`, `run_paginated_ingestion`, every
  connector) needs zero changes, and a content-duplicate counts toward
  `run_paginated_ingestion`'s `consecutive_already_seen` early-stop exactly like a hash-duplicate
  already does.
- **Global, not per-source**: the check is not scoped to a Source or connector, since the
  motivating scenario is one job appearing across connectors. A consequence: when a
  cross-connector content-duplicate is detected, the surviving row keeps the `source_id` of
  whichever connector ingested it *first* — the second connector's ingestion run reports it as
  already-seen and gets zero new rows under its own `source_id`.
- **Independent of `dedup_hash`** — this does not replace or modify `dedup.py`'s hash/fallback
  logic; both mechanisms run, and either can independently cause a skip. If both would match the
  same incoming offer it is still only skipped once, since `persist_offer` returns on the first
  hit. See `docs/adr/0028-content-based-duplicate-detection-is-independent-of-dedup-hash.md` for
  why this is deliberately a second signal rather than a change to the existing fallback, why
  exact-equality (no salary tolerance, no currency conversion) was chosen, and why company/title
  normalization was deferred.
- **Accepted limitations**: no DB-level uniqueness constraint backs this (a standard unique index
  treats every `NULL` as distinct, the opposite of what the salary NULL-safe match needs), so two
  concurrent `persist_offer` calls for the same content-duplicate can both pass the check and both
  insert — a narrow, accepted race mirroring this project's existing accepted stance on concurrent
  `/ingest` triggers. Company/title comparison is case-sensitive with no legal-suffix
  normalization (`"Acme"` and `"ACME"` are not deduped).
- **Visibility**: a skipped content-duplicate is logged at `INFO` (company, title, salary, and the
  matched row's `id`) but adds no new field to `IngestionResult`, `IngestResponse`,
  `ManualRunResponse`, or `SourceStatus`, and needs no frontend change — a deliberate, smaller v1
  scope per this project's minimal-numeric-UI preference.

### Cross-connector schema consistency

- **Purpose**: the three connectors were originally built in isolation, each one's own test file
  saying explicitly that no cross-source vocabulary unification happened there yet. This
  effort was the integration checkpoint — all three connectors were run and their output compared
  field by field before the scheduler and ingestion API (described below) started depending on them
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

### Scheduler

- **Purpose**: all three connectors exist and produce comparable `Offer` rows, but nothing yet
  calls them automatically or on a schedule, and nothing reports on what happened when they ran.
  This effort wires `APScheduler` into the FastAPI lifespan, gives each source its own
  configurable schedule, and adds a manual trigger endpoint plus a status endpoint. The ingestion
  API endpoints (described below) add their own `POST /ingest/{source}` reusing this dispatch seam
  (see "Registry/dispatch design" below) — this per-source ingestion scheduler is distinct from
  the later, separate Digest job, and this single-run zero-result warning is distinct from a later
  two-consecutive-run escalation and dedicated `/health/sources` endpoint planned for the
  hardening phase — both are explicitly out of scope here.

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
- **Real behavioral change, documented deliberately**: before this, FastAPI could start even
  with the DB down (only `/health/db` would fail per request). After this, startup itself
  calls `ensure_sources_exist`/`register_jobs`, so the app now fails to start if the DB is
  unreachable or unmigrated. `docker-compose.yml`'s `api` service `depends_on: db: condition:
  service_healthy` only guarantees Postgres itself is up, not that `alembic upgrade head` has
  already run — `make up` alone does not run migrations; `make migrate` must be run once against a
  fresh database before the `api` container will start cleanly. This is a real, new coupling,
  not a defect to silently work around.

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
  **Superseded later**: all three built-in connectors now default to a uniform interval
  schedule of 300s (5 minutes) instead of the mixed values above, and every source's interval is
  user-editable at runtime via `PUT /scheduler/sources/{source}/interval` — see the "Configurable
  auto-fetch cadence" notes below.

- **`scheduler_runs` table, not `sources.last_run_*` columns**: a new table rather than columns on
  `sources`, matching the project's existing ELT/audit-trail instinct (raw payloads are always kept,
  not overwritten) — this keeps `GET /scheduler/status` queryable by "latest row per source" cheaply
  via the `(source_id, started_at)` index, and leaves headroom for a later two-consecutive-run
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

- **`Source.last_fetched_at` is not a violation of the "no `sources.last_run_*` columns"
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
  so the ingestion package now owns the dispatch seam its name always promised, and
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

- **`force_refresh` is now genuinely threaded through every connector, not just `solid_jobs`** —
  `_dispatch_justjoinit`/`_dispatch_nofluffjobs` used to accept `force_refresh` (to
  satisfy the shared `Connector` protocol) and then silently drop it, so the interface promised
  uniform behavior none of the connectors but `solid_jobs` actually had. Fixed per-connector, not
  by dropping the parameter, since JustJoin.it turned out to have real meaning to give it:
  `run_justjoinit_ingestion(..., force_refresh=True)` now bypasses the incremental-pagination
  early-stop checkpoint (see ADR 0009), walking pagination all the way to `max_pages` regardless of
  the consecutive-already-seen streak — see `docs/adr/0010-force-refresh-threaded-through-all-connectors.md`.
  NoFluffJobs has no equivalent checkpoint to bypass (no pagination loop at all, per ADR 0009
  above), so `run_nofluffjobs_ingestion` accepts `force_refresh` for interface parity and documents
  in-line why it's a deliberate no-op rather than continuing to swallow it silently one layer down.

- **Non-blocking execution model — why job callables are plain `def`, not `async def`**: see
  `docs/adr/0005-scheduler-jobs-must-be-plain-sync-callables.md` for the full reasoning; summary
  here. `AsyncIOScheduler` shares uvicorn's single event loop and only offloads a job to its thread
  pool when the registered callable is a plain function — an `async def` job runs directly on the
  main loop instead. None of the three connectors are actually non-blocking on their own (all
  three call synchronous `httpx.get`, since SOLID.Jobs' subprocess call was later removed in
  favor of a direct HTTP call), so an
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
  returns `IngestionResult(ok=False, fetched=0, ...)` rather than raising (an established
  connector convention) — from the scheduler's perspective this is indistinguishable from a
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
  `SourceStatus.last_fetched_at` is read straight off `Source.last_fetched_at` (see above)
  rather than derived from the joined `SchedulerRun` — it is `None` for a source that has never
  completed a run.

### Ingestion API endpoints

- **Purpose**: all three connectors now run automatically on a schedule and produce
  comparable, deduplicated, persisted `Offer` rows, but nothing yet lets a job seeker force an
  out-of-band fetch through a dedicated ingestion-facing endpoint, or browse/inspect what has
  actually been stored. This adds `POST /ingest/{source}`, `GET /offers`, and
  `GET /offers/{offer_id}` to close that gap. It is the direct dependency for the offer list
  page (frontend, described below), which builds a table against `GET /offers` and wires a
  "Fetch now" button per source to `POST /ingest/{source}`.

- **`POST /ingest/{source}`** (`app/api/routes/ingestion.py` + `app/ingestion/service.py`) reuses
  the scheduler's dispatch seam directly — `resolve_source_by_connector` + `dispatch_ingestion`
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
  non-blocking execution model established for the scheduler (ADR 0005), and for the identical
  reason: none of the three connectors are internally non-blocking, so calling `dispatch_ingestion`
  directly from a `SessionDep`-based route handler would block `/health` and every other route for
  the run's duration. Verified mechanically by
  `tests/integration/test_ingestion_routes.py::test_health_endpoint_responds_during_ingest_run`.
  **`_trigger_ingest_async` also sets `source.last_fetched_at` on `result.ok`** — this is
  not a `scheduler_runs` write (ADR 0006's "not scheduler-audited" stance is unchanged and still
  applies to the run-history table) but a checkpoint on `Source` itself, and a job-seeker's
  on-demand "Fetch now" click is exactly the kind of successful fetch that checkpoint needs to
  reflect; leaving it scheduler-runs-only would make the Offers page's own source-status display
  go stale immediately after the button it sits next to was clicked.

- **Shared engine/session/dispatch lifecycle**: `_trigger_ingest_async` and
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
  behaviour) — a double-tap of the "Fetch now" button can start two overlapping runs; dedup
  still prevents duplicate rows, so the cost is wasted work, not data corruption. Debouncing that is
  a frontend concern, not this endpoint's.

- **`force_refresh` defaults to `False` on `POST /ingest/{source}` (reverses an earlier decision,
  ADR 0008)**: `_trigger_ingest_async` used to hardcode `force_refresh=True` unconditionally — a
  decision ADR 0008 made to work around SOLID.Jobs' old `sjctl sync`/`search` mode switch (later
  fixed). Once ADR 0012 replaced `sjctl` with a direct-HTTP connector, `force_refresh`'s only
  remaining effect for every connector (SOLID.Jobs, JustJoin.it) is bypassing the incremental
  pagination `consecutive_already_seen` early-stop (ADR 0009), so the hardcoded `True` silently
  defeated that incremental checkpoint on every single "Fetch now" click — the only fetch action
  reachable from the UI, since `FetchNowButton.tsx` has no way to pass a flag through `triggerIngest`/
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
  **Paginated, ordered, and scored inline**: `GET /offers` originally had no pagination
  ("acceptable at current single-machine data volumes") and no `ORDER BY` at all — fine until the
  backlog crossed ~18k rows, at which point an unfiltered request returned every row in one
  response and Postgres's scan order had no relationship to recency or scoring progress. It now
  takes `limit` (default 50, max 200) and `offset` (default 0) and always applies
  `ORDER BY posted_at DESC NULLS LAST, created_at DESC, id DESC` — the same ordering already
  applied to `_fetch_unscored_offers` (`app/scoring/batch.py`), so "top of the table" and "scored
  first" are finally the same offers. The response is now an envelope,
  `{"items": [...], "total": <count ignoring limit/offset>}`, so a client can page without a
  second request. Each item also now carries `score_percent: int | null` (renamed/retyped from
  `grade: str | null`, see the percentage-based match score section in matching.md) — the active
  profile's most recent `MatchScore.score_percent` for that offer, joined in via a `ROW_NUMBER()
  OVER (PARTITION BY offer_id ORDER BY created_at DESC)` subquery scoped to the active profile (or
  to a sentinel `-1` profile id when there's no active profile, so the query shape never branches)
  — eliminating the one-`GET /offers/{id}/score`-request-per-offer fan-out the frontend previously
  did to render score badges for a loaded page.

  **`order_by`/`order`**: after the `ORDER BY` fix above, clicking the frontend's "Score"
  column header only re-sorted whatever 50 rows the current page already held, so "sort by score"
  never surfaced the actual best/worst-matched offers across the full (18k+) backlog, only within
  whatever page the fixed `posted_at DESC` order happened to place them on. `GET /offers` now takes
  `order_by` (`posted_at` default, or `score_percent`) and `order` (`asc`/`desc`, default `desc`),
  applied to the query **before** `LIMIT`/`OFFSET` so a requested page reflects the full dataset's
  order. Score-sorted results always place unscored offers (`score_percent IS NULL`) last via
  `.nulls_last()` regardless of `order` direction — matching the frontend's prior client-side
  convention — with the existing `posted_at DESC NULLS LAST, created_at DESC, id DESC` chain kept as
  a tiebreaker beneath it. On the frontend, clicking the "Score" header
  (`OfferTable.tsx`) no longer sorts the already-fetched `offers` prop locally; it calls an
  `onScoreHeaderClick` callback owned by `OfferListPage.tsx`, which flips `order_by`/`order` state,
  resets to page one (same as any other filter change), and flows through `useOffers.ts` into a
  server refetch.

  **`source`**: the response's `source` field is the connector identity string
  (`Source.connector`), falling back to `Source.name` when `connector` is `NULL` (covers
  non-scheduler-managed `Source` rows, e.g. `app/db/seed.py`'s `"seed"` fixture row) — a `source`
  field is never null in a response. The `?source=` query filter, however, matches **only**
  `Source.connector`, not `Source.name` — a deliberate asymmetry: a non-scheduler-managed source's
  offers are visible in an unfiltered `GET /offers` (displaying its `name` as `source`) but cannot
  be selected via `?source=`. This is accepted for v1 since only the three real connectors are ever
  filtered on in practice.

  **`seniority`**: substring match (`ILIKE '%value%'`) against the possibly comma-joined
  `Offer.seniority` column (see `normalize_seniority` above) — `?seniority=senior` matches an offer
  stored as `"senior, lead"`. Safe against false positives because none of the five canonical
  levels (`junior`/`mid`/`senior`/`lead`/`expert`) is a substring of another.

  **`min_salary`**: "meets or exceeds" semantics — matches when `salary_max >= min_salary`, or,
  when `salary_max` is unknown, falls back to `salary_min >= min_salary`.

  **`grade`** (deleted later, once scoring moved to a percentage): originally an `EXISTS`-style
  subquery — `Offer.id IN (SELECT offer_id FROM match_scores WHERE grade = :grade)` — against
  `match_scores`. Deliberately **not** scoped to the active `Profile` (`Profile.is_active`) or to
  a specific `engine`, and never consumed by the frontend; the param was removed outright rather
  than inventing a percentage-equivalent "exact match" concept nobody had asked for.

  **`min_score`** (renamed from `min_grade`, int 0–100): a "minimum acceptable score"
  filter — `min_score=50` keeps offers scored 50 or higher, dropping lower and not-yet-scored
  offers. Scoped to the active profile only (it reuses the same inline-score join described
  above), matching what the frontend's "Minimum score %" input conceptually means: the active
  profile's own bar, not any profile's. Before the percentage-based score, this was `min_grade`, a
  five-value `GRADE_ORDER` slice; the underlying comparison is now a plain `score_percent >=
  min_score`.

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

### CORS

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

### Dead letter queues

- **Purpose**: every handled, anticipated failure up to this point (a malformed scraped record, a
  page that failed to fetch mid-run, a whole run's first-page fetch failing, an LLM matcher call
  raising `MatcherError`) was caught, logged at WARNING/ERROR, and silently dropped — no durable,
  queryable trace survived a container restart. This adds one record-and-list-and-retry
  capability that every existing catch site now calls into. It covers all three sources
  end-to-end: SOLID.Jobs, JustJoin.it, and NoFluffJobs are all scored via the same LangChain
  Matcher path (see "SOLID.Jobs Matcher verification" in matching.md), so there is no separate
  `sjctl evaluate` scoring path left uncovered.
- **`DeadLetterMixin`** (`app/db/models.py`): `id`, `dedup_key` (`String(255)`, unique per table),
  `failure_type` (`String(30)`), `error_message` (`Text`), `raw_payload` (`JSONB`, nullable),
  `status` (`String(20)`, `"open"`/`"resolved"`/`"abandoned"` — see "Automatic 403/429 retry"
  below for the third value — plain string per this repo's no-DB-enum convention), `occurred_at`
  (`DateTime(timezone=True)`, last-occurrence timestamp), `resolved_at` (nullable).
  `IngestionFailure` (`ingestion_failures`) adds `source_id` (FK `sources.id`),
  `scheduler_run_id` (FK `scheduler_runs.id`, nullable — null for manually-triggered failures,
  per ADR 0006), `page` (nullable), and (US49) `url` (`Text`, nullable — the specific posting URL
  a per-URL detail-fetch failure was recorded for), `blocked_status` (`Integer`, nullable — the
  HTTP status, always `403` or `429`, of a block-shaped fetch failure; `NULL` for every other
  failure shape), `retry_count` (`Integer`, `server_default="0"` — attempts spent by the
  automatic `dlq:retry_403` job specifically, not manual retries via `/failures`). `ScoringFailure`
  (`scoring_failures`) adds `offer_id` (FK `offers.id`), `profile_id` (FK `profiles.id`) — none of
  US49's new columns apply to scoring failures. Each ingestion-failure table gets a composite
  index mirroring `scheduler_runs`' `(source_id, started_at)` convention: `(source_id,
  occurred_at)`, plus (US49) `(status, blocked_status)` for the retry job's selection query;
  `scoring_failures` keeps its own `(offer_id, occurred_at)` index. Migrations:
  `7130773ba67b_dead_letter_queues`, `a1c2d4e6f8b0_detail_fetch_blocked_dlq`.
- **One row per resource, not one row per occurrence** — see
  `docs/adr/0016-dead-letter-rows-are-mutable-per-resource-not-append-only.md`. `dedup_key`
  identifies the failing *resource*: the job posting's `canonical_url` for `validation_failed`
  (falling back to `source_id:title:company` when `canonical_url` itself is missing/invalid);
  `source:{source_id}` for `page_fetch_failed` and `run_fetch_failed` — these two share one row
  per source, since page position isn't a stable identity across retries; `offer:{offer_id}:profile:{profile_id}`
  for `scoring_failed`; (US49) `source:{source_id}:detail_url:{sha256(url)}` for
  `detail_fetch_blocked` — a raw posting URL isn't guaranteed to fit `String(255)`, so it's
  hashed (`app.dlq.service.build_detail_url_dedup_key`) rather than embedded directly, and it's
  per-*source-and-URL* (not just per-URL) so the same posting URL colliding across two sources
  can never collide on one row. A recurring failure re-opens and updates the existing row in place
  (`status="open"`, `resolved_at=NULL`, fresh `error_message`/`occurred_at`) rather than
  appending a sibling row.
- **`app/dlq/service.py`**: `record_failure(session, model_cls, *, dedup_key, **fields) -> None`
  is a Postgres upsert (`pg_insert(...).on_conflict_do_update(index_elements=["dedup_key"], ...)`
  — the same idiom `persist_offer` already uses for offer dedup), wrapped in `try/except
  Exception` and logging at ERROR on failure, never raising: a bug in the dead-letter write path
  must not take down the ingestion/scoring call site it instruments. It's `async` (not the
  synchronous `session.add`-only design an append-only version would allow) because an upsert
  needs `await session.execute(...)`. Does not commit — the caller's existing transaction-boundary
  convention is unchanged. `list_failures(session, model_cls, *, limit, offset, filters) ->
  tuple[Sequence[Any], int]` mirrors `GET /offers`'s pagination/total-count-subquery pattern,
  ordering by `occurred_at DESC`.
- **`app/dlq/registry.py`**: `DEAD_LETTER_REGISTRY: dict[str, DeadLetterQueueSpec]` mirrors
  `CONNECTOR_REGISTRY`'s `dict[str, ...]` shape, with each spec owning everything
  process-specific rather than the route branching on `process ==`: `filterable_params` (the
  query-param names — not column names — accepted for that process: `{"source", "failure_type",
  "status"}` for ingestion, `{"offer_id", "profile_id", "failure_type", "status"}` for scoring),
  `build_filters` (an async callable resolving those params into `list_failures`'s filter dict —
  `_build_ingestion_filters` does the `source` connector-name → `source_id` lookup,
  `_build_scoring_filters` just passes `offer_id`/`profile_id` through), and
  `build_item_response`/`build_list_response` methods wrapping `response_schema.model_validate`
  so the route resolves the response-type union via one `cast()` at the call site instead of a
  second `if process ==` branch. A future process (e.g. Phase 4/5's send queue) is one more
  registry entry — the route body is unchanged.
- **`app/dlq/retry.py`**: `RETRY_HANDLERS: dict[str, RetryHandler]`, keyed by `failure_type`
  (flat across both tables, since the five `failure_type` strings are globally unique) rather
  than by process, because retry mechanics differ per failure type, not per table.
  `validation_failed` re-runs `Offer.model_validate(row.raw_payload)` then `persist_offer` on
  success. `scoring_failed` re-runs `score_offer_with_langchain(...)` then adds a `MatchScore`
  row on success. `page_fetch_failed`/`run_fetch_failed` both call `trigger_ingest(connector)`
  wholesale — there's no finer-grained stored input to replay, so "retry" means "re-run the
  source's ingestion" — and succeed when `result.ok`. These two handlers deliberately do **not**
  update `row` themselves on failure: because they share the `source:{id}` dedup key, a fresh
  failure from the re-triggered ingestion lands on this exact row via the ordinary
  `record_failure` upsert (in a *different* session, since `trigger_ingest` owns its own
  engine/session lifecycle) — `perform_retry` calls `session.refresh(row)` afterward to pick that
  up rather than trusting its own possibly-stale copy. (US49) `detail_fetch_blocked`'s
  `_retry_detail_fetch_blocked` is the one finer-grained exception to "retry means re-run the
  whole source": it looks up the row's `source_id`, dispatches through
  `CONNECTOR_REGISTRY[source.connector].detail_retry(session, source, row.url)` — set only for
  Bulldogjob/Rocket Jobs/Pracuj.pl (see below) — which re-fetches and persists exactly that one
  URL. A `None` `row.url` (shouldn't happen in practice, but the column is nullable) or a
  `BlockedFetchError` raised by the retry itself both call `_mark_still_failing(row, ...)`
  directly (unlike the two handlers above, this failure type's dedup key is already unique per
  URL, so there's no separate session whose upsert would otherwise race this one) and return
  `False`. `perform_retry(session, row)` is the shared success/failure envelope: on success, sets
  `status="resolved"` + `resolved_at`; on failure, either the handler already updated `row` in
  place (validation/scoring/detail-blocked) or a refresh picks up the externally-recorded update
  (fetch failures); either way it commits.
- **Six write call sites**: `normalize_and_validate` (`app/ingestion/persist.py`, now
  `async` and takes a leading `session` param) records `validation_failed` before returning
  `None`; `run_paginated_ingestion` (`app/ingestion/runner.py`) records `page_fetch_failed` when
  a page after the first returns `None`; `app/scheduler/service.py`'s `on_success` and
  `app/ingestion/service.py`'s manual-trigger `on_success` (newly added — the manual flow
  previously passed no `on_success` callback at all) both record `run_fetch_failed` when
  `result.ok` is `False`, **fixing a real bug in the same commit**: `result.error_message` on an
  `ok=False` result was previously discarded entirely by the scheduled path, with
  `scheduler_runs`' own status/warning semantics left completely untouched (`finish_run_ok`'s
  call is unchanged — a `run_fetch_failed` row is additive, not a replacement audit trail).
  `score_offers_with_langchain` (`app/llm/matcher.py`) records `scoring_failed` in its existing
  `except MatcherError` branch before continuing to the next offer. (US49) `SitemapDetailPageConnector._run_over_urls`
  (`app/connectors/sitemap_detail.py`, shared by Bulldogjob/Rocket Jobs) and `PracujConnector.run`
  (`app/connectors/pracuj.py`) both accumulate a `blocked: list[tuple[str, int]]` out-param
  through their per-URL detail-fetch loop and, once the run's own `run_paginated_ingestion` call
  returns, record one `detail_fetch_blocked` row per `(url, status)` pair.

#### Block-shaped fetch failures (403/429) and the automatic `dlq:retry_403` retry job

- **Purpose**: confirmed live 2026-07-29, Rocket Jobs' detail-page fetch was failing 210/210
  (100%) with `403 Forbidden` and producing zero new offers for over a day, with nothing
  recording, surfacing, or retrying it — a failed detail fetch was (and for every *other*
  connector still is, for a non-block failure) just a logged-and-dropped `continue`. This adds a
  way to tell a bot-block apart from an ordinary transient failure, record the block-shaped ones
  durably, and automatically retry them later — after a cooldown, via a fresh proxy/context, not
  inline in the same run (BUG43 found a fresh context/IP, not elapsed time within the same run,
  is what clears this operator's Cloudflare Managed Challenge).
- **`BlockedFetchError`** (`app/connectors/http.py`): raised by `_get` (and therefore every one
  of its four thin wrappers — `fetch_json`/`fetch_xml`/`fetch_gzip_xml`/`fetch_text` — propagate
  it unchanged, none of them catch it) when the *last* of its `_MAX_PROXY_ATTEMPTS` proxy-rotated
  attempts failed with an HTTP 403 or 429 specifically (`httpx.HTTPStatusError`, distinguished
  from the generic `httpx.HTTPError` catch that still just returns `None`). Every other failure
  shape — timeout, connection error, 5xx, malformed response, or an *earlier* attempt's 403 that a
  later attempt recovers from — is completely unchanged: still returns `None`, never raises.
  `SitemapDetailPageConnector._fetch_detail_html` (its own duplicated httpx retry loop, not
  routed through `_get`) and `PracujConnector`'s Playwright-driven `_fetch_rendered_page` /
  `_fetch_html_with_proxy_rotation` got the identical treatment, so all three detail-page-fetch
  connectors (Bulldogjob, Rocket Jobs, Pracuj.pl) raise the same exception for the same shape of
  failure regardless of transport. `_fetch_rendered_page`'s known limitation: a *200-status*
  Cloudflare challenge page (`_is_challenge_page`) is deliberately **not** treated as a block for
  this purpose — only status-code-based 403/429 is in scope.
- **`IngestionResult.blocked_status: int | None`** (`app/ingestion/types.py`) threads the status
  code up through every bulk connector's single interception point,
  `run_paginated_ingestion`'s `await asyncio.to_thread(fetch_page, ...)` call
  (`app/ingestion/runner.py`) — catching `BlockedFetchError` there and passing `blocked_status`
  through to both the `page_index == 0` `IngestionResult` and the later-page `record_failure`
  call is what gives SOLID.Jobs/JustJoin.it/NoFluffJobs/RemoteOK/Remotive/We Work Remotely
  block-status tagging on their existing `page_fetch_failed`/`run_fetch_failed` rows with **zero
  per-connector code changes** — they all already funnel through this one call site.
  `record_run_fetch_failure` (`app/ingestion/lifecycle.py`) forwards `result.blocked_status` onto
  `run_fetch_failed` rows the same optional way it already forwards `scheduler_run_id`. This is
  purely a *tag* on the existing whole-source failure rows for these six connectors — it changes
  nothing about when or whether the row is written, matching the story's explicit scope
  boundary: only the three detail-page connectors get the new per-URL mechanism below.
- **Per-URL retry for the three detail-page connectors**: `JobBoardConnector.supports_detail_retry() -> bool`
  (default `False`) and `async def retry_detail_fetch(session, source, url) -> bool` (default
  raises `NotImplementedError`) are two more `base.py` hooks in the same default-then-override
  shape as `supports_fetch_scope`/`apply_fetch_scope_term`. `SitemapDetailPageConnector` and
  `PracujConnector` both override them: `retry_detail_fetch` re-fetches the one URL (via
  `asyncio.to_thread` for the sitemap-detail connectors' synchronous httpx call — required per
  BUG42, since this retry job's tick runs on the app's own event loop, not a per-connector worker
  thread; via a fresh single-use Playwright browser for Pracuj.pl), parses it, and on success
  calls `normalize_and_validate` + `persist_offer` directly — the same two-step `ingest_offer`
  does, but split so a validation failure and a persist can both be observed by the caller as a
  plain `bool`. `ConnectorSpec.detail_retry: DetailRetry | None` (`app/ingestion/registry.py`) is
  wired to exactly these three specs (Bulldogjob, Rocket Jobs, Pracuj.pl); every other spec
  leaves it `None`.
- **`app/dlq/retry.py::run_detail_retry_batch(session, *, min_age_seconds, max_attempts) -> DetailRetrySummary`**:
  one tick of the job. Selects every `IngestionFailure` row with `status="open"`,
  `blocked_status IS NOT NULL`, and `occurred_at` older than `min_age_seconds` —
  **deliberately not filtered by `failure_type`**: an open, sufficiently-old, block-tagged row is
  eligible regardless of whether it's the new per-URL `detail_fetch_blocked` (dispatches to
  `_retry_detail_fetch_blocked`) or one of the six bulk connectors' now-tagged
  `page_fetch_failed`/`run_fetch_failed` rows (dispatches to the existing whole-source
  `_retry_fetch_failed`) — `perform_retry`'s existing `failure_type`-keyed dispatch already
  handles that branching, so the selection query doesn't need to. A row already at
  `retry_count >= max_attempts` is flipped straight to `status="abandoned"` without spending
  another attempt (still visible/manually-retryable via `/failures`, just no longer picked up
  here); otherwise `retry_count` is incremented and `perform_retry` is called (which commits
  internally, so this function never double-commits). `DetailRetrySummary` (frozen dataclass:
  `attempted`/`resolved`/`still_blocked`/`abandoned`) is the per-tick return value logged by the
  job.
- **`dlq:retry_403` scheduled job**: mirrors BUG24's `scoring:backlog` job exactly —
  `DETAIL_RETRY_JOB_ID = "dlq:retry_403"`, `register_detail_retry_job(scheduler, *,
  interval_seconds)` (`app/scheduler/lifecycle.py`) registers `run_detail_retry_job`
  (`app/scheduler/service.py`) directly as a coroutine (not the sync-wrapper-plus-thread-pool
  pattern connector runs use) with `IntervalTrigger`, `max_instances=1`, `coalesce=True`,
  `replace_existing=True`, so a slow tick chains into the next instead of overlapping. Owns its
  own `get_engine()`/`get_sessionmaker(engine)`/session lifecycle per tick, exactly like
  `run_scoring_job`. Registered in `app/main.py`'s `lifespan` alongside `register_jobs`/
  `register_scoring_job`. Three new `Settings` fields (`app/config.py`):
  `detail_retry_job_interval_seconds` (default `300`, the job's own poll cadence),
  `detail_retry_min_age_seconds` (default `1800` — the cooldown before an open blocked row is
  even eligible, giving a source's next few ordinary ingestion cycles a chance to pass first),
  `detail_retry_max_attempts` (default `5`).
- **Visibility**: no new UI — `GET /failures/ingestion` and `POST /failures/ingestion/{id}/retry`
  work unchanged against `detail_fetch_blocked` rows and the new `status="abandoned"` value
  (`Literal["open", "resolved", "abandoned", "all"]` on the route's `status` query param); a
  count shown anywhere stays a bare number per this project's minimal-numeric-UI convention.
- **`GET /failures/{process}`** (`app/api/routes/failures.py`): `process` is a plain `str` path
  param (not a `Literal`), so an unregistered value reaches the handler body and produces a `404`
  via registry lookup rather than FastAPI's own `422` — mirroring `UnknownConnectorError`'s
  handling. Same `limit`/`offset` convention as `GET /offers` (`DEFAULT_PAGE_SIZE=50`,
  `MAX_PAGE_SIZE=200`). `source` (ingestion only) resolves a connector name to `source_id` via
  `Source.connector`, using a `_NO_MATCHING_SOURCE_ID = -1` sentinel for an unknown connector —
  same pattern as `GET /offers`' `_NO_ACTIVE_PROFILE_ID`, so an unrecognized filter value returns
  an empty page rather than an unfiltered one or an error. `status` defaults to `"open"`
  (`"resolved"`/`"abandoned"`/`"all"` also accepted — `"abandoned"` added by US49, see below) rather
  than showing every historical row by default. A
  filter param outside the target process's `spec.filterable_params` (e.g. `offer_id` on
  `/failures/ingestion`) is a `400`, not silently ignored — `source`/`offer_id`/`profile_id`
  stay declared on the route signature for OpenAPI/Swagger discoverability, but which ones are
  legal per process is the registry's call, not the route's.
- **`POST /failures/{process}/{failure_id}/retry`**: looks up the row by id (404 if missing),
  dispatches to `RETRY_HANDLERS[row.failure_type]` via `perform_retry`, and returns the
  (possibly now-resolved) row.
- **Frontend**: `frontend/src/api/failures.ts` (typed client, mirrors `api/offers.ts`),
  `frontend/src/hooks/useFailures.ts` (mirrors `useOffers.ts`'s fetch-on-change effect, minus
  the offer list's debounce — a smaller filter set doesn't need it), `frontend/src/lib/failureColumns.tsx`
  (a small column-config registry mirroring `DEAD_LETTER_REGISTRY`: ingestion shows
  source/failure-type/page/occurred-at/error, scoring shows offer/profile/failure-type/occurred-at/error),
  `frontend/src/components/FailuresTable.tsx` (generic table + Prev/Next pagination footer
  copied from `OfferListPage.tsx`'s convention + a Status badge + a Retry button per row +
  "No failures recorded" empty state), `frontend/src/components/FailureDetailDrawer.tsx` (mirrors
  `ScoreDrawer.tsx`'s modal shell — full error text, pretty-printed `raw_payload` when present,
  and an informational origin label: "Scheduler run #N" / "Manual trigger" for ingestion,
  "Offer #N, Profile #N" for scoring — not a navigable link, since this app has no per-run or
  per-offer detail route today), `frontend/src/components/FailureFilters.tsx` (the
  process-conditional filter controls, split out of `FailuresPage.tsx` to keep it under the
  ESLint `complexity: 10` cap), `frontend/src/pages/FailuresPage.tsx` (process selector,
  page-reset-on-filter-change, ties the pieces together). New `/failures` route + nav link in
  `App.tsx`.

#### Shared warm proxy pool (`ProxyPool`)

- **Purpose**: confirmed live 2026-07-30 (BUG49), `ProxyPool.get_proxy` re-scraped and
  re-verified a fresh third-party proxy list from scratch on **every single call** despite the
  class's name — no caching, no pooling. Sitting in the hot path of up to
  `_MAX_PROXY_ATTEMPTS = 3` attempts per URL times up to `page_size * max_pages = 1000` URLs per
  Rocket Jobs/Pracuj.pl run, each individual scrape-and-verify pass costing anywhere from ~5s to
  40s+ (the free-proxy source's real-world hit rate is only ~15%), this meant a single run could
  take hours — and since every connector's own scheduled job is `max_instances=1`, one slow run
  silently blocked every future scheduled tick for that connector indefinitely, with
  `last_run_status` just reading `"running"` forever and no error surfaced anywhere. `ProxyPool`
  now holds a small in-memory pool of already-verified-good proxies (`target_size`, default `5`)
  that `get_proxy` picks from randomly, turning the common case into a near-zero-cost pool draw
  instead of a fresh scrape.
- **`ProxyPool`** (`app/connectors/proxy_pool.py`): `get_proxy(logger) -> str | None` returns a
  random pick from the good pool (`random.Random.choice`, injectable via the constructor's
  `rand` parameter for deterministic tests, mirroring `FingerprintPool`'s own `rand` pattern) —
  never the same proxy every time, spreading request load across several IPs. If the pool is
  empty (cold start, right after process boot, or every member has since been evicted), this
  pays a one-time synchronous `top_up` before returning; this is the one case that still pays
  scrape latency, unavoidable once but never a per-request cost once the pool is warm.
  `report_failure(proxy, logger)` evicts a proxy the moment a caller's actual request against the
  target site fails through it — a no-op if the proxy is already gone (handles the race where two
  callers were handed the same proxy and one already evicted it). `top_up(logger, *,
  max_attempts=None)` scrapes and verifies fresh candidates (`FreeProxy(https=True, ...).get()` —
  `https=True` matters, since `FreeProxy`'s own default silently verifies unproxied) until the
  pool is back at `target_size`, admitting each one that passes; bounded by `max_attempts`
  (defaults to `target_size * 4`) so a fully-down proxy source can't hang it forever, and a cheap
  no-op (zero network calls) when the pool is already full. All pool state (`_good: list[str]`) is
  guarded by a `threading.Lock`, not an `asyncio.Lock` — per BUG47's finding, every call into this
  pool happens via `asyncio.to_thread` from an arbitrary worker thread (BUG42), and once the
  scheduled top-up job below is added, potentially from a second worker thread concurrently with a
  live connector run, so any asyncio-native primitive would bind to whichever loop/thread first
  touched it and raise on the other.
- **One shared instance, not three**: `http.py`, `sitemap_detail.py`, and `pracuj.py` each used to
  construct their own independent `ProxyPool()` — a proxy verified by one connector's traffic was
  never available to another. `get_shared_proxy_pool()` (`lru_cache`-memoized exactly like
  `get_settings()`) replaces all three with one process-lifetime instance, sized from
  `Settings.proxy_pool_target_size`; every module now does `_proxy_pool =
  get_shared_proxy_pool()` instead of `ProxyPool()`. `_get` (`http.py`), `_fetch_detail_html`
  (`sitemap_detail.py`), and `_fetch_html_with_proxy_rotation` (`pracuj.py`) each call
  `_proxy_pool.report_failure(proxy, logger)` right after the existing per-attempt failure log,
  immediately before the loop's `continue`/next iteration — this is the only change to those three
  functions' control flow; the retry loop and its failure contract (`None` on exhaustion,
  `BlockedFetchError` on an exhausted 403/429) are unchanged.
- **`proxy_pool:topup` scheduled job**: mirrors `dlq:retry_403`'s registration shape
  (`PROXY_POOL_TOPUP_JOB_ID = "proxy_pool:topup"`, `register_proxy_pool_topup_job(scheduler, *,
  interval_seconds)` in `app/scheduler/lifecycle.py`, `IntervalTrigger`, `max_instances=1`,
  `coalesce=True`, `replace_existing=True`, registered in `app/main.py`'s `lifespan` alongside the
  other two backlog jobs) with one difference: `run_proxy_pool_topup_job`
  (`app/scheduler/service.py`) is registered as a **plain sync function**, not a coroutine —
  `ProxyPool.top_up` makes genuinely blocking HTTP calls, so `AsyncIOScheduler` must run it on its
  thread-pool executor (the same `run_source_sync` shape ingestion jobs use), not the scheduler's
  own event loop, or it would freeze the whole API for the scrape's duration exactly as BUG42
  found for connectors' own synchronous fetches. Two new `Settings` fields (`app/config.py`):
  `proxy_pool_target_size` (default `5`) and `proxy_pool_topup_interval_seconds` (default `120`).
  This job is what lets the pool self-heal from failure eviction over time without any request
  ever paying the full scrape cost, beyond the one-time cold start.

### Connector fetch date range + auto-fetch toggle

- **Purpose**: the earlier per-source `config_json` mechanics (live `AsyncIOScheduler` job, JSONB
  config, `build_job_id`, `build_source_status` mapper) already had the exact shape needed for
  two more orthogonal per-connector knobs: what `posted_at` window a run accepts (**Fetch
  Range**), and whether a connector's automatic job runs at all (**Auto-Fetch**) — see
  `CONTEXT.md` for the canonical glossary definitions. No migration: both new keys
  (`fetch_range`, `auto_fetch_enabled`) live in the existing freeform `Source.config_json` JSONB
  column alongside `schedule`.
- **`DEFAULT_SOURCE_CONFIGS`** (`app/scheduler/service.py`) gained `"auto_fetch_enabled": True`
  for all three built-in connectors. `_default_fetch_range()` is a separate function (not a
  static dict entry) returning `{"mode": "range", "since": (now - 7 days).isoformat(), "until":
  None}` computed fresh on every call — `DEFAULT_SOURCE_CONFIGS` is a module-level constant
  evaluated once at import time, which would freeze "seed time" at process start rather than
  actual insert time for a source added while the app has been running for days.
  `ensure_sources_exist` merges it in per-insert (`{**config, "fetch_range":
  _default_fetch_range()}`); because the insert is `on_conflict_do_nothing`, this only ever
  applies on a source's first-ever insert — **existing rows from before this story are not
  backfilled** and simply read back `fetch_range={}` / `auto_fetch_enabled` via the fail-open
  defaults below (deliberate: matches `parse_schedule`'s existing fail-soft convention, and
  avoids an unconditional startup `UPDATE` for a one-time migration concern).
- **`set_source_fetch_range`/`set_all_source_fetch_ranges`,
  `set_source_auto_fetch`/`set_all_source_auto_fetch`** (`app/scheduler/service.py`): structurally
  identical to the earlier `set_source_interval`/`set_all_source_intervals` — same
  `resolve_source_by_connector` reuse for `404` mapping, same flush-not-commit (callers commit),
  same reassign-the-whole-dict pattern (`source.config_json = {**source.config_json,
  "fetch_range": ...}`) required by `config_json` being a plain JSONB column with no SQLAlchemy
  `Mutable` wrapper.
- **`build_source_status`** (`app/scheduler/runs.py`) adds `fetch_range=(source.config_json or
  {}).get("fetch_range", {})` and `auto_fetch_enabled=(...).get("auto_fetch_enabled", True)` —
  default `True` on a missing key so a pre-existing row (seeded before this story) fails open to
  "enabled," and default `{}` for `fetch_range` reads back as "no filtering" via
  `resolve_fetch_range` below.
- **`register_jobs`** (`app/scheduler/lifecycle.py`): unchanged except one added line after
  `scheduler.add_job(...)` — `if not (source.config_json or {}).get("auto_fetch_enabled", True):
  scheduler.pause_job(job_id)`. Job registration itself (the `add_job` call and its kwargs) is
  untouched; only the post-registration paused state differs, per the story's own acceptance
  criteria.
- **Four new routes** (`app/api/routes/scheduler.py`), same shape as the earlier interval routes
  (`SessionDep`, `try/except SchedulerLookupError → HTTPException(404, ...)`, commit before
  touching the live scheduler so a mid-request crash never leaves it out of sync with a
  persisted-but-uncommitted config change):
  - `PUT /scheduler/sources/{source}/fetch-range` / `PUT /scheduler/sources/fetch-range` take
    `FetchRangeUpdateRequest { mode: "range" | "all", since: datetime | None, until: datetime |
    None }` (`app/schemas/scheduler.py`). A `@model_validator(mode="after")` requires `since` when
    `mode == "range"`, rejects `since > until`, and forces `since`/`until` to `None` when `mode ==
    "all"` — so `"all"` is always the same canonical shape once persisted, regardless of what a
    caller sent alongside it. No scheduler interaction — `fetch_range` never affects the live
    trigger, only what the next run (automatic or manual) fetches.
  - `PUT /scheduler/sources/{source}/auto-fetch` / `PUT /scheduler/sources/auto-fetch` take
    `AutoFetchUpdateRequest { enabled: bool }` and additionally call
    `scheduler.resume_job`/`scheduler.pause_job(build_job_id(connector))` — takes effect on the
    live scheduler immediately, no restart required, mirroring the earlier live-reschedule behavior.
    `POST /scheduler/run/{source}` (manual trigger) is completely unaffected either way — turning
    Auto-Fetch off pauses the *scheduled* job only, per `docs/adr/0018`.
  - The bulk variants apply one value to every connector with a non-null `connector` in a single
    call (same `set_all_source_*` shape as the earlier bulk interval endpoint) — a deliberate,
    silent overwrite of any prior per-connector customization, matching that precedent exactly.
- **Range filtering — `app/ingestion/runner.py`**, implemented exactly once inside the shared
  `run_paginated_ingestion`, so every connector that calls it gets filtering for free:
  - `resolve_fetch_range(fetch_range: dict | None) -> tuple[datetime | None, datetime | None]`
    returns `(None, None)` — "no filtering" — for `mode: "all"`, a missing key, or any
    malformed/unrecognised shape (the single place both "`all` disables the filter entirely" and
    "malformed config fails open" live, mirroring `triggers.py`'s `parse_schedule`).
  - `_parse_datetime(value)` wraps a module-level `TypeAdapter(datetime | None)` in a
    try/except, so it uniformly accepts a raw ISO string (SOLID.Jobs/JustJoin.it's
    `posted_at` shape), an already-parsed `datetime` (NoFluffJobs' shape, via its own
    `_epoch_ms_to_datetime`), or `None` — never raising.
  - `run_paginated_ingestion` gained `since`/`until: datetime | None = None` keyword params
    (defaulted, so every pre-existing call/test is a byte-for-byte no-op unless a caller opts
    in). Per offer: an unparseable/missing `posted_at` is treated as `datetime.now(UTC)`,
    evaluated fresh per offer (not once per run — a rate-limited paginated run can span a long
    time) — used **only** for this comparison, never written back onto the persisted `Offer`
    (`posted_at` stays whatever the source actually gave, or `None`); see
    `docs/adr/0017-fetch-range-posted-at-fallback-and-sort-order-trust.md` for the full
    reasoning, including why this is strictly better than an unconditional keep-everything
    fallback (it still respects an `until` upper bound, and it can never be mistaken for "old" by
    the early-stop below). An offer outside `[since, until]` is `continue`d — never reaching
    `ingest_offer`, and never touching `consecutive_already_seen` in either direction — so a
    narrow range can never look like "we've caught up" and truncate pagination for an unrelated
    reason. Applies identically regardless of `force_refresh`: `fetch_range` is a deliberate
    user-configured scope, not a pagination-performance shortcut like already-seen dedup — see
    `docs/adr/0018-manual-triggers-respect-fetch-range.md`.
  - **Early-stop-on-old-page**: once every offer on a (non-empty) page has an effective date
    `>= since` is false for none of them — i.e. the whole page is older than the cutoff —
    pagination stops before fetching the next page, since all three connectors' feeds are
    confirmed newest-first today. This assumption is trusted without a runtime guard (documented,
    not defended against a future sort-order change) per `docs/adr/0017`.
- **Three near-identical one-line connector diffs** (`app/connectors/solid_jobs.py`,
  `justjoinit.py`, `nofluffjobs.py`): each `run_x_ingestion` adds `since, until =
  resolve_fetch_range(config.get("fetch_range"))` alongside its existing
  `page_size`/`max_pages`/`already_seen_stop_threshold` config reads, threading `since=since,
  until=until` into its `run_paginated_ingestion(...)` call — consistent with how those other
  per-connector config values are already duplicated rather than centralized. A new connector
  that reuses `run_paginated_ingestion` gets range filtering for free with one
  `DEFAULT_SOURCE_CONFIGS` entry, per the story's own acceptance criteria.
- **Frontend**: `frontend/src/api/scheduler.ts` gained `updateSourceFetchRange`/
  `updateAllSourceFetchRanges`/`updateSourceAutoFetch`/`updateAllSourceAutoFetch` (same
  throw-on-error shape as the existing interval functions).
  `frontend/src/hooks/useFetchRangeSettings.ts` wraps `useSchedulerStatus()` (reused, not
  reimplemented) and tracks one combined `savingByConnector: Record<string, boolean>` map plus a
  shared `error` — a row's range and auto-fetch controls share one saving flag, since the story
  treats "each row saves independently" at the whole-row level, not per-control.
  `frontend/src/components/FetchRangeSection.tsx` renders one row per `KNOWN_SOURCES` entry: an
  auto-fetch checkbox (saves immediately on change), a mode `<select>` ("Date range"/"Fetch
  all"), and — only when mode is "Date range" — since/until `datetime-local` inputs behind their
  own explicit per-row Save button; `toDatetimeLocalValue`/`fromDatetimeLocalValue` do the
  ISO-string ⇄ local-datetime-input conversion at this UI boundary only, exactly like
  `FetchCadenceSection.tsx`'s `secondsToMinutes` converts at its own boundary — the API layer
  only ever deals in ISO strings. Two independent "apply to all" controls (range, and
  auto-fetch on/off) below the per-connector rows, since the two knobs are independently
  toggleable per the acceptance criteria. `SettingsPage.tsx` renders this between
  `FetchCadenceSection` and `NotificationsSection` — grouped there because cadence and
  range/auto-fetch all govern the same automatic scheduled job, sourced from the same `GET
  /scheduler/status` call. (A later addition inserts its own `OfferCleanupSection` between this
  section and `NotificationsSection`, so this is no longer the immediate predecessor of
  Notifications — see below.)
- **Scoring reuses Fetch Range**: this `fetch_range` concept and
  `resolve_fetch_range` function were built for ingestion-time filtering only; a later change (see
  "Batch scoring job" in matching.md) imports `resolve_fetch_range` unchanged into
  `app/scoring/batch.py` so batch scoring stops spending LLM calls on offers the user has already
  excluded from a Source's automatic/manual fetches — no new setting, no schema change, the same
  per-Source `config_json.fetch_range` value now governs both ingestion and scoring selection.

### Connector extensibility + stop/start toggle

- **Purpose**: six more connectors (Bulldogjob through WeWorkRemotely) were queued
  immediately after this effort, each of which would otherwise repeat the same six-file
  hand-edit (a new connector module, `normalize.py`, `registry.py`, `scheduler/service.py`,
  `llm/matcher.py`, five frontend call sites) with nothing catching an omission — the worst
  failure already seen in this project was a connector missing from `LANGCHAIN_SOURCES`:
  ingestion succeeds, the connector's offers just never get scored, silently, forever. This
  does two things: (1) extracts the three existing connectors' shared scaffolding into a
  `JobBoardConnector` Template Method base class, and (2) makes `CONNECTOR_REGISTRY` the single
  place a connector is declared to exist, with everything else (scheduler seeding, matching
  eligibility, every frontend connector list) deriving from it. It also adds a
  Connector Stop/Start toggle (`connector_enabled`), independent of the earlier Auto-Fetch toggle
  — see `CONTEXT.md` for both glossary entries.

- **`JobBoardConnector` (`app/connectors/base.py`)** — see
  `docs/adr/0021-jobboardconnector-template-method-boundary.md` for the full rationale. Three
  tiers, not two:
  - **Abstract** (`default_url`, `build_params`, `next_cursor`, `map_offer`) — no sensible
    default exists; every subclass must supply these. `map_offer`'s body is each connector's
    old free-standing `map_x_offer` function, moved verbatim — no mapping/normalization logic
    changed.
  - **Hooks** (sensible default, override only when an API needs a twist): `build_url(config)`
    defaults to `config.get("endpoint_url", self.default_url())` — SOLID.Jobs overrides it to
    call the free function `build_offer_url(config)` instead (division-templated, no
    `endpoint_url` override, unchanged from before this story). `envelope_key` is a plain class
    attribute (`"jobs"`/`"data"`/`"postings"`); `extract_offers(payload)` defaults to
    `extract_envelope_list(payload, self.envelope_key)` — NoFluffJobs overrides it fully to pass
    `allow_bare_list=False`. `build_headers(config)` defaults to `{}` — SOLID.Jobs overrides it
    to return the static `{"X-Api-Version": "1.0"}` header. `runner_kwargs(config)` defaults to
    `{}` and is merged **on top of** the generically-derived `page_size`/`max_pages`/
    `already_seen_stop_threshold` inside `run()` — JustJoin.it returns
    `{"rate_limit_delay": ...}` (an added key), NoFluffJobs returns
    `{"max_pages": 1, "already_seen_stop_threshold": 1}` (a hardcoded override config can't
    undo, preserving its "single fetch, no pagination loop" behavior from ADR 0009).
  - **Fixed, never overridden**: `fetch_page(config, cursor, page_size)` (the
    fetch → extract → log-on-failure → next-cursor step) and `run(session, source,
    force_refresh=False)` (config-read → dispatch-to-`run_paginated_ingestion`). `fetch_page`
    takes `config` as an explicit parameter — deliberately, rather than reading a `self.config`
    set once per `run()` call — because `CONNECTOR_REGISTRY` holds one long-lived connector
    instance per connector (constructed once at import time, see below), and a manual trigger
    can run concurrently with an in-flight scheduled tick for the same connector; storing
    `config` as shared mutable instance state would race between the two. `run()` instead
    builds a fresh closure over its own local `config` on every call — the same safety the old
    per-module closures already had, just preserved through the refactor.
  - Each of the three connectors is now a small subclass (`SolidJobsConnector`,
    `JustJoinItConnector`, `NoFluffJobsConnector`) implementing only the genuinely-varying
    pieces; the free-standing `fetch_json` wrappers, `extract_offer_list` helpers, and
    per-module `run_x_ingestion` functions are deleted, not kept alongside the new classes.
    `SolidJobsConnector.__init__(self, *, campaign: str)` stores `campaign` on the instance
    (previously threaded through `run_solid_jobs_ingestion`'s own `campaign` kwarg per call).

- **`ConnectorSpec` / `CONNECTOR_REGISTRY` (`app/ingestion/registry.py`)** — see
  `docs/adr/0022-connector-registry-is-the-single-source-of-truth.md`. `CONNECTOR_REGISTRY:
  dict[str, ConnectorSpec]` replaces the old `dict[str, Connector]` — `ConnectorSpec(name,
  label, dispatch)` adds a human-readable `label` (previously only known to the frontend's
  `KNOWN_SOURCES` constant) alongside the dispatch callable. Each entry's `dispatch` is a bound
  `.run` method on a constructed connector instance — `SolidJobsConnector(campaign=
  get_settings().solid_jobs_campaign).run`, constructed once at module import time. This is
  safe: `get_settings()` is `@lru_cache`d, so binding at import time reads the same value a
  per-call `get_settings()` lookup would have. `dispatch_ingestion` and
  `resolve_source_by_connector` read `.dispatch` off the spec instead of calling the dict value
  directly. Everything else now derives from `CONNECTOR_REGISTRY`:
  - `ensure_sources_exist` (`app/scheduler/service.py`) iterates `CONNECTOR_REGISTRY` instead of
    a hand-maintained `DEFAULT_SOURCE_CONFIGS` dict, seeding every key with one shared
    `_default_config_template()` (schedule, `auto_fetch_enabled`, `connector_enabled` — all
    defaulting to sensible values) plus the existing `_default_fetch_range()`.
  - `LANGCHAIN_SOURCES` (`app/llm/matcher.py`) is now `frozenset(CONNECTOR_REGISTRY.keys())`
    instead of a hand-listed set. This bakes in "every registered connector is LangChain-scored"
    as structural — which is not a new assumption: an earlier effort already retired the
    originally-planned second scoring engine (`sjctl evaluate`) and made LangChain cover all
    three sources (see "SOLID.Jobs Matcher verification" in matching.md). This just
    removes the last traces of that abandoned plan: the dead `"sjctl"` option on the
    `MatchEngine` schema literal, and the stale "`sjctl evaluate` wrapper (SOLID.Jobs)" wording
    in CLAUDE.md's Phase 3 overview.
  - `GET /connectors` (new `app/api/routes/connectors.py`) returns `[{id, label}, ...]` built
    from `CONNECTOR_REGISTRY.values()` — a separate route module from `scheduler.py` since it
    doesn't touch `Source` rows or APScheduler at all, just the registry.

- **Connector Stop/Start (`connector_enabled`)** — the flag that actually stops a connector,
  filling the gap the Auto-Fetch glossary entry explicitly called out ("doesn't disable the
  connector or block manual runs"). Enforced in exactly one place: `run_with_lifecycle`
  (`app/ingestion/lifecycle.py`) checks `source.config_json.connector_enabled` immediately after
  resolving the source — before `before_dispatch` runs, so a rejected manual trigger creates no
  `SchedulerRun` row — and raises `ConnectorDisabledError` if it's `False`. This is a standalone
  exception, not a `SchedulerLookupError` subclass (that family means "this connector doesn't
  exist"; this means "it exists but is stopped"), so both `POST /scheduler/run/{source}`
  (`app/api/routes/scheduler.py`) and `POST /ingest/{source}` (`app/api/routes/ingestion.py`,
  which funnels through the same `run_with_lifecycle` via `trigger_ingest`) get their own
  `except ConnectorDisabledError: raise HTTPException(409, ...)` clause distinct from the
  existing `except SchedulerLookupError: raise HTTPException(404, ...)`. `connector_enabled` and
  `auto_fetch_enabled` are combined with AND in exactly one shared function,
  `connector_should_auto_run(config)` (`app/scheduler/lifecycle.py`), used by `register_jobs`'s
  startup pause decision and by all four enabled/auto-fetch routes (single and bulk) — the same
  "always register, conditionally pause" pattern established earlier for Auto-Fetch, just gated
  on both flags instead of one. This also fixed a latent asymmetry: the auto-fetch routes previously
  paused/resumed based solely on `payload.enabled`, which would have silently resumed a
  `connector_enabled=false` connector's job the moment auto-fetch was turned back on; they now
  call `connector_should_auto_run` on the post-update config instead. Toggling
  `connector_enabled` never touches `Offer` rows — no query anywhere filters offers by their
  source's `connector_enabled`.

- **Frontend** — `frontend/src/api/connectors.ts` (new) wraps `GET /connectors`;
  `frontend/src/hooks/useKnownSources.ts` (new) fetches it once per mount, silently swallowing a
  rejection into an empty list (mirroring `useSchedulerStatus`'s own convention) — this replaces
  `frontend/src/constants.ts`'s deleted `KNOWN_SOURCES` array everywhere it was used
  (`OfferFilters.tsx`, `FailureFilters.tsx`, `OfferListPage.tsx`, and the new Settings components
  below). `frontend/src/hooks/useConnectorSettings.ts` (new) consolidates the former
  `useFetchCadence`/`useFetchRangeSettings` hooks into one, adding `saveEnabled`/`saveEnabledAll`
  alongside the existing interval/range/auto-fetch methods, all sharing one
  `savingByConnector: Record<string, boolean>` map (the existing precedent — range and
  auto-fetch already shared one map before this story). `frontend/src/lib/
  connectorSettingsDraft.ts` (new) holds the shared minutes/datetime-local draft-conversion
  helpers (`secondsToMinutes`, `toDatetimeLocalValue`/`fromDatetimeLocalValue`,
  `draftFromFetchRange`, `buildRequest`) previously duplicated between
  `FetchCadenceSection.tsx` and `FetchRangeSection.tsx`. `ConnectorSettingsCard.tsx` (new) renders
  one connector's cadence, fetch range + auto-fetch, and stop/start controls together in a single
  card — replacing the old one-row-per-connector-per-section layout, which duplicated the
  connector's name across two separate sections. `ConnectorSettingsSection.tsx` (new) renders an
  "apply to all" bar (four independent controls — cadence, range, auto-fetch, stop/start) above a
  vertical stack of `ConnectorSettingsCard`s, one per `useKnownSources()` entry — a vertical card
  stack rather than a widening row-based table is what keeps the page legible as more connectors
  are registered (six more were added later). **Superseded later**: as the registry grew past six
  connectors, the vertical stack was replaced by a tab strip showing exactly one
  `ConnectorSettingsCard` at a time — see "Per-connector offer counts + connector settings
  sub-pages" below. `FetchCadenceSection.tsx`, `FetchRangeSection.tsx`,
  `useFetchCadence.ts`, and `useFetchRangeSettings.ts` (and their test files) are deleted, not
  kept alongside the new components.

- **Adding a connector, end to end**: (1) write `app/connectors/<name>.py` subclassing
  `JobBoardConnector`, implementing the 4 abstract methods and overriding a hook only if the
  API genuinely needs it; (2) add one `ConnectorSpec` entry to `CONNECTOR_REGISTRY`
  (`app/ingestion/registry.py`); (3) add a `normalize.py` vocabulary mapping only if the new
  API introduces raw values not already covered. Nothing else to touch — scheduler seeding
  (`ensure_sources_exist`), matching eligibility (`LANGCHAIN_SOURCES`), and every frontend list
  (`useKnownSources`) pick it up automatically.

### Connector architecture cleanup

A design audit of all 9 connectors against ADR 0021/0022 found the two ADRs'
promises had eroded in practice — Bulldogjob and Rocket Jobs turned out to be ~90% duplicated
code, not two independent connectors, and a seed-config-override ladder had regrown in
`scheduler/service.py` outside the registry, the exact anti-pattern ADR 0022 was written to
eliminate. This cleanup is structural only: no connector's live fetch output, dedup, or
normalization behavior changed.

- **`app/connectors/sitemap_detail.py`'s `SitemapDetailPageConnector`** is a new intermediate
  base between `JobBoardConnector` and `BulldogjobConnector`/`RocketJobsConnector`
  (`JobBoardConnector` → `SitemapDetailPageConnector` → `{Bulldogjob,RocketJobs}Connector`), the
  same subclass-of-subclass shape `ADR 0021` already established for `JobBoardConnector` itself.
  It captures the sitemap-cursor-persisted, rate-limited, per-URL-detail-fetch `run()` shape both
  connectors previously each carried their own copy of: reading `page_size`/`max_pages`/
  `already_seen_stop_threshold`/`rate_limit_delay_seconds` from config, resolving/persisting
  `sitemap_cursor` via `resolve_sitemap_cursor`/`next_sitemap_cursor` (fixed after a bug where the
  cursor wasn't persisted, causing repeated re-fetches of page 1), and the
  rate-limited per-URL `fetch_page` closure. Each subclass now implements only 3 hooks:
  `sitemap_url()` (replaces `default_url`), `fetch_sitemap_urls(config)`, and
  `extract_detail_json(html, *, url)` (the `extract_next_data`/`extract_job_posting_json_ld`
  swap point) — plus `follow_redirects_on_detail_fetch()`, defaulting to `False`, which Rocket
  Jobs overrides to `True` (its one real behavioral difference from Bulldogjob, a 308-redirect
  quirk confirmed live 2026-07-14). `map_offer` and every connector-specific parsing helper
  (`_join_locations`/`_pick_salary` for Bulldogjob, `_find_job_posting`/`_extract_location`/
  `_external_id_from_url` for Rocket Jobs) stay in their own connector modules, untouched.

- **`app/connectors/http.py`'s four fetch functions** (`fetch_json`, `fetch_xml`,
  `fetch_gzip_xml`, `fetch_text`) now share one internal `_get()` helper for the transport-level
  `try/except httpx.HTTPError` — issuing the GET with the merged `User-Agent` header and
  `raise_for_status()`, logging and returning `None` on failure. `_get()` takes `error_noun`
  (`"offers"` for `fetch_json`/`fetch_xml`, `"sitemap"` for `fetch_gzip_xml`/`fetch_text`) and
  `log_params` (`True`/`False` in the same split) so each function's existing log message
  wording stays byte-identical — this was a behavior-preserving refactor verified by running
  `tests/test_http.py` unmodified.

- **`ConnectorSpec.seed_config_overrides: dict[str, Any]`** (new field, `field(default_factory=dict)`
  on the still-frozen dataclass) replaces `scheduler/service.py`'s `_connector_config_overrides`
  branching function. Pracuj's, RemoteOK's, and Remotive's per-connector seed defaults
  now live directly on their `CONNECTOR_REGISTRY` entries; `ensure_sources_exist` reads
  `CONNECTOR_REGISTRY[connector].seed_config_overrides` instead of branching on connector identity
  — the override now travels with the connector's own registry entry rather than living in a
  second file that has to be kept in sync with it.

- **`registry.py` no longer restates each connector's display label as an independent string
  literal.** Every `JobBoardConnector`-backed entry's `label` is now sourced from
  `<instance>.name` (e.g. `label=_bulldogjob.name`), reusing the same connector instance already
  constructed for `dispatch=<instance>.run` — the same "derive, don't restate" pattern
  `LANGCHAIN_SOURCES = frozenset(CONNECTOR_REGISTRY.keys())` (`app/llm/matcher.py`) established.
  We Work Remotely (which implements the `Connector` Protocol directly, not
  `JobBoardConnector`) keeps an explicit label string, but now sourced from a new
  `we_work_remotely.NAME` module constant rather than a second inline literal.
  `tests/test_registry_label_sync.py` guards this: it asserts `spec.label ==
  spec.dispatch.__self__.name` for every class-backed entry, so a future edit that desyncs them
  fails loudly instead of silently drifting.

- **`sitemap.py`'s `parse_sitemap_locs` is now public** (renamed from `_parse_sitemap_locs`) —
  it's imported across module boundaries (`bulldogjob.py`, `rocket_jobs.py`), so the leading
  underscore was misleading about its actual visibility contract.

See `docs/adr/0021-jobboardconnector-template-method-boundary.md` and
`docs/adr/0022-connector-registry-is-the-single-source-of-truth.md` for the follow-up notes
recording where this story's extraction fits against each ADR's original decision.

### Connector fetch scope: all offers vs filtered by hard skills

Bulldogjob and Pracuj.pl issue one live fetch per matched offer (a sitemap-enumerate-then-detail
walk and a Playwright-driven listing-then-detail walk, respectively), so a candidate whose active
Profile only wants a handful of skills still pays the anti-scraping exposure of the whole
catalog. This adds a third `config_json`-driven per-connector knob, **Fetch Scope**,
structurally identical to Fetch Range/Auto-Fetch but scoped to only the connectors with
a confirmed live keyword-filter mechanism — SOLID.Jobs, Bulldogjob, Pracuj.pl. The other 6
connectors fetch their whole catalog in one or a handful of calls regardless of match count, so
filtering them would reduce only what gets stored, not request volume, and they get no config
key, no UI control, no registry flag.

- **`ConnectorSpec.supports_fetch_scope: bool = False`** (new field, `app/ingestion/registry.py`)
  is `True` on exactly the `SOLID_JOBS`, `BULLDOGJOB`, `PRACUJ` entries —
  `tests/test_registry_fetch_scope.py` pins this set so a future connector addition can't
  silently flip it without a failing test forcing review.

- **`app/ingestion/fetch_scope.py` (new module)** owns resolution as a pure, session-free
  function plus a thin async DB-touching wrapper, the same two-layer split
  `app/ingestion/runner.py`'s `resolve_fetch_range` established: `resolve_fetch_scope_mode(dict |
  None) -> "all" | "filtered"` fails open to `"all"` for a missing key or malformed shape (same
  convention as `resolve_fetch_range`); `resolve_fetch_scope(mode, profile) ->
  FetchScopeResolution` returns either `terms=[]` (mode is `"all"`) or one term per starred
  (`Skill.hard`) skill on the profile, OR-ed together — no active profile, or an active profile
  with zero starred skills, produces a non-`None` `blocked_reason` instead of silently falling
  back to `"all"`; `resolve_fetch_scope_terms(session, config)` is the async wrapper every
  connector's `run()` calls, reading the active profile via the existing
  `app.db.profile_repo.get_active_profile`.

- **`hard_skill_names(profile: Profile) -> list[str]`** (new, `app/schemas/profile.py`) is a pure
  extraction of what was previously `app/llm/matcher.py`'s private `_hard_skill_names` — the
  matcher's score-capping logic (see "Hard skill miss cap" in matching.md) now imports and calls this shared function instead of
  keeping its own copy, since this story needed the same "which skills are starred" read from a
  module `fetch_scope.py` can import without a circular dependency (`matcher.py` imports
  `CONNECTOR_REGISTRY`, which imports every connector, which imports `fetch_scope.py`).

- **`JobBoardConnector` (`app/connectors/base.py`) gains two hooks**: `supports_fetch_scope()
  -> bool` (default `False`) and `apply_fetch_scope_term(config, term) -> dict` (default
  `NotImplementedError`). Its fixed `run()` calls `resolve_fetch_scope_terms` once per run when
  `supports_fetch_scope()` is `True`; a non-`None` `blocked_reason` returns
  `IngestionResult(ok=False, ..., error_message=blocked_reason)` immediately, and a `"filtered"`
  resolution calls `run_paginated_ingestion` once per hard-skill term (via
  `apply_fetch_scope_term`-transformed config), accumulating `fetched`/`created` across passes
  and stopping at the first term whose result is not `ok`. **No new Dead Letter Queue code**: a
  blocked or failed filtered run reaches the exact same `IngestionResult(ok=False, ...)` →
  `record_run_fetch_failure` → `FailureType.RUN_FETCH_FAILED` pathway already wired for
  every "run a connector" caller — retried via the existing `POST
  /failures/ingestion/{id}/retry` with zero new retry-handler code.

- **`SolidJobsConnector`** (`app/connectors/solid_jobs.py`) implements
  `apply_fetch_scope_term` by injecting a single-element `terms` list into `config` —
  `build_offer_params`'s `search.searchTerm` param already existed and worked, just was never
  populated from anywhere upstream before this story.

- **`SitemapDetailPageConnector`** (`app/connectors/sitemap_detail.py`, shared by
  `BulldogjobConnector`) gains a `fetch_filtered_sitemap_urls(config, term) -> list[str] | None`
  hook and its own `supports_fetch_scope()`-gated branch in `run()`, mirroring
  `JobBoardConnector`'s shape but walking one filtered-listing enumeration per term instead of
  one shared sitemap. Its existing per-run body was extracted into `_run_over_urls(...,
  persist_cursor: bool = True)` first (a pure, behavior-preserving refactor) so the filtered path
  can call it with `persist_cursor=False` — a filtered run enumerates a small, fresh, per-term
  listing each time rather than the full stable catalog, so the `sitemap_cursor`
  resume-where-you-left-off concern doesn't apply and the unfiltered path's cursor is left
  untouched by a filtered run. `BulldogjobConnector.fetch_filtered_sitemap_urls` is implemented
  per a dedicated live-research spike (`docs/adr/0027`): `bulldogjob.com/companies/jobs/s/skills,
  <Term>` embeds the same `__NEXT_DATA__` shape as every other page, with job summaries (not full
  detail records) under `props.pageProps.jobs`; pagination is client-side only (`?page=`/
  `?perPage=` are silently ignored), so a plain-request filtered fetch is capped at one page (up
  to 50 offers) per hard-skill term, a deliberate scope reduction consistent with filtered mode's
  own "fewer requests, reduced recall" premise.

- **`PracujConnector`** (`app/connectors/pracuj.py`) resolves fetch scope immediately after
  reading `config` — before launching Playwright/Chromium, a cheap short-circuit for a run that's
  going to be blocked anyway. A non-empty `filtered_terms` list loops `_collect_offers` once per
  term (`category_filter=term, start_page=1` always — filtered runs don't participate in the
  `listing_page_cursor` resumption, the same deliberate scope reduction as Bulldogjob's), OR-ing
  `enumeration_ok`/`mid_run_failure` conservatively across terms (the whole run is
  `enumeration_ok=False` only if every term's first page failed) and concatenating each term's
  offers before persisting — cross-term duplicate detail records are harmless, since
  `ingest_offer`'s canonical-URL dedup already collapses them. `listing_page_cursor` is only
  updated on the unfiltered path.

- **Scheduler plumbing mirrors Fetch Range/Auto-Fetch exactly, with one deliberate deviation**:
  `set_source_fetch_scope` (`app/scheduler/service.py`) gates only `mode: "filtered"` against
  `CONNECTOR_REGISTRY[connector].supports_fetch_scope` (raising `FetchScopeNotSupportedError` →
  HTTP 400), since `mode: "all"` is a no-op equal to the default and has no behavioral
  consequence on an unsupported connector — there is **no `set_all_source_fetch_scope`/bulk
  route**, since "apply filtered mode to all 9 connectors" has no sensible meaning when only 3
  support it. `PUT /scheduler/sources/{source}/fetch-scope` (`app/api/routes/scheduler.py`)
  follows the same try/except → 400/404 → commit → `build_source_status` shape as the fetch-range
  route. `build_source_status` (`app/scheduler/runs.py`) reads back `fetch_scope` fail-open to
  `{"mode": "all"}`, and `_default_config_template()` seeds every connector (including the 6
  unsupported ones) with that same default — no migration, no backfill, matching Fetch Range's
  own precedent.

