# NoFluffJobs connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

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
  same as any other (see "Scheduler" in ../ingestion.md), but is used purely as a staleness signal surfaced to
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
  | `seniority` | `seniority[]` | A list on the wire, observed always length 1 in live sampling; each item mapped to the shared canonical vocabulary via `app.ingestion.normalize.normalize_seniority` (P1US5), then joined with `", "` if ever multi-valued — see "Cross-connector schema consistency" in ../ingestion.md |
  | `salary_min`/`salary_max`/`salary_currency`/`contract_type` | `salary.{from,to,currency,type}` | `salary.type` takes values `permanent`/`b2b`/`zlecenie` in the wild — passed through verbatim as `contract_type`, permanently no vocabulary translation (out of scope per the `Contract Type` glossary entry, not deferred). Salary values arrive as floats and are coerced to `int`; currency passed through `normalize_salary` (P1US5) |
  | `posted_at` | `posted` | A Unix **milliseconds** epoch integer (not an ISO string, unlike JustJoin.it's `publishedAt`) — divided by 1000 and converted with `datetime.fromtimestamp(..., tz=UTC)` |
  | `description` | *(not mapped — always `None`)* | **Known limitation**, same as JustJoin.it's: the listing payload has no full job-description field |

