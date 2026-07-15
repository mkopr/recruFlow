# Pracuj.pl connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### Pracuj.pl connector (P3US41)

- **Purpose**: the direct sequel to P3US39 (The Protocol) — same operator (Grupa Pracuj), same
  Cloudflare Managed Challenge blocker independently confirmed on Pracuj.pl, but here the Phase
  1 feasibility spike passed, so Phase 2 (this connector) shipped where The Protocol's did not.

- **Why this connector uses Playwright unlike the other nine**: every plain-HTTP path into
  pracuj.pl — homepage, its own robots.txt-listed sitemap
  (`SiteMaps/CurrentOffers/SiteMapIndexJobOffers.xml`), a search-listing URL — returns `403`
  with a `cf-mitigated: challenge` header, confirmed live 2026-07-14 with plain `curl`. Unlike
  The Protocol, five fresh-browser-launch headless Playwright navigations spread across ~3.5
  minutes, plus one headed navigation under a local Xvfb display, all reached real content
  cleanly (`200`, no `cf-mitigated` header, no challenge markers) — no single-lucky-pass
  escalation pattern. See
  `docs/adr/0026-pracuj-playwright-cloudflare-feasibility-spike.md` for the full spike trail and
  `docs/adr/0024` for the contrasting failed spike this one was modeled on.

- **Pracuj.pl's own sitemap is stale, so listing-page pagination replaces it as the enumeration
  source**: every one of the 12 sub-sitemaps under `SiteMapIndexJobOffers.xml` has a `lastmod`
  from November/December 2021 — over four years old at implementation time (2026-07-14) despite
  being live-linked from robots.txt. `PracujConnector` instead enumerates offers via Pracuj.pl's
  own keyword-filtered search listing (`https://www.pracuj.pl/praca/{keyword};kw?pn={n}&rop={page_size}`),
  which embeds live results as a React Query SSR cache
  (`props.pageProps.dehydratedState.queries`, keyed `"jobOffers"`) inside each page's
  `__NEXT_DATA__` script tag — the same embedded-JSON-in-SSR-HTML shape Bulldogjob's
  `__NEXT_DATA__`/Rocket Jobs's JSON-LD precedent established, just nested one level deeper.
  Every offer's own detail page (`_dehydrated_query_data(..., "jobOffer")`) is then fetched for
  the richer structured record `map_offer` needs (numeric salary per contract type, a native
  boolean remote flag) that the listing summary alone doesn't carry.

- **IT-category filtering, applied at enumeration, not after**: given Pracuj.pl's cross-industry
  breadth (a live "IT-labeled" category URL guess, `informatyka-it;sc-15005`, actually returned
  the *unfiltered* general feed — lawyers, warehouse workers, drivers, mixed in with a handful of
  IT titles — because the guessed category id didn't match Pracuj.pl's real dictionary), this
  connector instead uses Pracuj.pl's own keyword-search URL scheme
  (`/praca/{quote(category_filter)};kw`, confirmed live via the homepage's own "IT" tab link),
  default `category_filter="it"`. The server performs the match before this connector ever
  detail-fetches anything, mirroring `SolidJobsConnector`'s `division` config precedent but
  server-side rather than client-side — `config_json["category_filter"]` on a Pracuj.pl `Source`
  row is the equivalent knob.

- **Browser-context reuse, rate limiting, and the async/sync seam this required**
  (`app/connectors/pracuj.py`): one Playwright Chromium browser + one browser context + one page
  are launched once per `run()` call and reused for every listing and detail fetch in that run,
  not relaunched per page. A deliberate `rate_limit_delay_seconds` (default `4.0`, vs. every
  other connector's `1.0`) is applied via `asyncio.sleep` before every fetch, given the added
  cost of browser-based fetching the story calls out. Because `JobBoardConnector`'s inherited
  `fetch_page` closure contract (used by `run_paginated_ingestion`) is a *synchronous* callable —
  fine for every other connector's blocking `httpx.get`, but incompatible with Playwright's
  async-only API inside a running event loop — `PracujConnector.run` does all Playwright-driven
  work (`_collect_offers`) upfront as one awaited async call, collecting a bounded, in-memory
  list of already-fetched offer-detail dicts (capped at `page_size * max_pages`), then hands
  `run_paginated_ingestion` a trivial synchronous closure that slices that list — the same
  "pre-fetch then slice" shape Bulldogjob/Rocket Jobs use for their sitemap-derived URL list, just
  with the *content* pre-fetched too, not only the URLs. One real consequence: `already_seen_stop
  _threshold`'s early-stop optimization (BUG02/ADR0009) no longer reduces *live browser-fetch*
  cost for this connector the way it does for the httpx-based ones, since all fetches must
  complete before that check can run — the `page_size`/`max_pages` cap is this connector's primary
  cost control instead, deliberately smaller than the other connectors' defaults
  (`page_size=10`, `max_pages=5`, vs. Bulldogjob/Rocket Jobs's `20`/`50`).

- **Monthly vs. hourly salary — a Pracuj.pl-specific wrinkle no prior connector had**: a
  `typesOfContracts[].salary` block carries a `timeUnit.id` (`0` = monthly, non-zero = hourly,
  confirmed live 2026-07-14: a B2B contract type is typically quoted hourly, e.g. `140–155
  zł/godz.`, while UoP is typically monthly, e.g. `6000–8500 zł/mies.`). `_pick_monthly_salary`
  (`app/connectors/pracuj.py`) only ever feeds a monthly-rate block into `salary_min`/`salary_max`
  — preferring UoP among monthly options, falling back to any other monthly contract type — and
  reports an hourly-only contract type's name as `contract_type` without ever mixing its numeric
  rate into a field meant for a monthly figure. This is the same "leave it None rather than guess"
  posture Rocket Jobs's missing-field handling established, applied to a unit-mismatch case
  instead of an absent-field case.

- **`map_offer` field mapping** (`app/connectors/pracuj.py`): `title` ← `attributes.jobTitle`,
  `company` ← `attributes.displayEmployerName`, `location` ← joined
  `attributes.workplaces[].displayAddress`, `canonical_url`/`external_id` ← `attributes
  .offerAbsoluteUrl` / `jobOfferWebId`, `remote` ← `attributes.employment.entirelyRemoteWork`
  (already a native boolean — `normalize_remote` returns it as-is via its bool branch, so
  `normalize.py` gets no `_REMOTE_STRING_VOCAB[PRACUJ]` entry, there being no raw string value to
  seed one from), `seniority` ← `attributes.employment.positionLevels[].pracujPlName`, mapped
  through a new `_SENIORITY_VOCAB[PRACUJ]` built from Pracuj.pl's own 11-entry `positionLevels`
  dictionary (confirmed live 2026-07-14), `posted_at` ←
  `publicationDetails.dateOfInitialPublicationUtc`, `description` ← `attributes.description` (a
  server-truncated preview even on the detail page — confirmed live at ~240 characters ending in
  `...` — used as-is, not treated as a parsing failure).

- **Failures surface loudly**: an enumeration failure (the first listing-page fetch itself)
  returns `IngestionResult(ok=False, ...)` directly. A later failure — another listing page or
  any detail-page fetch returning `None`, including a Cloudflare challenge page reappearing
  mid-run — stops collection (rather than continuing to burn rate-limited attempts against a
  likely-blocked session, per ADR 0024/0026's escalation finding) and records one
  `IngestionFailure` row (`FailureType.PAGE_FETCH_FAILED`) via the same `record_failure` path
  every other connector's dead-letter queue uses (P3US33), with whatever offers were already
  collected still persisted rather than discarded.

- **Registered in `CONNECTOR_REGISTRY`** (`app/ingestion/registry.py`) as `PRACUJ = "pracuj"`.
  `ensure_sources_exist` (`app/scheduler/service.py`) layers a Pracuj.pl-specific override
  (`_connector_config_overrides`) on top of the shared default seed: a `3600`-second interval
  (vs. the shared `300`s default — expensive browser-based fetching against a huge, non-IT-only
  site warrants a much longer cadence, the same rationale ADR 0024/0026 established) and a
  non-empty `category_filter: "it"` default, so a freshly seeded source never floods the offer
  list with every industry Pracuj.pl lists. No scheduler, matcher, or frontend edit beyond that
  was needed — the same P3US37 "adding a connector" checklist outcome every connector since
  Bulldogjob has confirmed.

- **`Dockerfile` bakes in the Chromium browser, not just the `playwright` pip package**: `uv
  sync --frozen --all-groups` installs the Python package, but the actual browser binary
  Playwright drives is a separate download (`playwright install --with-deps chromium`) that
  does not come from `uv sync` at all. Discovered live 2026-07-14 — the `api` container's image
  predated this story and could not even start (`ModuleNotFoundError: No module named
  'playwright'` at `CONNECTOR_REGISTRY` import time, since `app/main.py` imports every
  registered connector eagerly), and after rebuilding, a manual `docker exec ... playwright
  install` into the *running* container's writable layer silently stopped working the next time
  the container was recreated (`Executable doesn't exist at
  .../chromium_headless_shell-1228/...`). The runtime stage's `Dockerfile` now runs `playwright
  install --with-deps chromium` at build time instead, so the browser survives container
  recreation the same way the `.venv` copied from the builder stage does — this is the only
  connector with a Dockerfile footprint beyond the shared `uv sync`.

- **Supports Fetch Scope (US47)**: fetch scope is resolved before Chromium is even launched (a
  cheap short-circuit for a run that's going to be blocked anyway). A `"filtered"` resolution
  loops `_collect_offers` once per starred hard skill (`category_filter=term, start_page=1`
  always — filtered runs don't participate in BUG42's `listing_page_cursor` resumption),
  concatenating offers across terms; `listing_page_cursor` is only persisted on the unfiltered
  path. See
  [Ingestion pipeline: Connector fetch scope](../ingestion.md#connector-fetch-scope-all-offers-vs-filtered-by-hard-skills-us47).

