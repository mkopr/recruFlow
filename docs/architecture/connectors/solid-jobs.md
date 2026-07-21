# SOLID.Jobs connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### SOLID.Jobs connector (direct API, replacing an earlier `sjctl` subprocess wrapper)

- **`app/connectors/solid_jobs.py`** — the first of three sibling connectors
  (SOLID.Jobs, JustJoin.it, NoFluffJobs, shipped together). Originally a subprocess wrapper around the
  `sjctl` CLI; rewritten (see
  `docs/adr/0012-solid-jobs-direct-api-replaces-sjctl-subprocess.md`) to call SOLID.Jobs' own
  public HTTP endpoint directly, once the vendor confirmed `sjctl` itself was just a thin wrapper
  over that same endpoint. Exposes
  `run_solid_jobs_ingestion(session, source, *, campaign, force_refresh=False) -> IngestionResult`
  as the single public entrypoint (unchanged signature) — it does not commit the session (same
  convention as `persist_offer`) and does not create or seed a `Source` row itself.
- **Endpoint**: `GET https://solid.jobs/public-api/offers/{division}` — `division` is a URL path
  segment (`build_offer_url`, defaulting to `"IT"`), not a query param. No auth; `campaign` is a
  required query param. `_fetch_solid_jobs_json` pins `X-Api-Version: 1.0` on every request (the
  only one of the three connectors that pins an API version — the other two have no such header
  to pin).
- **`config_json` schema for a SOLID.Jobs Source row** (mirrors JustJoin.it's own config surface):
  `division` (str, defaults to `"IT"`) → URL path segment; `cities` (list[str]) →
  `search.cities` (comma-joined); `min_salary` (int) → `search.minimumSalary`; `experience_levels`
  (list[str]) → `search.experiences` (comma-joined); `terms` (list[str]) → `search.searchTerm`
  (comma-joined), the technology/free-text filter (e.g. `["python"]`); plus `page_size`,
  `max_pages`, `already_seen_stop_threshold` (pagination config, same defaults and meaning as
  JustJoin.it's). `build_offer_params` does no validation of these — a malformed config value
  fails loudly via `str()` coercion rather than being silently dropped, since `config_json` is
  already-validated-at-write-time internal configuration, not user input. **Known live-API
  limitation** (see ADR 0012): `search.experiences` only accepts a single value in practice —
  multi-value input (comma-joined or repeated) returns `400` from the live API — even though
  `build_offer_params` will still comma-join more than one configured `experience_levels` entry;
  fixing this is an open follow-up, not implemented yet.
- **Response envelope, confirmed live 2026-07-05** (see ADR 0012, resolving what had until then
  been an open question, before this connector had live access): `{"jobs": [...], "pageIndex",
  "pageSize", "totalCount", "totalPages"}` — the same `"jobs"` key sjctl's own `search --json` used.
  `salary: {from, to, currency, employmentType}`, `locations: string[]`, `isRemote`/`isHybrid`,
  `experienceLevel`, `validFrom`, `description` all match the pre-rewrite field shape almost
  field-for-field.
  - `_extract_offers(payload)` — single-arg now (no `list_key`/`item_key`; that was purely an
    artifact of the old sync-vs-search envelope split, which no longer exists). Reads a bare list
    directly, or the `"jobs"` key from a dict payload; anything else returns `None` so the caller
    can distinguish "zero offers" from "the response shape changed".
  - `map_solid_jobs_offer` (renamed from `map_sjctl_offer`, no field changes): `locations` (list) →
    `Offer.location` (single string) joined with `", "`. `isHybrid` is dropped from the normalised
    field — `Offer.remote` is `isRemote` only, not `isRemote OR isHybrid`, since folding hybrid
    into "remote" would misrepresent hybrid roles (raw `isHybrid` is still preserved in
    `raw_payload`). `contract_type` maps from `salary.employmentType` (`"UoP"`/`"B2B"`) rather than
    the top-level `contractTime` (`"full_time"`/`"part_time"`), since "contract type" in this
    domain means employment form, not work-time schedule (see the `Remote` and `Contract Type`
    glossary entries in `CLAUDE.md`). `description` is stored as the raw HTML the API returns,
    unstripped — HTML-to-text is deferred to whichever later phase actually needs plain text (CV
    tailoring).
- **Pagination and `force_refresh`, JustJoin.it's model, not NoFluffJobs' no-op**: every
  request sets `sortActive=validFrom&sortDirection=desc`, giving the same newest-first
  precondition JustJoin.it's endpoint relies on (ADR 0009). `run_solid_jobs_ingestion` interleaves
  fetch-then-persist per page (`pageIndex`/`pageSize`, no cursor field — "fewer offers returned
  than `pageSize`" is the end-of-results signal) and stops early once
  `already_seen_stop_threshold` consecutive already-seen offers accumulate, exactly mirroring
  `run_justjoinit_ingestion`'s `_persist_offers` shape. `force_refresh=True` bypasses that
  checkpoint (ADR 0010's model) instead of switching sjctl subcommands — the old sjctl
  watch-scoped "sync" concept (ADR 0001) no longer exists in the direct API and has no
  replacement, since a "watch" was never a resource the direct API exposed.
- **`_fetch_solid_jobs_json`** is the sole HTTP boundary, structured identically to
  `_fetch_justjoinit_json`/`_fetch_nofluffjobs_json`: delegates to the shared
  `app.connectors.http.fetch_json`, which catches `httpx.HTTPError` (connection/timeout/non-2xx via
  `raise_for_status()`) and `json.JSONDecodeError` on `response.json()`, logging at `ERROR` and
  returning `None` in both cases — never raises. `run_solid_jobs_ingestion` turns a `None` from
  either `_fetch_solid_jobs_json` or `_extract_offers` into
  `IngestionResult(ok=False, fetched=0, created=0, error_message=...)` only when it happens on the
  first page; a later-page failure logs a warning and returns whatever was already fetched, same
  as JustJoin.it.

- **Supports Fetch Scope**: `SolidJobsConnector.apply_fetch_scope_term` injects a
  single-element `terms` list into `config`, routing one hard-skill term at a time into
  `build_offer_params`'s existing (previously unpopulated) `search.searchTerm` param — see
  [Ingestion pipeline: Connector fetch scope](../ingestion.md#connector-fetch-scope-all-offers-vs-filtered-by-hard-skills).
