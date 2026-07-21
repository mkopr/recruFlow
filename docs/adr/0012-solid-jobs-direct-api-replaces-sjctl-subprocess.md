# SOLID.Jobs connector calls its direct public HTTP API, not the sjctl subprocess

The vendor confirmed `sjctl` is itself a thin wrapper over a public, key-less HTTP
endpoint — `GET https://solid.jobs/public-api/offers/{division}`, `division` a URL path segment
(`IT`/`Engineering`/`Marketing`/`Sales`/`HR`/`Logistics`/`Finances`/`Other`). Once that's true,
SOLID.Jobs is no longer "genuinely different" from JustJoin.it/NoFluffJobs (the stated reason
for leaving it alone previously) — it's the third source that calls `fetch_json` like its two siblings.
`app/connectors/solid_jobs.py` now does exactly that: `build_offer_url`/`build_offer_params`
replace `build_search_args`/`build_sync_args`, `_fetch_solid_jobs_json` replaces `_run_sjctl`, and
`_extract_offers` collapses to a single envelope shape instead of the sync/search split. This
closes the loop that earlier work started: all three connectors now share one transport, one
failure-handling shape, and one test style. The subprocess boundary, the sjctl watch
state-management problem that caused the original "Fetch now" bug (see
[ADR 0008](0008-manual-fetch-forces-refresh-scheduled-run-does-not.md)), the Docker image's
`curl | bash` sjctl installer (signature verification disabled), and ADR 0001/ADR 0002's
sync/search distinction are all removed, not just relocated.

**Query-param contract**, confirmed 2026-07-05 by live requests against the production endpoint
(not just vendor docs): `campaign` (required, same value as the old `Settings.sjctl_campaign`,
renamed `solid_jobs_campaign`), `pageIndex`/`pageSize`, `sortActive=validFrom`&`sortDirection=desc`
(always set — this is the pagination precondition, see below), and optional
`search.cities`/`search.experiences`/`search.searchTerm` (comma-joined strings, per
`build_offer_params`) plus `search.minimumSalary` (int). No auth, no API key. An optional
`X-Api-Version: 1.0` header is pinned explicitly on every request (none of the three connectors
previously pinned an API version) for stability against future default-version bumps.

**Response envelope — resolved, not the two shapes originally guessed.** A live request
(`GET .../offers/IT?campaign=recruflow&pageIndex=0&pageSize=3&...`) returned
`{"jobs": [...], "pageIndex": 0, "pageSize": 3, "totalCount": 1590, "totalPages": 530}` — the same
`"jobs"` envelope key sjctl's own `search --json` subcommand used (see ADR 0002), not `"results"`
or `"data"` as originally speculated before this ticket had live access. `_extract_offers` is
written against this confirmed shape; a bare list is still accepted defensively (mirrors the other
two connectors' extractors) but no fallback envelope key is needed since the real shape is known.

**Offer field shape** matches `map_sjctl_offer`'s existing mapping almost field-for-field (as the
bug file predicted): `jobOfferKey`, `url`, `title`, `company`, `locations: string[]`, `isRemote`,
`isHybrid`, `experienceLevel`, `salary: {from, to, currency, employmentType}`, `contractTime`,
`validFrom`, `description`. `map_solid_jobs_offer` is a rename of `map_sjctl_offer` with no field
changes.

**Pagination and `force_refresh` semantics: JustJoin.it's early-stop model, not NoFluffJobs'
no-op.** `sortActive=validFrom&sortDirection=desc` gives the same newest-first precondition
JustJoin.it's endpoint relies on (ADR 0009) — pages are requested with `pageIndex`/`pageSize`
instead of a cursor, and "fewer offers returned than `pageSize`" is the end-of-results signal (no
cursor/next-page field exists in the response to say so directly). `run_solid_jobs_ingestion` now
interleaves fetch-then-persist per page and stops early once `already_seen_stop_threshold`
consecutive already-seen offers accumulate — exactly `run_justjoinit_ingestion`'s shape.
`force_refresh=True` bypasses that checkpoint (ADR 0010's model), replacing the old
sync-vs-search subcommand switch entirely. The sjctl watch-scoped "sync" concept (a saved search
synced periodically) does not exist in the direct API and is dropped along with it — there was
never a "watch" resource in the direct API to preserve.

**Discovered discrepancy, not fixed in this ticket**: live testing found `search.experiences`
rejects multi-value input — both comma-joined (`"Senior,Expert"`) and repeated
(`search.experiences=Senior&search.experiences=Expert`) return `400` ("The value '...' is not
valid."), and only `Senior`/`Regular`/`Junior` were accepted as single values in testing
(`Expert`/`Mid`/`Lead`/`Manager` all 400'd). This contradicts the vendor's own doc, which lists
`search.experiences` as `string[]`. `build_offer_params` still comma-joins per this ADR's stated
contract and per the existing "`config_json` is already-validated-at-write-time, not user input,
so build functions do no validation of these values" convention (carried over from
`build_search_args`) — a caller who configures more than one `experience_levels` entry will get a
`400` from the live API, not a client-side rejection. Fixing this (e.g. issuing one request per
experience level and merging results) is out of scope for this bug and is left as an open
follow-up if a future story needs multi-experience-level filtering. `search.cities` was confirmed
live to accept comma-joined multi-value filtering correctly (filtered `totalCount` from 1590 to
990 across two cities in one request).

**Superseded**: this ADR supersedes
[ADR 0001](0001-solid-jobs-sync-vs-search-cache-strategy.md) and
[ADR 0002](0002-sjctl-contract-verified-against-live-binary.md) — their sync/search subcommand
distinction and sjctl v0.3.0 field-verification no longer describe current behavior. Both files are
kept for history, not deleted.

**Explicitly out of scope for this ADR/ticket** (do not read the sections below as touched by
this story):

- `app/config.py`'s other settings — only `sjctl_campaign` → `solid_jobs_campaign` changed.
- `.claude/skills/jobs-track`, `jobs-evaluate`, `jobs-create-profile` — these wrap different sjctl
  subcommands (`track`/`evaluate`/`profile`) entirely unrelated to offer ingestion, and are
  vendored upstream copies per README.md's own "these are vendored copies... to update them,
  re-copy from the source repo" statement — not owned by this connector story.
- `.claude/skills/jobs-search` and `jobs-digest` — these invoke `sjctl search`/`sync` directly as a
  standalone interactive CLI workflow orchestrated by a Claude Code skill, a separate code path
  from `app/connectors/solid_jobs.py` that this bug never touched.
- CLAUDE.md's Phase 2/Phase 3 roadmap mentions of "sjctl sync"/"sjctl evaluate wrapper" — these
  name future work on unrelated sjctl subcommands (candidate-profile sync, offer evaluation), not
  the ingestion connector this story rewrites.
