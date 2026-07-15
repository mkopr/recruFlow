# Rocket Jobs connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### Rocket Jobs connector (P3US40)

- **Purpose**: the third of the six connectors P3US37 queued back-to-back
  (P3US38-44, Bulldogjob through WeWorkRemotely), and the next one after P3US38 to reuse its
  "sitemap enumeration + per-URL embedded-structured-data" two-phase-fetch pattern rather than
  the base class's cursor loop — P3US39 (The Protocol) sits between the two in the queue but
  stopped at a feasibility spike (Cloudflare Managed Challenge), so no connector code exists
  for it.

- **Shared-platform relationship with JustJoin.it**: Rocket Jobs's homepage config exposes
  `baseVtApiUrl: https://tracker.justjoin.it` for analytics, and its own sitemap URL redirects
  through a `public.justjoin.com`-hosted path — the two are sibling products on the same
  underlying platform. They are still ingested as two fully independent connectors, the same
  way JustJoin.it and NoFluffJobs already are despite any shared ancestry.

- **Why the obvious approach (a direct API call) is deliberately not used** (investigated live
  2026-07-13, see
  `docs/adr/0025-rocket-jobs-sitemap-and-json-ld-investigation.md` for the full trail): the
  homepage is a client-rendered SPA with no embedded data in the initial HTML, backed by a real
  API at `https://api.rocketjobs.pl`. Unlike the JustJoin.it/NoFluffJobs precedent (OD-4),
  `api.rocketjobs.pl`'s own `robots.txt` explicitly disallows `/` for all user-agents (bar a
  short marketing-page allowlist that excludes the offers endpoint) — a real operator "don't
  crawl this" signal, not just an unmapped guess. `RocketJobsConnector` never calls this host;
  its class docstring names it explicitly so a future contributor doesn't casually "simplify"
  the connector into a direct API call. What does work, and is robots.txt-sanctioned: the
  separate `rocketjobs.pl` frontend host publishes its own complete sitemap
  (`https://rocketjobs.pl/sitemaps/active-jobs.xml`), which resolves through a redirect chain
  to `part0.xml` — 13,387 live job URLs, confirmed live 2026-07-13 — and each job detail page
  embeds a standard `schema.org JobPosting` block as `<script type="application/ld+json">`, an
  SEO-oriented data block, not tied to any particular frontend framework the way Bulldogjob's
  `__NEXT_DATA__` is.

- **Two-phase fetch, not cursor pagination**: `RocketJobsConnector`
  (`app/connectors/rocket_jobs.py`) overrides both `fetch_page` and `run`, mirroring
  `BulldogjobConnector` exactly — `next_cursor` always returns `None`, `run()` calls
  `fetch_sitemap_urls()` once, then hands `run_paginated_ingestion` a closure that treats
  `page_size`/`max_pages` as "how many sitemap URLs to live-fetch per chunk / per run" —
  fallback defaults `page_size=20`, `max_pages=50` (the same as Bulldogjob) bound total live
  per-run HTTP traffic to `page_size * max_pages = 1000` fetches; against the 13,387-URL
  catalog observed live, a full crawl spans roughly 14 runs, which `already_seen_stop_threshold`
  makes cheap once caught up (each subsequent run's early pages are mostly-already-seen and
  stop quickly, rather than re-walking the whole catalog every run).

- **Sitemap-walking is a shared helper, not a duplicate**: `_parse_sitemap_locs` (previously
  private to `bulldogjob.py`) was extracted into `app/connectors/sitemap.py` during this story,
  with no behavior change, and both `BulldogjobConnector.fetch_sitemap_urls` and
  `RocketJobsConnector.fetch_sitemap_urls` import it from there. `RocketJobsConnector`'s own
  `fetch_sitemap_urls` handles both sitemap shapes the redirect chain could resolve to: a
  `<urlset>` directly (today's observed shape, after following the redirect through
  `public.justjoin.com`) or a `<sitemapindex>` requiring a second hop per `<sitemap><loc>` entry
  (handled defensively in case the site later splits the sitemap into multiple parts, per the
  story's own acceptance criteria) — URLs from every part are deduplicated before being
  returned. Fetching uses a new `fetch_text` (`app/connectors/http.py`), the plain-text sibling
  to `fetch_gzip_xml` (Rocket Jobs's sitemap, unlike Bulldogjob's, is not gzip-compressed), with
  `follow_redirects=True` explicit since httpx defaults to not following redirects and the
  sitemap URL itself is a redirect chain. `_fetch_detail_html` also passes
  `follow_redirects=True` for the same reason — a live scheduler run during manual verification
  (2026-07-14) found some sitemap-listed detail URLs 308-redirect to a canonicalized path, which
  without this would have been mistaken for broken detail pages and skipped.

- **`extract_job_posting_json_ld` (module-level function in `rocket_jobs.py`, independently
  unit-testable)** — unlike Bulldogjob's single `__NEXT_DATA__` script match, a page can embed
  more than one `<script type="application/ld+json">` block (breadcrumbs, organization data,
  ...), so every match is `json.loads`'d and inspected for `"@type": "JobPosting"` (also
  unwrapping a `"@graph"`-wrapped block), returning the first match found; one malformed block
  is skipped rather than sinking the whole page, exactly like a single broken Bulldogjob detail
  URL doesn't fail its chunk. Logs `"Rocket Jobs returned unexpected page shape"` (matching
  every other connector's failure-logging convention) when no script tag is present at all, or
  none of the parsed blocks is a `JobPosting`.

- **Raw payload = the parsed `JobPosting` JSON-LD dict plus one provenance key, not the HTML**:
  a live sample of six real detail pages during implementation (2026-07-14) found the JSON-LD
  block never carries a `url` key at all — contradicting the story's own Background, which
  listed `url` alongside `title`/`description`/etc. as if it were a normal field. Since
  schema.org `JobPosting` also has no separate id field (unlike Bulldogjob's `job.id`),
  `fetch_page`'s closure sets a `_source_url` key on the parsed dict (the exact URL the page was
  fetched from) before appending it to the offers list — additive provenance metadata, not a
  fabricated value, and persisted as part of `raw_payload` alongside the untouched JSON-LD
  fields, the same "store what was fetched" posture Bulldogjob's `raw_payload` has, just with
  one field added to make `canonical_url` possible at all. See
  `docs/adr/0025-rocket-jobs-sitemap-and-json-ld-investigation.md`.

- **`map_offer` field mapping** (`app/connectors/rocket_jobs.py`): `title` ← `title`, `company`
  ← `hiringOrganization.name`, `location` ← `jobLocation.address.addressLocality` (schema.org
  `PostalAddress` shape, joined across multiple `jobLocation` entries the same way Bulldogjob's
  `_join_locations` joins cities), `canonical_url` ← the JSON-LD's own `url` field if ever
  present, falling back to `_source_url` (in practice, always the fallback, per the finding
  above), `contract_type` ← `employmentType` (a schema.org standard string, e.g. `FULL_TIME`),
  `posted_at` ← `datePosted`, `description` ← `description`. `external_id` is derived from
  `canonical_url`'s own path segment. `remote` ← `jobLocationType`, mapped through a new
  `_REMOTE_STRING_VOCAB[ROCKET_JOBS] = {"telecommute": True}` entry — schema.org's own standard
  value for a remote posting, confirmed live on a real automatic scheduler run during manual
  verification (2026-07-14, present on some but not all postings, matching schema.org's spec for
  the field). `baseSalary`, seniority, and tech tags were confirmed absent across every sampled
  page — per the project's missing-field conservatism, neither is guessed: `seniority`/salary
  are still fed through `normalize_seniority`/`normalize_salary` exactly as the other four
  connectors are, but `normalize.py` gets no `_SENIORITY_VOCAB[ROCKET_JOBS]` entry, since no
  real observed value exists yet to build one from — the story's own Testing table calls out a
  ~30-page manual field-presence survey as a follow-up, not solved by this story.

- **Registered in `CONNECTOR_REGISTRY`** (`app/ingestion/registry.py`) as `ROCKET_JOBS =
  "rocket_jobs"`, constructed once at import time like the other four — no scheduler, matcher,
  or frontend edit was needed, the same P3US37 "adding a connector" checklist outcome Bulldogjob
  already confirmed.

