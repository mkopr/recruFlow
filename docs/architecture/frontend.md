# Offer list & frontend

[Architecture index](../../ARCHITECTURE.md)

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

### Offer applied/hide/notes fields (P3US31)

- **Purpose**: the first story to give `Offer` fields that are purely user-owned — `applied`,
  `hide`, `notes` — rather than connector-sourced (title, company, salary, ...) or computed
  (`score_percent`). It's consequently the first partial-update write path anywhere in the API:
  every prior write endpoint (`PUT /profile`) is a full upsert; `PATCH /offers/{offer_id}` updates
  only the fields present in the request body.
- **Schema/DB**: one Alembic migration (`bef7908f5330_offer_applied_hide_notes`) adds
  `applied BOOLEAN NOT NULL DEFAULT false`, `hide BOOLEAN NOT NULL DEFAULT false`,
  `notes TEXT NULL` to `offers`. `notes` has no length cap, matching the existing unbounded
  `description` column.
- **`PATCH /offers/{offer_id}`** (`app/api/routes/offers.py`): takes `OfferEdit`
  (`app/schemas/offer.py` — `applied: bool | None = None`, `hide: bool | None = None`,
  `notes: str | None = None`, all optional) and returns the updated `OfferSummary`. The handler
  applies `payload.model_dump(exclude_unset=True)` field-by-field via `setattr` — `exclude_unset`
  (not `exclude_none`) is what makes "only fields present in the request body change" work
  correctly, including the case where a client explicitly sends `{"notes": null}` to clear notes:
  `exclude_unset` only drops fields never present in the request at all, not fields explicitly set
  to `None`. Unknown `offer_id` returns `404 {"detail": "offer {id} not found"}`, mirroring
  `GET /offers/{offer_id}`'s existing convention. The response includes the offer's real, current
  `score_percent` (via the same latest-score-for-active-profile query `GET /offers/{offer_id}/score`
  uses) rather than always `None` — otherwise toggling Applied/Hide on a scored row would erase its
  visible score badge in the frontend's locally-patched state, since the frontend never re-fetches
  the list after a `PATCH`.
- **`GET /offers` gains `applied`/`show_hidden`**: `applied: bool | None` is tri-state, same
  shape as the existing `remote` filter. `show_hidden: bool = False` is the one filter in this
  endpoint that behaves differently when *omitted* versus every other optional filter: omitting
  `remote`/`seniority`/`min_score`/etc. means "no constraint," but omitting `show_hidden` (or
  passing `false`) means hidden offers are actively excluded (`OfferModel.hide.is_(False)`) —
  there is no way to request "no opinion on hidden-ness" the way there is for the other filters.
  `show_hidden=true` removes that clause entirely, returning hidden and non-hidden offers together,
  still subject to every other active filter. Both new clauses are added before the `total = ...`
  count query, same as every existing filter, so `total` stays consistent with the returned page.
- **Re-ingestion never resets these fields — for free**: `app/ingestion/persist.py`'s
  `persist_offer` already inserts via `on_conflict_do_nothing(index_elements=[OfferModel.dedup_hash])`
  — on a duplicate `dedup_hash`, the conflict clause does nothing at all, not even touching columns
  the ingestion payload doesn't reference. Since `applied`/`hide`/`notes` are never part of the
  ingestion `Offer` schema, this acceptance criterion required zero code changes in the ingestion
  path; the three new columns only needed DB-level `server_default`s so a genuinely new row still
  gets sensible defaults.
- **Frontend**: `frontend/src/hooks/useOffers.ts` gains `updateOffer(updated: OfferSummary): void`
  — patches a single row into local state without a full list re-fetch (mirroring the "ride along
  on `OfferSummary`, no extra per-row request" pattern BUG26 established for `score_percent`). When
  `showHidden` is false and the updated offer's `hide` is true, `updateOffer` removes it from local
  state instead of replacing it in place — this is what makes hiding a row disappear immediately
  without a manual refresh. **Known, accepted trade-off**: `total` is deliberately left unchanged
  by `updateOffer` (no re-fetch), so the displayed count can drift by one after a hide/unhide until
  the next real fetch; this is intentional, not a bug. `frontend/src/components/OfferTable.tsx`
  calls `patchOffer` directly (mirroring how it already calls `fetchOfferScore` directly via
  `useOfferScoreDetail` rather than delegating network calls up to the parent) and invokes the new
  `onOfferPatched` prop with the response. `frontend/src/components/NotesEditor.tsx` is a new
  overlay built on `ScoreDrawer.tsx`'s exact scaffold (fixed backdrop that closes on click,
  `role="dialog" aria-modal="true"` card panel, `Escape`-key `window` listener) with an editable
  textarea and Save/Cancel instead of read-only content. `frontend/src/components/OfferFilters.tsx`'s
  "Show hidden offers" checkbox is wrapped in the same `.input`-styled, `flex-col` label shape as
  every other filter (a caption line above a bordered control) rather than a bare inline checkbox
  — the filter row uses `items-end` alignment, so a differently-shaped control breaks the row's
  visual alignment against the select/input fields next to it.

### Offer new-offer highlight until opened (P3US35)

- **Purpose**: closes the last gap in "make the best-matching offers impossible to miss"
  (P3US28 added a one-shot sound alert on new high scores, P3US29 made its threshold
  user-configurable via `scoreAlertPrefs.minScorePercent`) — missing the sound (stepped away,
  muted, tab not focused) previously meant a great match could sit unnoticed in the list forever.
  This story adds a fourth user-owned `Offer` field, `link_opened_at`, following P3US31's exact
  migration → model → schema → endpoint → frontend pattern.
- **Schema/DB**: one Alembic migration (`95644bfde2a0_offer_link_opened_at`, mirroring
  `bef7908f5330_offer_applied_hide_notes`'s shape) adds `link_opened_at TIMESTAMPTZ NULL` to
  `offers`, defaulting to null. Included in `OfferSummary`/`OfferDetail` (`app/schemas/offer.py`)
  alongside `applied`/`hide`/`notes`.
- **`PATCH /offers/{offer_id}` request-flag-to-server-timestamp**: `OfferEdit` gains
  `link_opened: bool | None = None` — deliberately a behavioral flag in the request, not a direct
  passthrough of `link_opened_at`, so the client can never set an arbitrary timestamp; only the
  server decides `now()`. This means the field can't go through the handler's generic
  `for field, value in payload.model_dump(exclude_unset=True).items(): setattr(offer, field,
  value)` loop (there is no `Offer.link_opened` ORM attribute) — `patch_offer` pops `link_opened`
  out of the dumped payload before that loop runs, then applies it separately:
  `if link_opened and offer.link_opened_at is None: offer.link_opened_at = datetime.now(UTC)`.
  Checking `is None` (not just running `datetime.now(UTC)` unconditionally) is the whole
  idempotency guarantee — a repeat `{"link_opened": true}` call is a no-op on the timestamp
  because the condition is only ever true once per offer. `{"link_opened": false}` is accepted by
  the schema but intentionally has no effect; there is no "un-open" acceptance criterion.
- **Highlight derivation is computed, never stored**: a row is eligible for the highlight when
  `score_percent != null && score_percent >= scoreAlertPrefs.minScorePercent && link_opened_at ==
  null && canonical_url != null` (`isHighlighted` in `frontend/src/components/OfferTable.tsx`),
  recomputed from `GET /offers` data on every load — there is no `is_highlighted` column, no
  "mark as seen" endpoint, and no per-session cache. This is deliberate, not an oversight: it's
  the only way lowering `minScorePercent` in Settings can retroactively highlight
  previously-below-bar, not-yet-opened offers on the very next load with no rescoring or backend
  change. See `docs/adr/0019-offer-highlight-is-derived-not-stored.md` and the `CONTEXT.md`
  **Unopened Match Highlight** glossary entry.
- **Reuses `.card-accent` verbatim** (`frontend/src/index.css`, unmodified) — the same
  accent-tinted `color-mix` border/background treatment already established for other
  accent-styled cards, applied at the `<tr>` level, so the highlight reads as part of the
  existing dark theme rather than a new bolted-on banner color.
- **Click-to-open wiring** (`OfferTable.tsx`'s title `<a>`, the same anchor P3US26 already
  rendered when `canonical_url` is set): `onClick={() => handleOpenLink(offer)}` does not call
  `preventDefault`, so the existing `target="_blank"` navigation is untouched and never blocked
  or delayed. `handleOpenLink` (a) no-ops if `link_opened_at` is already set (avoids a redundant
  PATCH on repeat clicks), (b) optimistically calls `onOfferPatched({ ...offer, link_opened_at:
  new Date().toISOString() })` synchronously so the row's highlight visibly clears the instant
  it's clicked, without waiting on the network, then (c) fires `void patchOffer(offer.id,
  { link_opened: true }).catch(() => {})` — fire-and-forget, with a bare `.catch` added (beyond
  the original story plan) specifically to swallow the rejection `patchOffer` throws on a failed
  request; without it, an offline/erroring PATCH would surface as an unhandled promise rejection
  (noisy in the browser console, and can fail a Vitest run outright via other, unrelated tests).
  No retry or error toast is added — the optimistic local state is treated as sufficient for this
  session, matching the existing "no client-side snapshot" acceptance criterion's spirit.
- **Reingestion protection is free, for the same reason P3US31's fields got it**: `link_opened_at`
  is never part of the ingestion `Offer` schema, so `persist_offer`'s
  `on_conflict_do_nothing(index_elements=[OfferModel.dedup_hash])` already leaves it untouched on
  a duplicate `dedup_hash` — no ingestion-path code changes were needed, only a regression test
  (`test_reingest_does_not_reset_link_opened_at`).

### Per-connector offer counts + connector settings sub-pages (P3US45)

- **Purpose**: the main page's connector cards and Settings' connector configuration both scale
  poorly once a registry grows past a handful of entries — the main page gives no sense of how
  many offers each connector has actually produced or how much of the active profile's backlog
  is scored, and Settings' vertical `ConnectorSettingsCard` stack (P3US37) keeps growing taller
  with every new connector (six real connectors already; P3US42-44 queue three more). This story
  adds counts to the former and a tab/sub-page navigation to the latter, without touching either
  component's actual content.

- **`ConnectorOption` (`app/schemas/connectors.py`) gains three required `int` fields**:
  `offer_count`, `scored_count`, `unscored_count`. `GET /connectors`
  (`app/api/routes/connectors.py`) computes all three in one grouped query — `SELECT
  Source.connector, COUNT(Offer.id), COUNT(CASE WHEN Offer.id IN (scored_offer_ids) THEN
  Offer.id END) ... GROUP BY Source.connector` — then merges the per-connector counts with
  `CONNECTOR_REGISTRY` so every registered connector appears with `(0, 0, 0)` even if it has no
  `Source`/`Offer` rows yet (a brand-new connector's first day, or a monkeypatched test double).
  `offer_count` is a **raw inventory count**: every `Offer` row for that connector, unfiltered by
  `hide`, `applied`, or fetch-range — deliberately not the same "how many offers can I currently
  see" count `GET /offers`'s `total` returns. `scored_count`/`unscored_count` are keyed on whether
  each offer has a `MatchScore` row for the **active Profile only** — a `MatchScore` against a
  different (inactive) profile still counts as unscored. Mirrors, but does not share,
  `app/api/routes/offers.py`'s `_NO_ACTIVE_PROFILE_ID = -1` sentinel convention: when there is no
  active profile, the "scored" subquery is scoped to an id no `MatchScore.profile_id` can ever
  hold, so every connector reports `scored_count == 0` without branching the query shape. This is
  a second, independent per-file sentinel (this codebase's established convention, not a shared
  cross-module constant).

- **`ScoringStatusResponse` (`app/schemas/scoring.py`) gains `total_offers: int`** — a raw,
  unfiltered `COUNT(*)` over the whole `Offer` table (`count_total_offers`, `app/scoring/
  batch.py`, mirroring `count_unscored_backlog`'s existing on-demand-count style), computed
  alongside the rest of `GET /scoring/status`'s fields. Unlike `unscored_backlog` (already
  profile/connector/fetch-range-scoped), `total_offers` answers "how many offers exist at all,"
  independent of any profile — the database-wide denominator the frontend's `scored / total`
  numbers need.

- **Frontend counts wiring**: `useKnownSources()` (`frontend/src/hooks/useKnownSources.ts`) now
  returns a `refetch` alongside `sources` — every existing consumer that only destructured
  `{ sources }` (`OfferFilters`, `FailureFilters`, `ConnectorSettingsSection`) is unaffected;
  `OfferListPage` is the only caller that also uses `refetch`, calling it from both existing
  refresh triggers (`handleIngested`, and the `scoringStatus.finished_at` effect that already
  re-pulls the offer table after a background scoring run) so a connector's counts update live,
  the same "no manual refresh" guarantee the rest of the main page already gives. Both new counts
  are rendered as bare `scored / total` numbers, deliberately without any words — `SourceFetchCard`
  adds a second line, `"{scoredCount} / {offerCount}"`, below its existing label/last-fetched
  status line; `ScoreNowButton`'s `defaultSubtitle` becomes `"{total_offers - unscored_backlog} /
  {total_offers}"`, replacing its previous "N offers pending / All offers scored" wording
  entirely (a deliberate minimal-UI call — this project's other status text stays wordy, but
  scoring counts read better as bare numbers here).

- **Settings connector sub-pages**: `ConnectorSettingsSection.tsx`'s vertical
  `ConnectorSettingsCard` stack (P3US37) is replaced by a `role="tablist"`/`role="tab"` strip
  sourced directly from `useKnownSources()`, rendering exactly one active connector's
  `ConnectorSettingsCard` below it — the "Apply to all" bar above the tab strip is untouched and
  stays visible and functional regardless of which tab is selected (it was already
  connector-agnostic, calling the same `*All` bulk endpoints). The active tab is plain
  component state, not derived from routing, so adding a new `CONNECTOR_REGISTRY` entry makes it
  appear as a new tab with zero changes to `ConnectorSettingsSection.tsx` itself — the same
  zero-frontend-change extensibility P3US37 established for the old card stack. The tab strip's
  container reuses the same `flex flex-wrap` pattern the "Apply to all" bar already uses, so it
  wraps onto additional rows rather than overflowing at both the real 6-connector count and a
  9-10-connector fixture-mocked stretch test, at both mobile and desktop widths (manually
  confirmed: 6 tabs sit on one row at 1440px width and wrap to three rows at 375px width, with no
  horizontal overflow on the tab strip itself either way).

- **`frontend/src/lib/connectorSettingsTabPrefs.ts` (new)** persists the selected tab id to
  `localStorage` under `recruflow.connectorSettingsTab`, mirroring BUG33's
  `offerListPrefs.ts` precedent (bare `load.../save...` functions, no wrapper hook) but simplified
  — the module only stores a string id; "is this still a known connector" is checked by the
  consuming component against the live `useKnownSources()` list, since the prefs module itself has
  no way to know the registry. A persisted id pointing at a since-removed connector (or nothing
  persisted yet) falls back to the registry's first entry rather than rendering no tab as active.

### Fetch Scope row in connector settings (US47)

`ConnectorSettingsCard.tsx` gains a `FetchScopeRow` sub-component, rendered only when
`ConnectorOption.supports_fetch_scope` is `true` — a mode `<select>` (All offers / Filtered by
hard skills) plus a Save button calling `useConnectorSettings()`'s new `saveFetchScope(connector,
mode)`, which follows `saveRange`'s success/failure-boolean shape (not `saveAutoFetch`'s
void-returning one), since a `"filtered"` save can be rejected with HTTP 400 on an unsupported
connector and the UI needs to know. No "apply to all" bulk variant exists for this control,
mirroring the backend's deliberate lack of a bulk fetch-scope route (see [Ingestion pipeline:
Connector fetch
scope](ingestion.md#connector-fetch-scope-all-offers-vs-filtered-by-hard-skills-us47)). The row
was extracted into its own component (rather than inlined like the cadence/fetch-range rows)
purely to keep `ConnectorSettingsCard`'s cyclomatic complexity under this repo's ESLint
`complexity: 10` ceiling.

