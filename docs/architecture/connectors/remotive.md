# Remotive connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### Remotive connector (P3US43)

- **Purpose**: a genuine, confirmed, public, unauthenticated JSON API at
  `GET https://remotive.com/api/remote-jobs`, no signup/key, no offset/cursor pagination — the
  same "simplest connector" shape RemoteOK established in ../remoteok.md. The one real structural
  difference: Remotive's `category` query param accepts a single value per call, so
  `RemotiveConnector` fetches once per configured category and merges the results before
  handing off to the shared persist/dedup path, rather than issuing one call per page. This is
  a fetch-shape deviation from `build_params`/`next_cursor`, not from cursor pagination as
  such — the same category of deviation Bulldogjob's own `fetch_page` override already
  documents and normalizes: both `build_params` and `next_cursor` are unused stubs kept only to
  satisfy `JobBoardConnector`'s abstractmethods.

- **`config_json.categories`** (default `("software-development", "devops", "qa", "data")`,
  seeded via `_connector_config_overrides` in `app/scheduler/service.py`, same layering point
  Pracuj.pl's `category_filter` and RemoteOK's interval override use) is meant to scope
  ingestion to IT-relevant categories. **Confirmed live 2026-07-14, this filter currently has
  no effect server-side**: `GET /api/remote-jobs?category=X` returns the identical ~39-job,
  mixed-category response (Software Development, Sales, Marketing, Medical, Product
  Management, ...) for every value of `X` tried, including deliberately invalid ones
  (`nonsense-xyz`) — Remotive's public/free tier appears to ignore the documented `category`
  param entirely (their own API's legal notice mentions a separate paid tier). This is not
  something to work around in this connector: the request is built exactly per the documented
  contract, four lightweight calls per run is cheap regardless, and dedup on canonical URL
  (which already has to handle a job appearing under two *configured* categories) transparently
  absorbs the fact that all four calls currently return the same job set — if Remotive fixes
  server-side filtering later, this connector filters correctly with zero code changes. `qa`
  and `data` and `devops` are real slugs confirmed against `GET /api/remote-jobs/categories`;
  the initial default of `"software-dev"` was wrong (the real slug is
  `"software-development"`) — caught by that same live category-listing check, not by the
  (currently no-op) filter behavior itself.

- **`remote` is hardcoded `True`, never computed**: Remotive is remote-only by construction,
  identical rationale to RemoteOK.

- **Seniority is left unmapped (`None`)**: `category` is a role-family label (Software
  Development, DevOps, ...), not a seniority signal — `normalize.py` gets no
  `_SENIORITY_VOCAB[REMOTIVE]` entry, and `map_offer` never calls `normalize_seniority` at all,
  the same fabrication-risk avoidance RemoteOK's own `tags` field gets. `category` and `tags`
  are merged (deduplicated, order-preserved) into `industry_tags` instead, since that's the
  existing free-text-topical-label field RemoteOK's own `tags` already established.

- **Salary is never parsed from free text**: Remotive's `salary` field is an unstructured
  string (`"$70,000 - $90,000"`, or empty — confirmed live), not a numeric pair. `salary_min`/
  `salary_max` are hardcoded `None`; `normalize_salary` is still called (with `"USD"` passed
  explicitly, same reasoning as RemoteOK's own currency default override) purely so
  `salary_currency` comes out `"USD"` rather than `normalize_salary`'s own PLN default. The raw
  string survives only in `raw_payload` (ELT, stored unconditionally by `persist_offer`) — no
  regex/heuristic range parsing was attempted, per this project's explicit missing-field
  conservatism (OD-9).

- **`job_type` (e.g. `"full_time"`) is never mapped into `contract_type`**: per CLAUDE.md's
  explicit Contract Type vs. work-time-schedule distinction, a work-time-schedule value like
  full-time/part-time is not the same domain concept as a legal contract form (UoP, B2B), and
  the latter is not derivable from Remotive's payload at all. `contract_type` is hardcoded
  `None`.

- **Live bug found and fixed during manual verification, not caught by any mocked test**:
  Remotive's `publication_date` (e.g. `"2026-07-13T07:05:10"`) carries no timezone suffix,
  unlike every other connector's `posted_at` source field (RemoteOK's `date` has a `Z` suffix;
  NoFluffJobs converts an epoch to a `tz=UTC`-aware `datetime` directly). `map_offer` originally
  passed this string straight through, which crashed every real run of
  `run_paginated_ingestion`'s fetch-range filter (`app/ingestion/runner.py`) with
  `TypeError: can't compare offset-naive and offset-aware datetimes` the moment a `since`/
  `until` bound was set — which every freshly-seeded source has by default (US34's 7-day
  fetch-range seed). A private `_normalize_posted_at` helper in `app/connectors/remotive.py`
  parses the raw string and attaches `UTC` when the parsed value is naive, confirmed live after
  the fix (`fetched: 156, created: 18` on first real run across the four default categories,
  `created: 0` on an immediate rerun against the same window). Every mocked unit/integration
  test in this codebase used a manually-authored `posted_at` fixture and would never have
  caught this — it only surfaced against the real API's actual payload shape, the same category
  of gap Rocket Jobs's and Pracuj.pl's own live-testing writeups already flagged for this
  project.

- **Registered in `CONNECTOR_REGISTRY`** (`app/ingestion/registry.py`) as
  `REMOTIVE = "remotive"`, with no schedule-interval override (unlike RemoteOK/Pracuj.pl) — four
  lightweight GETs per run isn't meaningfully more expensive than the shared 300s default. No
  scheduler, matcher, or frontend edit beyond the registry entry and the `categories` config
  default was needed — automatically scoring-eligible via `LANGCHAIN_SOURCES`
  (`app/llm/matcher.py`) and automatically visible to the frontend via `useKnownSources()`'s
  `GET /connectors` call, confirmed live showing `remotive`/`Remotive` in the connector list
  immediately after registration, with zero `frontend/src/` edit.

- **Market-scope callout** (same note RemoteOK's own section makes): Remotive, like RemoteOK, is
  a global remote-first board, not Poland-specific — this and RemoteOK are recruFlow's first two
  connectors extending ingestion beyond the project's original Poland-only framing.

