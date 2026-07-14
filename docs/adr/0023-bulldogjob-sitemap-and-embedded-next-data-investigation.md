# Bulldogjob: no public API, but its own sitemap plus embedded `__NEXT_DATA__` JSON gives a complete, unauthenticated offer feed

P3US38 needed to resolve Bulldogjob's equivalent of OD-4 (does a JSON endpoint exist behind the
SPA, or does ingestion require a Playwright scraper?), continuing the investigation discipline
`docs/adr/0003-justjoinit-json-endpoint-investigation.md` and
`docs/adr/0004-nofluffjobs-json-endpoint-investigation.md` established: guess candidate URLs from
the site's own served bundle/config, then confirm every candidate against the live site with
`curl` before trusting it. Unlike JustJoin.it and NoFluffJobs, this investigation did not turn up
a JSON API endpoint at all — Bulldogjob's real data source is a GraphQL/Apollo backend the SSR
Next.js frontend calls server-side, not something reachable with a plain `curl`.

**The listing page's pagination is broken from a plain-request client.** `GET
https://bulldogjob.com/companies/jobs?page=2` returns `200`, but the page's own embedded
`__NEXT_DATA__.props.pageProps.slugState.page` is still `1`, and the job list is byte-identical to
`?page=1` — the site's real "next page" affordance is a client-side action (almost certainly a
POST/GraphQL call triggered by JS), not observable from a plain GET. The Next.js
client-navigation data route (`_next/data/<buildId>/companies/jobs.json`, the shortcut that
worked for neither JustJoin.it nor NoFluffJobs either, for different reasons) also 404s here.

**`robots.txt` (fetched directly) does not block the path that does work.** It disallows
`/page`, `/feeds`, `/account`, `/auth`, `/faq`, `/index`, and a few filter paths — none of which
this connector touches. It does not disallow `/sitemap*` or `/companies/jobs/<id>`.

**The working, unauthenticated, complete-in-one-pass approach:**

```
GET https://bulldogjob.com/sitemap.en.xml.gz        -> sitemap index (gzip XML)
  -> sub-sitemap <loc>https://bulldogjob.com/en/jobs.xml.gz</loc>
GET https://bulldogjob.com/en/jobs.xml.gz            -> gzip XML urlset, ~1000 <loc> entries
GET <each job's own /companies/jobs/<id>-<slug> URL>  -> HTML with embedded __NEXT_DATA__ JSON
```

Confirmed live 2026-07-13: `curl -A "recruFlow/0.1" "https://bulldogjob.com/sitemap.en.xml.gz"`
returns a gzip sitemap index with four sub-sitemaps (`etc`, `jobs`, `companies`, `readme`); the
`jobs` one gunzips to 993 `<loc>` entries. Every job detail page (e.g.
`https://bulldogjob.com/companies/jobs/243779-java-technical-leader-warsaw-devire`) embeds a
`<script id="__NEXT_DATA__" type="application/json">` tag whose
`props.pageProps.data.job` is a complete, structured GraphQL-shaped record — not an HTML
fragment to scrape, the same "parse embedded JSON" ELT step the other three connectors' JSON
endpoints already are, just delivered via an HTML response.

**Two findings not anticipated by the story's own Background section, both confirmed by fetching
and parsing real pages rather than guessing field names:**

1. `jobs.xml.gz` is not purely job detail URLs. ~5% of its entries (54 of 993 sampled) are
   filter/tag listing pages (`/companies/jobs/s/skills,Java`, `/companies/jobs/s/role,qa`, ...)
   that share the site's Next.js `__NEXT_DATA__` shape but carry no `job` record.
   `fetch_sitemap_urls` filters to the `/companies/jobs/<digits>-` pattern before returning, so
   these never reach a live per-URL detail fetch.
2. Structured salary fields (`employmentSalary`/`b2bSalary`/`otherSalary`, each with
   `minValue`/`maxValue`) are populated as `null` on nearly every sampled listing; the only
   populated salary signal is a free-text range string (`money`, e.g. `"180 - 200"`) paired with
   a `timeframe` (`hour`/`month`/`year`) that varies per listing. `map_offer` does not attempt to
   parse this text into `salary_min`/`salary_max` — mixing unconverted hourly/monthly/yearly
   figures into one numeric field would silently corrupt scoring input, which is worse than
   leaving the field `None`. This is a known, documented limitation, same category as
   NoFluffJobs's own "no full description" gap (ADR 0004).

**Field shapes confirmed live** (used to build `app/connectors/bulldogjob.py`'s test fixtures):
`job.id` is the full `<numeric-id>-<slug>` string (also the canonical URL's own path segment, so
no separate slug lookup is needed); `job.remote` is a plain boolean (unlike JustJoin.it's string
enum); `job.experienceLevel` takes values `junior`/`medium`/`senior`/`lead` in sampled listings
(no `expert`/`trainee`/`c-level` observed — `_SENIORITY_VOCAB[BULLDOGJOB]` only maps the four
confirmed values); `job.locations` is a list of `{location: {cityEn, cityPl, ...}}` (occasionally
with a `null` `location`, handled defensively); `job.publishedAt` is an ISO 8601 string with a
timezone offset; `job.offer` (benefits) and `job.requirements` (responsibilities + requirements)
are HTML strings, concatenated into `description` when present — richer than either JustJoin.it
or NoFluffJobs, whose listing-only payloads carry no full posting body at all.

If Bulldogjob changes its site, `_parse_sitemap_locs`, `extract_next_data`, and `map_offer` in
`app/connectors/bulldogjob.py` are the places to re-verify — re-fetch
`sitemap.en.xml.gz`/`en/jobs.xml.gz` and re-inspect a live detail page's `__NEXT_DATA__` shape
with the same `curl`-and-parse method documented here. A browser DevTools network capture (not
attempted in this investigation, consistent with ADR 0003/0004's own sandboxed-headless-Chromium
limitation) could still reveal Bulldogjob's real client-side "next page" GraphQL call, which would
let a future revision supersede the sitemap-enumeration approach with true cursor pagination — not
required for this story, since the sitemap approach is already complete and
`robots.txt`-compliant on its own.
