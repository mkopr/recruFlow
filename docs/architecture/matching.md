# Matching

[Architecture index](../../ARCHITECTURE.md)

### Unified Match Score schema

- **Purpose**: the foundational Phase 3 work. Every other Phase 3 piece (the LangChain Matcher,
  the `sjctl evaluate` wrapper, cross-engine consistency checks, the batch scoring job,
  the frontend score display) constructs or reads a `MatchScore` row against this schema, so the
  schema, the read endpoint, and the insert-never-overwrite invariant had to be locked in first. No
  new migration is needed — `match_scores` has existed since an earlier foundational migration but
  was never written to or read from until now.
- **`MatchScore`/`MatchScoreResponse` split (`app/schemas/match_score.py`)**: mirrors `Offer`/
  `OfferSummary` exactly — `MatchScore` is the domain-input model an engine constructs before
  persistence (no `id`, since the DB assigns it on insert), `MatchScoreResponse`
  (`from_attributes=True`) is the plain, already-validated read model `GET /offers/{id}/score`
  returns straight off an ORM row (`engine`/`score_percent` as plain values, no re-validation on
  the way out).
- **`score_percent: int` (`ge=0, le=100`), not a letter grade** — `MatchScore`
  now reports the Matcher's rounded `weighted_total` directly rather than bucketing it into a
  five-letter grade; see the "Percentage-based match score" section below for the full rationale
  and the migration off the original `Literal["A", "B", "C", "D", "F"]` design this bullet used to
  describe. `engine` is
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
- **No MatchScore-writing/persistence helper exists yet** — this was schema-plus-read-endpoint
  only, per its own scope; the LangChain Matcher and the abandoned `sjctl evaluate` wrapper would
  each need an insert path once they existed, and could share one if warranted. Introducing one
  now would have been speculative code with no caller.
- **No uniqueness constraint on `(offer_id, profile_id)`** — deliberately left alone; the
  acceptance criteria require multiple `MatchScore` rows per offer over time (re-scores, or scores
  against different profiles), so a new score is always inserted, never overwritten.

### LangChain Matcher

- **Purpose**: built directly on the Match Score schema and read endpoint above. Scores offers
  from all three sources (SOLID.Jobs, JustJoin.it, NoFluffJobs) against the active `Profile` and
  writes `MatchScore` rows. A second `sjctl evaluate` engine for SOLID.Jobs was originally planned
  but abandoned before implementation — see "SOLID.Jobs Matcher verification" below — so this is
  the only scoring engine; the batch scoring job (below) is the entry point that will call it.
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
- **`score_percent = round(_weighted_total(output) * 100)`** — the Matcher's
  internal 0.0–1.0 weighted total is surfaced directly as a 0–100 integer, with no threshold table
  or letter-grade bucketing in between. This module originally shaped a `GradeScale` class (a
  seam explicitly built for later configurable grade thresholds) here; that later percentage-based
  rework deleted both `GradeScale` and the configurable-threshold `scoring_config` entirely once
  there was no letter left to calibrate — see the "Percentage-based match score" section below.
  `DIMENSION_WEIGHTS` stays a plain dict, unaffected by that change — nothing has ever needed
  configurable weights.
- **Deal-breaker cap, enforced in code, not left to the LLM**: any `Profile.deal_breakers` entry
  matched in the offer's text caps `score_percent` at a fixed `40` (`_cap_score_for_deal_breaker`,
  only ever lowers, never raises — an already-low score is left unchanged). Before the switch to a
  percentage score this capped a letter grade at `D`; the mechanism changed to a numeric ceiling
  but the rule itself (deterministic, code-level, never LLM-judged) did not.
- **Deal-breaker detection is itself deterministic, never an LLM-judged field** — see
  `docs/adr/0014-deal-breaker-detection-deterministic-not-llm.md`. Folding detection into
  `_MatcherOutput` was considered and rejected: `Offer.description`/`title`/`company` are adversarial
  third-party text, and a listing could manipulate the model into denying a real deal-breaker match,
  defeating the cap's entire purpose. `_deal_breaker_hit` instead tokenizes the deal-breaker phrase
  (lowercase, split on hyphen/underscore/slash/whitespace) and matches with an *optional* separator
  between tokens, so `"on-site only"` matches `"on-site only"`, `"onsite only"`, and `"on site only"`
  alike, while a single-token deal-breaker like `"Java"` keeps plain word-boundary anchors and so
  never matches inside `"JavaScript"`.
- **Hard skill miss cap** is `deal_breakers`/`_deal_breaker_hit` inverted: a positive
  "must mention at least one of these" check where `deal_breakers` is a negative "must mention
  none of these" one. Live investigation found a Java-only offer scoring 86% for a Python-only
  profile — `skill_match` (30% weight) got hedged to ~0.5 by the LLM while the other five
  dimensions scored ~1.0, and nothing let one dimension veto the total from the positive side the
  way `deal_breakers` already vetoes it from the negative side.
  - **Modeled as a flag on existing `Skill` entries, not a parallel free-text list.** This
    originally shipped as a separate `Profile.core_skills: list[str]` (mirroring `deal_breakers`
    exactly), but this duplicated skill names already entered in `Profile.skills` and invited
    drift (typo/edit in one list but not the other). It was revised same-session to
    `Skill.hard: bool = False` — the frontend `SkillsTable` gets a star toggle per skill instead
    of `Profile` gaining a second list, and `_hard_skill_names(profile)` reads
    `[s.name for s in profile.skills if s.hard]` as the set to check. `CoreSkillsList.tsx` was
    deleted; there is no longer a `Profile.core_skills` field.
  - **CV extraction never sets `hard=True`**: `Skill` is shared between `Profile` and
    `CVExtraction` (the CV-upload LLM's structured-output target, see profile.md), so `hard`
    is technically exposed in that schema too. `extract_profile_from_cv_text`
    (`app/llm/cv_extraction.py`) force-resets every extracted skill's `hard` to `False`
    regardless of what the model output, the same deterministic-override pattern as
    `_apply_missing_salary_conservatism` — `hard` is a candidate preference, not a CV fact, and
    must never be inferred.
  - `_missing_hard_skills(profile, offer)` returns `True` only when the profile has at least one
    skill flagged `hard` and *none* of their names are found in the offer haystack — OR semantics
    fall out naturally, since the loop returns `False` on the first match. It reuses
    `_deal_breaker_hit`'s exact tokenize/regex/haystack machinery (factored into a shared
    `_offer_haystack(offer)` helper both functions call) rather than inventing new matching logic,
    so the same punctuation-variant and word-boundary guarantees apply symmetrically (`"Java"`
    still won't false-match inside `"JavaScript"`).
  - `_cap_score_for_missing_hard_skill` caps `score_percent` at `_HARD_SKILL_MISS_CAP = 25`, only
    ever lowering, never raising. Both caps are applied unconditionally in sequence in
    `score_offer_with_langchain` (deal-breaker check first, by precedent) — since
    `_HARD_SKILL_MISS_CAP` (25) is lower than `_DEAL_BREAKER_SCORE_CAP` (40), this composes as
    `min()` of both cap values for free, with no extra bookkeeping, when an offer trips both
    checks at once; each cap independently appends its own explanation to `rationale`, so a
    doubly-capped score's rationale names both the matched deal-breaker and the missing hard
    skills. No skill flagged `hard` (the default) never triggers this cap, so existing uncapped
    scores are unaffected.
- **Missing-field conservatism is a code-level backstop, not prompt-only** —
  `_apply_missing_salary_conservatism` clamps `salary_fit` to `<= 0.5` and appends a note to the
  rationale whenever `Profile.salary_min` and `Profile.salary_target` are both absent, regardless of
  what the (mocked-in-tests, non-deterministic-in-production) LLM output claims. This is scoped to
  salary only, per this story's acceptance criteria; `seniority_fit` has no backing `Profile` field
  at all to be conservative about, and `work_mode_location`/`contract_type` don't get an equivalent
  backstop yet — tracked as **OD-9**.
- **Routing**: `LANGCHAIN_SOURCES = frozenset({SOLID_JOBS, JUSTJOINIT, NOFLUFFJOBS})` and the pure
  predicate `is_langchain_source(connector)` decide which offers this chain scores — all three real
  connectors route here (see "SOLID.Jobs Matcher verification" below); only a `None`/unrecognised
  connector (e.g. a manually seeded `Source` row with no connector identity) is excluded.
  **`score_offers_with_langchain(session, profile_row, offers)`** is the batch entry point the
  batch scoring job (below) calls by name: it filters to langchain-routed offers, scores each, `session.add()`s the resulting
  `MatchScore` rows, and returns them — never committing (the caller controls the transaction
  boundary, matching `app.ingestion.persist` and `app.db.profile_repo`'s convention). A single
  offer's `MatcherError` is logged at WARNING and skipped; it never aborts the rest of the batch.
- **Prompt-injection defense**: the system prompt treats `Offer.title`/`description`/`company` as
  untrusted third-party data, never as instructions, mirroring the `jobs-evaluate` skill's rubric —
  a listing that tries to instruct the model to change its scoring behavior is itself scored as a
  red flag rather than obeyed.

### SOLID.Jobs Matcher verification

- **Purpose**: the originally-planned second scoring engine (`sjctl evaluate`, for SOLID.Jobs only)
  was abandoned before it was ever built — a follow-up confirmed there is only one engine, the
  LangChain Matcher, covering all three sources. This fixed the one place the Matcher still
  encoded the abandoned two-engine plan: `LANGCHAIN_SOURCES` was `frozenset({JUSTJOINIT,
  NOFLUFFJOBS})`, so `is_langchain_source("solid_jobs")` returned `False` and
  `score_offers_with_langchain` silently skipped every SOLID.Jobs offer passed to it, with no
  error and no log line.
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
  the existing missing-salary conservatism (see the LangChain Matcher section above) and the LLM's
  own "score conservatively when a field is missing" instruction apply exactly as they do for the
  other two sources — no
  SOLID.Jobs-specific handling exists or is needed anywhere in the scoring path.

### Batch scoring job

- **Purpose**: the work above left a schema, a read endpoint, and a fully working
  source-agnostic scoring function (`score_offers_with_langchain`), but nothing called it
  automatically, on demand, or queried which offers actually need scoring. This is a
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
  the query shape. Old `MatchScore` rows against the previous Profile are never deleted (the
  original "always insert, never overwrite" design described above).
- **Re-scoring on in-place Profile *edit***: the "Re-scoring on Profile change" bullet
  above only covers `profile_id` actually changing (activating a different row). Editing the same
  active profile's content in place — a new CV upload, a changed deal-breaker, a newly-starred
  hard skill — kept `profile_id` constant, so every offer that already had a `MatchScore` row for
  that id stayed permanently excluded from `_fetch_unscored_offers`, showing a stale score
  indefinitely; there was no notion of "this profile's content changed since this score was
  computed." Fixed in `app/db/profile_repo.py`'s `upsert_profile`: it now compares the row's
  previous `data` JSONB against the newly-validated `Profile.model_dump(mode="json")` before
  overwriting it, and if they differ *and* the row ends up active, calls the new
  `invalidate_scores_for_profile(session, profile_id)` — a plain `DELETE FROM match_scores WHERE
  profile_id = :id` — before returning. This is deliberately the cheapest of the fixes considered
  for this bug (full delete-and-redrain, not a `MatchScore.created_at < Profile.updated_at` staleness
  comparison): it needs no schema change and no edit to `_fetch_unscored_offers` at all — the
  offers simply reappear in the same "no MatchScore row exists" query the backlog-draining job
  (described below) already polls every `scoring_job_interval_seconds`, so a profile edit's full rescore
  happens automatically in the background, never blocking the save request itself. The
  `data_changed` comparison is what keeps a no-op resave (e.g. re-clicking "Set as active" with no
  edits) from needlessly nuking otherwise-still-valid scores.
- **`POST /score/batch`** (`app/api/routes/scoring.py`, `app/schemas/scoring.py`'s flat
  `BatchScoringResponse`): calls `run_batch_scoring`, commits, returns the counts. Always `200`
  — there's no per-connector routing to 404 on the way `POST /ingest/{source}` has, and
  `run_batch_scoring` never raises (mirrors `score_offers_with_langchain`'s own
  never-raise-out-of-a-batch convention).
- **Automatic post-ingestion trigger, added then removed again**: the trigger used to live
  in `app/scheduler/service.py`, called only from `_run_source_async` — meaning
  `POST /ingest/{source}` (the *only* fetch action `FetchNowButton.tsx` actually calls) never
  scored anything, ever, since it goes through a sibling code path
  (`app/ingestion/service.py`'s `_trigger_ingest_async`) that never called it. The fix moved
  `_trigger_batch_scoring_after_ingestion()` into `app/ingestion/lifecycle.py`'s
  `run_with_lifecycle` — the one call site shared by manual `/ingest`, manual `/scheduler/run`,
  and automatic APScheduler jobs alike — calling it unconditionally after `dispatch_ingestion`
  returns, on both the success and error branches. Once a dedicated
  `scoring:backlog` job was added on its own independent interval, this made *two* unsynchronized
  triggers race the same unscored backlog: an ingestion run and a `scoring:backlog` tick landing
  close together could each fetch the same "unscored" offers before either committed, producing
  duplicate `MatchScore` rows for the same offer/profile pair (measured at ~43% wasted
  duplicate LLM calls against the live backlog). The fix for that removed
  `_trigger_batch_scoring_after_ingestion()` and both call sites in `run_with_lifecycle` entirely
  — `scoring:backlog` is now the *only* automatic trigger, exactly matching the original
  intent of a backlog-drain "fully independent of any source's ingestion schedule." Ingestion
  itself no longer scores anything; a freshly-ingested offer is picked up on the backlog job's
  next tick (or immediately via manual `POST /score/batch`), not synchronously with the fetch.
- **Mutual exclusion inside `run_batch_scoring` itself**: rather than trust every current
  and future caller to never overlap, `app/scoring/batch.py` now serializes all calls on a
  module-level `asyncio.Lock` (`_scoring_lock`) — `run_batch_scoring` is a thin wrapper that
  acquires the lock and delegates to `_run_batch_scoring_locked`. This is what actually closes
  the race: the scheduled `scoring:backlog` tick and a manual `POST /score/batch` call are still
  two independent callers, each opening its own session, so removing the earlier trigger alone only
  removed one of several possible overlaps. With the lock, a second caller's own
  `_fetch_unscored_offers` query runs only after the first caller's transaction has committed, so
  it never sees an offer the first call is still in the middle of scoring.
- **No unique constraint added on `match_scores (offer_id, profile_id)`**: this was
  suggested as part of the race-condition fix, but the Match Score schema section above already
  documents a deliberate decision to allow multiple
  `MatchScore` rows per offer over time (re-scores), with reads always taking the most recent row
  — `tests/integration/test_offers_routes.py`'s `test_rescoring_offer_inserts_new_row_without_overwriting_existing`
  and its two sibling "most recent score" tests exercise exactly this. A hard uniqueness
  constraint would foreclose that intentional future capability for no real benefit now that the
  actual race is closed at the trigger and lock level. Instead, a one-off data-only
  migration (`134e4fa8b06d`) deletes the accidental duplicate rows the race had already
  produced, keeping the newest row per `(offer_id, profile_id)` pair — pure cleanup, no schema
  change.
- **Bounded batch size and live progress**: with the automatic trigger briefly firing on every
  ingestion (before it was removed, see above), a single manual `/ingest` call could otherwise try
  to score an unbounded backlog synchronously (this repo's dev database had ~15k offers
  ingested-but-never-scored at one point, since nothing had ever scored them). `run_batch_scoring` now takes
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
  ingestion itself triggered scoring, as described above. That trigger was later removed entirely, so
  neither guard has anything left to protect against and both were deleted along with it.
- **Fetch Range-aware selection and offer cleanup**: `_fetch_unscored_offers` and
  `_count_unscored_offers` now reuse `resolve_fetch_range` (`app/ingestion/runner.py`) so
  scoring never spends an LLM call on an offer the user has already excluded from ingestion via a
  narrowed Fetch Range — see CONTEXT.md's "Fetch Range" and "Offer Cleanup" entries, and
  `docs/adr/0020-scoring-backlog-filter-favors-simplicity-over-scan-cost.md`. The query is split
  into `_candidate_offers_stmt(profile_id)` (the existing already-scored/open-failure/connector
  filter, now also selecting `Source.config_json`) and a pure predicate, `_in_fetch_range(offer,
  config_json)`, applied in Python over the full candidate set rather than in SQL — deliberately
  accepting a full per-call materialize (over the DB-side `.limit()`/`func.count()` the
  earlier version used) in exchange for not duplicating `resolve_fetch_range`'s parsing/fail-open
  logic in a second, SQL-shaped form; see the ADR for the concrete cost/benefit reasoning. A
  Source with `mode: "all"` or no `fetch_range` at all is unaffected — every offer from it is
  still a candidate exactly as before. Narrowing a Source's Fetch Range never invalidates an
  existing `MatchScore` (unlike a Profile edit, described above) — it only changes future offer
  selection; an offer that becomes ineligible today becomes eligible again automatically, with no
  manual intervention, the moment its Source's range widens or flips back to `"all"`.
- **`DELETE /offers` and `GET /offers/cleanup-preview`**: a manually-triggered, global
  (cross-source) bulk delete for offers that have aged out, plus a paired read-only preview so the
  Settings UI can show an accurate pre-delete count before the user confirms. Both routes share
  `_partition_offers_for_cleanup(session, older_than)` (`app/api/routes/offers.py`): an Offer is a
  deletion candidate only if `posted_at` is non-null and strictly before `older_than` (a null
  `posted_at` is never treated as "old" the way scoring's Fetch Range treats it as "now" — see
  CONTEXT.md's "Offer Cleanup" entry for why the two deliberately differ); candidates that have
  *any* `Application` row, in any status, under any Profile, are excluded and counted separately as
  `skipped` rather than deleted. Deleting an Offer cascades its `MatchScore`, `ScoringFailure`, and
  `CVVersion` rows in the same transaction, explicit ordered `DELETE`s rather than a schema-level
  `ondelete=CASCADE` (matching this codebase's established convention, e.g.
  `_delete_sources_with_offers` in the test suite) — `Application`'s own FK to `offers.id` stays a
  hard, untouched `RESTRICT`, since any offer with an Application row is by construction never a
  deletion candidate. `GET /offers/cleanup-preview` is registered *before* `GET
  /offers/{offer_id}` in the router: FastAPI's `{offer_id}` path parameter matches any string at
  the Starlette routing layer (the `int` type is enforced by FastAPI's own validation *after* the
  route already matched, not by the route's regex), so `cleanup-preview` would otherwise match
  `get_offer` first and 422 on int-conversion before ever reaching the intended handler.
  `older_than` is a required `Query(...)` param on both routes (FastAPI 422s automatically if it's
  missing) — there is no "delete everything" default. As of this writing, `Application` rows have no
  creation path anywhere in the running app (Phase 4 — CV tailoring/sending — is not yet built),
  so in real usage today `skipped` is always `0`; the check is built now against the existing
  schema so it is already correct once Phase 4 lands, and is exercised today only by tests and by
  inserting an `Application` row directly via SQL for manual verification.

### Configurable grade thresholds — superseded by the percentage-based match score

This earlier effort added a `scoring_config` table, `ScoringConfig` schema, `scoring_config_repo.py`, a
`GET`/`PUT /scoring-config` pair, `app/llm/matcher.py`'s `build_grade_scale`, and a "Grade cutoffs"
Settings card, all in service of making the letter-grade thresholds user-editable. The
percentage-based rework below deleted every piece of it outright rather than migrating it: once
`MatchScore` reports a plain 0–100 percentage instead of a letter, there is no shared "what does B
mean" calibration left for a threshold table to hold — a minimum-score filter and an alert
threshold are now each just a number the user types in, no persisted config in between. See the
next section.

### Percentage-based match score

- **Purpose**: every prior piece of Phase 3 hardcoded, threaded through, or built UI around a
  five-bucket letter grade, even though the Matcher already computed a continuous 0.0–1.0
  `weighted_total` internally (see the LangChain Matcher section above) and discarded it the
  moment a letter was picked. This
  stops discarding it: `MatchScore.score_percent = round(weighted_total * 100)` is now the
  headline field everywhere a `grade` used to be. It fully supersedes the configurable grade
  thresholds above (a plain percentage needs no shared calibration table) and revises the
  grade-shaped parts of the Match Score schema, offer-list scores, and auto-fetch-cadence work to
  their percentage equivalents, without reopening any of their unrelated
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
  `scoring_config_repo.py`, and `GET`/`PUT /scoring-config` are all removed — see the
  "Configurable grade thresholds" section above.
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
  Fetch cadence (unchanged) and Notifications (this section's updated form).
- **Theme (`frontend/src/index.css`)**: the five `--color-grade-*` custom properties and
  `.badge-grade-*` classes are removed (colour is now computed inline via a `style` prop, not a
  CSS class); `--color-grade-none`/`.badge-grade-none` are renamed to `--color-score-none`/
  `.badge-score-none`, keeping their declarations unchanged — the neutral "not yet scored" state
  itself is unaffected by this story.

