# Bulldogjob connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### Bulldogjob connector (P3US38)

- **Purpose**: the first of the six connectors P3US37 queued back-to-back (P3US38-44,
  Bulldogjob through WeWorkRemotely), and the first real test of whether P3US37's "adding a
  connector, end to end" checklist holds for a source that doesn't fit the cursor-pagination
  template. It didn't, cleanly — see the Domain Decision below.

- **Why the obvious approaches don't work** (investigated live 2026-07-13, see
  `docs/adr/0023-bulldogjob-sitemap-and-embedded-next-data-investigation.md` for the full
  trail): Bulldogjob has no published API. `?page=N` on the listing page returns `200` but the
  page number in the response body never advances past `1` — the real "next page" is a
  client-side call, not a plain GET. The Next.js client-navigation shortcut
  (`_next/data/<buildId>/companies/jobs.json`) 404s. What does work: the site's own
  `sitemap.en.xml.gz` → `en/jobs.xml.gz` sub-sitemap enumerates every live job URL in one
  request (no pagination needed at all), and each job detail page embeds the full record as
  structured JSON in a `<script id="__NEXT_DATA__">` tag — the same ELT-eligible "parse
  embedded JSON" shape the other three connectors' JSON-endpoint responses have, just arriving
  via an HTML response instead of a dedicated API.

- **Two-phase fetch, not cursor pagination**: `BulldogjobConnector`
  (`app/connectors/bulldogjob.py`) overrides both `fetch_page` and `run` rather than using
  `JobBoardConnector`'s inherited cursor loop — `next_cursor` always returns `None`, since the
  sitemap fetch (not this method) is what changes between runs. `run()` calls
  `fetch_sitemap_urls()` once (index sitemap → jobs sub-sitemap → filtered list of real job
  URLs), then hands `run_paginated_ingestion` a closure that treats `page_size`/`max_pages` as
  "how many sitemap URLs to live-fetch per chunk / per run" rather than API pages — fallback
  defaults `page_size=20`, `max_pages=50` (vs. the base class's 100/100) bound total live
  per-run HTTP traffic to `page_size * max_pages = 1000` fetches, comfortably covering the
  ~1000-URL sitemap observed live. `already_seen_stop_threshold` applies unchanged, at the
  granularity of one sitemap-URL chunk (a chunk fully seen stops the next chunk from being
  fetched at all, not just from being persisted).

- **Sitemap filtering, a live finding not anticipated by the story**: `jobs.xml.gz` mixes real
  job detail URLs (`/companies/jobs/<numeric-id>-<slug>`) with filter/tag listing pages
  (`/companies/jobs/s/skills,Java`, `/companies/jobs/s/role,qa`, ...) — confirmed live,
  ~5% of sitemap entries. `fetch_sitemap_urls` filters to the numeric-id pattern before
  returning, so these never reach a live per-URL fetch.

- **`fetch_gzip_xml` (`app/connectors/http.py`)** — the gzip+XML sibling to `fetch_json`,
  same error-handling shape (`httpx.HTTPError` → log + `None`, malformed content → log +
  `None`), used for both sitemap levels. `extract_next_data` (module-level function in
  `bulldogjob.py`, independently unit-testable) regexes the `__NEXT_DATA__` script tag out of
  a detail page's HTML and `json.loads`s it, logging `"Bulldogjob returned unexpected page
  shape"` (matching every other connector's failure-logging convention) on either a missing
  tag or malformed JSON inside it. A single broken/dead detail URL is skipped, not fatal to
  its chunk — the same "skip this one item, keep going" posture `ingest_offer` already has for
  one invalid offer.

- **Raw payload = the parsed `__NEXT_DATA__` dict, not the HTML**: `fetch_page`'s closure
  appends `extract_next_data(html, url=url)`'s return value directly to the offers list, and
  that dict is what `run_paginated_ingestion` persists verbatim as `raw_payload` — `map_offer`
  never mutates it.

- **`map_offer` field mapping** (`app/connectors/bulldogjob.py`, confirmed against real sampled
  detail pages 2026-07-13): `canonical_url` is reconstructed from the job's own `id` field
  (`https://bulldogjob.com/companies/jobs/{id}`) — `id` already contains the full
  `<numeric-id>-<slug>` string, so no separate slug lookup is needed, and this is also the
  same URL the sitemap listed (used as `dedup_hash`'s primary key). `remote` is already a
  plain boolean on the job record (`job.remote`), so no `_REMOTE_STRING_VOCAB` entry was
  needed — `normalize_remote` handles a bool input generically. `experienceLevel` (`junior`,
  `medium`, `senior`, `lead` observed live) is mapped via a new `_SENIORITY_VOCAB[BULLDOGJOB]`
  entry (`medium` → `mid`, others map to themselves). Salary is a known-limitation area: real
  listings almost always carry salary as a free-text range string (`b2bSalary.money`, e.g.
  `"180 - 200"`/hour) with `minValue`/`maxValue` null — `normalize_salary` is not extended to
  parse that free text (mixing hour/month/year figures into one `salary_min`/`salary_max`
  pair without unit conversion would silently corrupt the data), so most Bulldogjob offers
  have `salary_min`/`salary_max = None`, mirroring NoFluffJobs's own documented "no full
  description" gap. `_pick_salary` prefers `employmentSalary`, then `b2bSalary`, then
  `otherSalary` (a job can offer more than one contract type), and derives `contract_type`
  from whichever block was picked. `description` concatenates the `offer` (benefits) and
  `requirements` (responsibilities + requirements) HTML fields when present — unlike
  JustJoin.it/NoFluffJobs, a Bulldogjob detail page's `__NEXT_DATA__` does carry real body
  text.

- **Registered in `CONNECTOR_REGISTRY`** (`app/ingestion/registry.py`) as `BULLDOGJOB =
  "bulldogjob"`, constructed once at import time like the other three — no scheduler,
  matcher, or frontend edit was needed, confirming P3US37's "adding a connector" checklist
  holds even for this structurally different source.

- **Supports Fetch Scope (US47)**: `fetch_filtered_sitemap_urls(config, term)` fetches
  `bulldogjob.com/companies/jobs/s/skills,<Term>`, whose embedded `__NEXT_DATA__` carries job
  summaries under `props.pageProps.jobs` (each `id` already the full `<numeric-id>-<slug>`
  string, so detail URLs are built directly with no separate slug lookup). Pagination on this
  page is client-side only (`?page=`/`?perPage=` are silently ignored server-side), so a filtered
  fetch is capped at one page — up to 50 offers — per hard-skill term; see `docs/adr/0027` for
  the full live-research findings and
  [Ingestion pipeline: Connector fetch scope](../ingestion.md#connector-fetch-scope-all-offers-vs-filtered-by-hard-skills-us47).

