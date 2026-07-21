# Rocket Jobs: no usable public API (robots.txt-disallowed), but its own sitemap plus embedded schema.org JSON-LD gives a complete, robots.txt-sanctioned offer feed

Resolving Rocket Jobs's equivalent of OD-4 meant continuing the investigation
discipline `docs/adr/0003-justjoinit-json-endpoint-investigation.md`,
`docs/adr/0004-nofluffjobs-json-endpoint-investigation.md`, and
`docs/adr/0023-bulldogjob-sitemap-and-embedded-next-data-investigation.md` established: guess
candidate URLs from the site's own served bundle/config, then confirm every candidate against
the live site before trusting it.

**Rocket Jobs shares infrastructure with JustJoin.it.** Its homepage config exposes
`baseVtApiUrl: https://tracker.justjoin.it` for analytics, and (as found during this
investigation) its own sitemap URL redirects through a `public.justjoin.com`-hosted path — the
two are sibling products on the same underlying platform, not unrelated boards. This connector
still ingests Rocket Jobs independently, the same way JustJoin.it and NoFluffJobs are two
separate connectors despite any shared ancestry.

**The homepage is a client-rendered SPA with no embedded data in the initial HTML** — no
`__NEXT_DATA__`, `__NUXT__`, or `__APOLLO_STATE__` — unlike Bulldogjob (ADR 0023). Everything
is fetched client-side after load, against a real backend at `https://api.rocketjobs.pl`
(confirmed live: it returns structured JSON errors, not a static 404 page, for both unmapped
and guessed-but-wrong paths under a `/v2/...` prefix).

**`api.rocketjobs.pl`'s own `robots.txt` disallows `/` for all user-agents** (with a short
allowlist of marketing pages: `/sitemap`, `/pricing`, `/login`, `/register`) — a real, explicit
"don't crawl this" signal from the site operator, confirmed 2026-07-13. This is different from
the JustJoin.it/NoFluffJobs precedent (OD-4), where the discovered endpoints had no such
disallow. Guessing the exact offers resource path under `/v2/...` (`offers`, `job-offers`,
`search/offers`, and other plausible names) didn't succeed either, so pursuing this API further
would mean both guessing blind *and* going against a published robots.txt rule. Per this
story's own Domain Decision, `api.rocketjobs.pl` is treated as off-limits, not as a target to
keep probing.

**`rocketjobs.pl` itself (the separate, less restrictive frontend host) publishes a full
sitemap in its own `robots.txt`**: `https://rocketjobs.pl/sitemaps/active-jobs.xml`. Followed
through its redirect chain (confirmed 2026-07-13), it resolves to `part0.xml`, which lists
**13,387 live job URLs** — a complete, pagination-free enumeration, and one the site operator
has explicitly published for crawling (unlike the disallowed API).

**The working, unauthenticated, complete-in-one-pass approach:**

```
GET https://rocketjobs.pl/sitemaps/active-jobs.xml   -> redirect chain (via public.justjoin.com)
  -> part0.xml (urlset, 13,387 <loc> entries; further parts handled if the site later splits it)
GET <each job's own detail page URL>                  -> HTML with an embedded schema.org
                                                           JobPosting JSON-LD block
```

**Each job detail page embeds a `schema.org JobPosting` JSON-LD block** (confirmed 2026-07-13,
`<script type="application/ld+json">`), containing `title`, `description`, `datePosted`,
`validThrough`, `employmentType`, `hiringOrganization` (name + logo + `sameAs` company site),
and `jobLocation` (structured address). This is a standard, structured, SEO-oriented data
block — a normal and expected thing for a crawler to read, not an evasion technique, and (unlike
Bulldogjob's `__NEXT_DATA__`) not tied to any particular frontend framework.

**Fields confirmed absent, sampling six real detail pages during this implementation
(2026-07-14) rather than relying only on the story's own single-page check:** `baseSalary`, a
seniority level (`experienceRequirements`), and tech tags — consistent with the story's own
Background. Per this story's own Domain Decision and the project's missing-field conservatism,
`map_offer` in `app/connectors/rocket_jobs.py` does not fabricate either of these — `seniority`
and salary fields are fed through the shared `normalize_seniority`/`normalize_salary` functions
exactly as-is (raw `None` in, `None` out via their existing fail-open behaviour), and
`normalize.py` gets no `_SENIORITY_VOCAB[ROCKET_JOBS]` entry, since no real value was observed to
build one from.

**`jobLocationType` is a real, confirmed remote-work signal, unlike the six-page sample's own
finding** — a live automatic scheduler run against the full real catalog during manual
verification (2026-07-14, `make up`) surfaced several postings with `jobLocationType:
"TELECOMMUTE"` (schema.org's own standard value for a remote posting), a field absent from the
smaller six-page sample entirely by chance. `_REMOTE_STRING_VOCAB[ROCKET_JOBS]` maps
`"telecommute": True`, the same "add a vocab entry only for a genuinely observed value" posture
`_SENIORITY_VOCAB[BULLDOGJOB]` already follows — just discovered later, against a larger live
sample, than the six-page spot check first suggested. The story's own Testing table calls out a
~30-page manual field-presence survey as a follow-up to confirm salary/seniority/tags more
broadly; the six-page sample plus this larger live run corroborate the story's own single-page
finding for those three fields but do not replace that follow-up.

**A finding the story's own Background did not anticipate:** every sampled page's JSON-LD key
set is exactly `@context`, `@type`, `applicantLocationRequirements`, `datePosted`,
`description`, `employmentType`, `hiringOrganization`, `jobLocation`, `title`, `validThrough` —
never a `url` key, even though the story's Background listed `url` as if it were a normal field
alongside `title`/`description`/etc. Since schema.org `JobPosting` also carries no separate id
field (unlike Bulldogjob's `job.id`), and the sitemap-listed URL is the only place a canonical
identifier for the posting exists at all, `run`'s `fetch_page` closure sets a `_source_url` key
on the parsed dict (the exact URL the page was fetched from) before handing it to `map_offer` —
additive provenance metadata, not a fabricated field value, persisted as part of `raw_payload`
alongside the untouched JSON-LD fields. `map_offer` derives `canonical_url`/`external_id` from
`_source_url`, checking the JSON-LD's own `url` field first only in case a future Rocket Jobs
revision starts populating it. `applicantLocationRequirements` (a country-restriction field, not
a remote-work signal) was also observed on every sampled page but is not mapped to anything.

**Field shapes confirmed live** (used to build `app/connectors/rocket_jobs.py`'s test
fixtures): `jobLocation.address.addressLocality` is the city name (schema.org `PostalAddress`
shape); `hiringOrganization.name` is the company name; `employmentType` is a schema.org
standard string (e.g. `FULL_TIME`); `datePosted` is an ISO 8601 string; `description` is an
HTML string.

**Some sitemap-listed detail URLs 308-redirect to a canonicalized path**, confirmed on the same
live scheduler run — `_fetch_detail_html` now passes `follow_redirects=True` (it didn't
initially; the first live run logged spurious `failed to fetch ... detail page` errors for
otherwise-good, merely-redirected URLs before this was caught and fixed), matching
`fetch_sitemap_urls`'s own `fetch_text` posture.

If Rocket Jobs changes its site, `fetch_sitemap_urls` and `extract_job_posting_json_ld` in
`app/connectors/rocket_jobs.py` (and the shared `_parse_sitemap_locs` in
`app/connectors/sitemap.py`, extracted from Bulldogjob's original implementation during this
story so both connectors share one sitemap-walking helper rather than duplicating it) are the
places to re-verify — re-fetch `sitemaps/active-jobs.xml` and re-inspect a live detail page's
JSON-LD shape with the same fetch-and-parse method documented here.
