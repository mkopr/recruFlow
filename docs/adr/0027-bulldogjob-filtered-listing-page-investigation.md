# Bulldogjob: the skills-filtered listing page reuses the same `__NEXT_DATA__` shape as the general catalog, but its pagination is client-side only, capping a plain-request filtered fetch at one page per term

US47 needed to confirm, before writing `BulldogjobConnector.fetch_filtered_sitemap_urls`, whether
`bulldogjob.com/companies/jobs/s/skills,<Term>` (the one comparative `totalCount` curl check the
story's own research had already done) is a real, walkable listing or just a `totalCount` preview
with no further plain-request affordance — continuing the same "confirm every candidate against
the live site with `curl` before trusting it" discipline `docs/adr/0023` established for this
connector's sitemap approach.

**The filtered listing page is a real Next.js page, not a redirect or client-only shell.**
`GET https://bulldogjob.com/companies/jobs/s/skills,Python` returns `200` with an embedded
`<script id="__NEXT_DATA__">` blob, same as every other page on this site. Its
`props.pageProps` carries `totalCount` (`306` for `skills,Python`, confirmed live 2026-07-15),
`slugState` (`{page, perPage, filters, order}`), and — the useful part — `jobs`: a list of **job
summary** records (id, company, position, city, experienceLevel, technologyTags, a
`denominatedSalaryLong` block, `remote`, `contractB2b`/`contractEmployment`/`contractOther`), 50
of them on this sample. Skill matching is case-insensitive server-side
(`skills,python` and `skills,Python` both returned `totalCount: 306`), and a term with no matches
returns a clean `200` with `totalCount: 0, jobs: []` — not an error.

**Pagination is entirely client-side, exactly like the general `/companies/jobs` listing
(`docs/adr/0023`).** Both `?page=2` and `?perPage=100` are silently ignored by the server-rendered
page: `slugState` always reports back `{"page": 1, "perPage": 50}` regardless of what was
requested, and the embedded `jobs` list is byte-identical to the unparameterized request. The
`_next/data/<buildId>/companies/jobs/s/skills,<Term>.json` shortcut — the same one ADR 0023 ruled
out for the general path — 404s here too. There is no plain-request way to reach a filtered
term's second page; the real "next page" affordance is a client-side GraphQL/Apollo call, same
conclusion as ADR 0023, now confirmed for the filtered path specifically too.

**Consequence, and the scope decision this drives:** a plain-request filtered fetch is capped at
the first page — up to 50 job summaries — per hard-skill term, regardless of `totalCount`. This
is a deliberate, documented limitation, same category as ADR 0023's un-parsed free-text-salary
gap: Fetch Scope's "filtered" mode exists specifically to issue *fewer* requests and accept
*reduced recall* in exchange (US47's whole premise), so a per-term 50-offer cap is consistent with
the feature's own intent rather than a defect to work around. It also means filtered runs don't
need `SitemapDetailPageConnector`'s `sitemap_cursor` resumption machinery (BUG41) at all — there
is only ever one page to fetch, not a large stable catalog to walk incrementally — which is why
`_run_over_urls` is called with `persist_cursor=False` from the filtered path.

**No second per-job detail fetch shape was needed, but a detail fetch is still required.** Each
listing summary's `id` field is already the full `<numeric-id>-<slug>` string — the exact same
value and source as a job detail page's own `job.id` (ADR 0023) — so
`fetch_filtered_sitemap_urls` builds detail URLs directly as
`https://bulldogjob.com/companies/jobs/{id}`, with no separate slug lookup, identical in shape to
`fetch_sitemap_urls`'s sitemap-derived URLs. A detail fetch through the existing
`extract_next_data`/`map_offer` machinery is still necessary despite this, because the listing
summary itself lacks `description` (`offer`/`requirements`), the full `employmentSalary`/
`b2bSalary`/`otherSalary` breakdown, and `publishedAt` — exactly the fields ADR 0023 already
established only the detail page's `__NEXT_DATA__` carries.

**Implementation:** `fetch_filtered_sitemap_urls(config, term)` fetches
`bulldogjob.com/companies/jobs/s/skills,{quote(term, safe="")}` via the same
`_fetch_detail_html`/`extract_next_data` helpers `fetch_sitemap_urls` already uses, reads
`props.pageProps.jobs`, and maps each entry's `id` to a detail URL. Returns `[]` (not `None`) for
a genuine zero-match term — confirmed live to be a normal `200` response, not a failure — and
`None` only on an actual fetch failure or unexpected page shape, matching
`SitemapDetailPageConnector`'s existing `fetch_sitemap_urls` contract.

If Bulldogjob changes this page's shape, re-run the same `curl`-and-parse checks documented here
against `bulldogjob.com/companies/jobs/s/skills,<Term>` before touching
`fetch_filtered_sitemap_urls`. A browser DevTools capture of the real client-side pagination call
(not attempted here, same sandboxed-headless-Chromium limitation as ADR 0023) could reveal a way
to walk past page 1 for a popular skill term in the future, but is not required for this story.
