# Profile

[Architecture index](../../ARCHITECTURE.md)

### Profile data model (P2US1)

- **Purpose**: the first Phase 2 story. Defines `app/schemas/profile.py`'s `Profile`, the
  canonical, source-agnostic candidate-facts document that US19's LLM extraction, US20's frontend
  editor, and this story's own `PUT /profile` all validate against. No new migration is needed —
  the `profiles` table's existing `data` JSONB column (P0US5) already satisfies "profiles DB table
  stores these fields plus an `is_active` boolean flag"; the structured fields live inside `data`,
  validated at the application layer, the same ELT-adjacent split `offers.raw_payload` already
  uses.
- **Field list**: `skills` (`Skill`: `name`, `proficiency`, `years`, `category`, `hard` — the last
  added by P3US32, a candidate-marked "this is a hard requirement" flag consumed by the matcher's
  hard-skill-miss cap, see the P3US22 section in matching.md), `past_roles`
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
  or `[]`) — `Skill.hard` (P3US32) is the one preference-like field that rides along on a
  CV-derived nested object rather than a top-level `Profile` field, so it gets its own explicit
  force-reset-to-`False` step instead of "just don't put it in `CVExtraction`" (see the P3US22
  section below).
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

