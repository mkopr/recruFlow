# JustJoin.it connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### JustJoin.it connector

- **Investigation finding (resolves Open Decision OD-4 for JustJoin.it — NoFluffJobs's half of
  OD-4 was resolved separately and is documented in nofluffjobs.md)**: JustJoin.it exposes a real,
  unauthenticated JSON endpoint, so Path A (thin HTTP client) was implemented — no Playwright
  scraper. The endpoint was found by downloading justjoin.it's own served Next.js JS bundles and
  grepping them for the API client code, since a local headless-Chromium network capture (the
  more direct "devtools Network tab" approach) never completed in this sandboxed environment. The
  obvious guesses were wrong: the page's own runtime config names `https://api.justjoin.it` as
  `baseApiUrl`, but `GET https://api.justjoin.it/offers` returns `404 Invalid endpoint`;
  `baseCpUrl` (`https://profile.justjoin.it`) redirects to a login page. The bundle code backing
  the public `/job-offers` listing page actually calls a gateway whose `baseURL` resolves to the
  *relative* path `/api/candidate-api` (proxied through justjoin.it's own server), giving the real
  endpoint: `GET https://justjoin.it/api/candidate-api/offers?from=<cursor>&itemsCount=<page
  size>` — see `docs/adr/0003-justjoinit-json-endpoint-investigation.md` for the full trail
  (mirrors ADR 0002's "verify against the live system" discipline).
- **`app/connectors/justjoinit.py`** — the second of three sibling connectors shipped together
  with SOLID.Jobs and NoFluffJobs. Exposes
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
- **Pagination early-stops on already-seen offers, with a hard ceiling as backstop**:
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
- **`force_refresh=True` bypasses the early-stop checkpoint**:
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
  | `remote` | `workplaceType` | JustJoin.it's own 3-value enum is `{"remote", "hybrid", "office"}` — mapped to a canonical `bool` via `app.ingestion.normalize.normalize_remote`; this happens to already satisfy the `Remote` glossary rule that hybrid is not remote |
  | `seniority` | `experienceLevel` | Mapped to the shared canonical vocabulary via `app.ingestion.normalize.normalize_seniority` — see "Cross-connector schema consistency" in ../ingestion.md |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `employmentTypes[0].{from,to,currency,type,gross}` | **Known limitation**: a JustJoin.it offer can list several employment-type entries (e.g. both `b2b` and `permanent`, each further repeated per display currency); only the first/primary entry is mapped, matching the same simplification `map_solid_jobs_offer` was allowed for SOLID.Jobs's own multi-field shape. Salary values arrive as floats and are coerced to `int` for the `Integer` DB column; currency and the `gross` flag are passed through `normalize_salary`, which logs (but does not fabricate a conversion for) non-`PLN` currencies and `gross: false` figures. `contract_type` remains a raw pass-through of `type` — permanently, not deferred — per the `Contract Type` glossary entry being explicitly out of scope for vocabulary unification |
  | `posted_at` | `publishedAt` | ISO datetime string, parsed by `Offer`'s pydantic validation |
  | `description` | *(not mapped — always `None`)* | **Known limitation**: the list endpoint's offer objects do not include the job description body; only the per-offer detail endpoint (`GET /api/candidate-api/offers/{slug}`) has it, and fetching that per offer would multiply request volume for every ingestion run. `description` is nullable on `Offer`, so this is schema-compliant; a later story could add a bounded per-offer detail fetch if the description text becomes necessary (e.g. for CV tailoring) |
