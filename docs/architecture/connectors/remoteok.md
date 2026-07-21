# RemoteOK connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### RemoteOK connector

- **Purpose**: the simplest of the seven new job-board connectors added after Phase 3, and
  deliberately so — RemoteOK exposes a genuine, confirmed, public, unauthenticated JSON API at
  `GET https://remoteok.com/api`, no signup/key, and no pagination at all: a single `GET` returns
  a bare JSON array with no cursor/page parameter of any kind. This makes `RemoteOKConnector`
  structurally immune to the cursor-restart bug class two earlier connectors hit (there is no
  cursor to persist incorrectly, because there is no cursor), and needs no sitemap-walking
  helper, no Playwright, and no per-page rate-limit throttle.

- **The endpoint's real payload size is a fixed ~100-item rolling window, not an exhaustive
  archive**: confirmed live 2026-07-14 with plain `curl` against the real endpoint — the response
  is consistently 101 elements total (1 metadata + 100 job postings), regardless of how many jobs
  RemoteOK's own web UI shows. `extract_offers` does not cap anything itself; it hands back every
  non-metadata element the API returns, whatever that count is on a given call. Because there is
  no cursor, each scheduled run (every 120s, per this connector's interval override below) simply
  re-fetches that same latest-~100 window: dedup on canonical URL silently drops postings already
  seen, and any job newly published since the last run is picked up as a fresh one. A "fetch older
  postings" feature is not possible against this endpoint at all — there is no parameter that
  reaches further back than what a given call already returns. End-to-end ingestion confirmed live
  (100 fetched, 99 created — one duplicate posting within RemoteOK's own feed correctly collapsed
  by dedup, not a failure; a rerun against the same window then produced 0 created).

- **`extract_offers` override is the entire "bare list with a non-job first element" wrinkle**
  (`app/connectors/remoteok.py`): the endpoint's response is a bare JSON array whose first
  element (`payload[0]`) is API legal/attribution metadata, not a job posting. `extract_offers`
  checks for a non-list or empty payload (returning `None`, which `JobBoardConnector.fetch_page`
  turns into the standard "returned unexpected JSON shape" error log with no crash), then hands
  `payload[1:]` to the shared `extract_envelope_list`'s `allow_bare_list=True` path — no bespoke
  loop, no new `normalize.py` helper, since no other connector has this shape.

- **`next_cursor` always returns `None`**: a single-shot feed, same category as NoFluffJobs's
  existing pagination shape. Dedup on canonical URL alone (not a cursor) is what makes refetching
  the entire feed on every scheduled run correct and cheap — confirmed live: a second run against
  the same 100-element response reported `fetched: 100, created: 0`.

- **Seniority is left unmapped (`None`), not guessed from `tags`**: unlike SOLID.Jobs/JustJoin.it
  /NoFluffJobs/Pracuj.pl's controlled-vocabulary seniority fields, RemoteOK's `tags` is free-text
  with no reliable seniority signal. `map_offer` hardcodes `seniority: None` and never calls
  `normalize_seniority` at all (rather than calling it against an empty/no vocab entry), so
  `normalize.py` gets no `_SENIORITY_VOCAB[REMOTEOK]` entry — a deliberate fabrication-risk
  avoidance (OD-9's missing-field conservatism in the Matcher already covers this gracefully),
  not an oversight to "complete" later. `tags` is still stored on `industry_tags` (this is the
  first connector to populate that field) since it remains useful for the skill-match dimension.

- **Salary**: `salary_min`/`salary_max` are already plain numeric fields in the response (unlike
  every other connector's nested salary object), mapped through a small `_zero_to_none` helper
  (reusing `to_int`) that independently collapses RemoteOK's `0` "not specified" sentinel to
  `None` per field — not just the exact `(0, 0)` pair. `normalize_salary` is called with the
  literal `"USD"` as `raw_currency` (RemoteOK's payload carries no currency field at all), since
  `normalize_salary`'s own default (`"PLN"` when `raw_currency` is falsy) would otherwise silently
  mislabel a USD-denominated remote salary as PLN.

- **`remote` is hardcoded `True`, never computed**: RemoteOK is remote-only by construction — no
  per-offer remote flag exists in the payload because there's nothing to distinguish.

- **`canonical_url`** ← `url`, falling back to `apply_url` defensively (both were identical in
  every sample observed live) — the real `remoteok.com` URL, unmodified, satisfies the API's
  attribution requirement with no extra code.

- **Registered in `CONNECTOR_REGISTRY`** (`app/ingestion/registry.py`) as `REMOTEOK = "remoteok"`.
  `ensure_sources_exist`'s `_connector_config_overrides` (`app/scheduler/service.py`) gives it a
  `120`-second interval — shorter than the shared `300`s default, the opposite direction from
  Pracuj.pl's longer-interval override, since this is a single lightweight GET with no pagination
  cost. No scheduler, matcher, or frontend edit beyond the registry entry and this one interval
  override was needed — the same "adding a connector" checklist outcome every connector
  since Bulldogjob has confirmed. Automatically scoring-eligible via `LANGCHAIN_SOURCES`
  (`app/llm/matcher.py`) deriving from `CONNECTOR_REGISTRY.keys()`, and automatically visible to
  the frontend via `useKnownSources()`'s `GET /connectors` call — no `app/llm/matcher.py` or
  `frontend/src/` edit was needed for this connector at all.
