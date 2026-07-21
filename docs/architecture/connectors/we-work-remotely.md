# We Work Remotely connector

[Architecture index](../../../ARCHITECTURE.md) · [Connectors overview](../connectors.md)

### We Work Remotely connector

- **Purpose**: the last of the six connectors in the post-Phase-3 batch, and a deliberate "does the
  extensibility investment hold in the opposite direction" test case from its five siblings —
  every other connector in this batch found some JSON path (an API, or an embedded
  `__NEXT_DATA__`/JSON-LD blob); We Work Remotely's only confirmed public source is
  `GET https://weworkremotely.com/remote-jobs.rss`, a plain RSS/XML feed with no cursor.
  `weworkremotely.com/api/v1/remote-jobs/` was checked live 2026-07-15 and confirmed private
  (`401`, `WWW-Authenticate: Token realm="Application"`) — it's the partner/employer-posting API,
  not a public read endpoint.

- **Implements the `Connector` Protocol directly, not `JobBoardConnector`**: `JobBoardConnector`'s
  `fetch_page` is fixed around `fetch_json` plus a cursor (`app/connectors/base.py`); an RSS feed
  is neither JSON nor cursor-paginated (one request always returns the full current live set), so
  it doesn't fit that Template Method's shape. `app/connectors/we_work_remotely.py` instead
  exports a bare async function, `run_we_work_remotely_ingestion`, registered directly as a
  `ConnectorSpec.dispatch` — the same "plain function satisfies the `Connector` Protocol" shape
  every connector had before the class hierarchy was introduced. This is this batch's one
  deliberate exception, called out both in the module's own docstring and with an inline comment
  on its `CONNECTOR_REGISTRY` entry, so a future reader doesn't mistake the asymmetry for
  something the class-hierarchy migration simply forgot to convert.

- **New `fetch_xml` primitive** (`app/connectors/http.py`), the RSS/XML sibling of `fetch_json`:
  same signature shape (`url`, `source_name`, `logger`, `params=None`, `headers=None`,
  `timeout=10.0`), same fail-soft posture (an `httpx.HTTPError` or `xml.etree.ElementTree.ParseError`
  is caught, logged, and turned into `None` — never raised out to the caller). It only fetches and
  parses well-formed-XML-or-not; it knows nothing about RSS `<item>`/`<channel>` shape, exactly
  the same split `fetch_json`/`extract_envelope_list` establish for JSON. That RSS-shape
  validation lives one layer up, in `_extract_rss_items` — `None` means "not RSS-shaped at all" (no
  `<channel>` element), an empty list is a valid, non-error "zero live postings right now" result
  (matches every other connector's empty-result posture), and logging the "which one happened"
  distinction is `fetch_page`'s job, not `_extract_rss_items`'s — the same log-site split
  `JobBoardConnector.fetch_page`'s own "unexpected JSON shape" log already establishes relative to
  `extract_offers`.

- **Company name comes from `<title>`, not `<description>`, overriding the original
  assumption**: live sampling of the real feed 2026-07-15 (100/100 items checked) showed every
  `<title>` is formatted `"Company Name: Job Title"`, with zero exceptions, while `<description>`
  carries no company-identifying line at all — its only consistently structured content is a
  `"Headquarters:"` *location* line and, rarely, a salary line (see below). `_split_company_and_title`
  splits the raw title on the first `": "`; when a title has no such separator (never observed
  live, but not guaranteed), it falls back to `(None, raw_title)` — an empty `company` fails
  `Offer`'s `min_length=1` and routes through the existing `VALIDATION_FAILED` dead-letter path
  with no special-case handling, the same behavior every other connector already has for a
  missing required field.

- **Salary is a rare, best-effort regex parse of `<description>`, not the primary path**: only
  ~1/100 sampled live postings had a parseable compensation line at all, and the one confirmed
  shape is `"Up to USD <amount>"` inside a `<strong>` tag (e.g. `"<strong>Up to USD
  80,000</strong> per year"`) — HTML tags are stripped before matching. `_parse_salary_ceiling`
  intentionally matches only `USD`/`US$`/`$`-prefixed amounts; no other currency was observed live,
  and guessing at an unconfirmed currency would violate this project's missing-field conservatism
  (OD-9) rather than serve it. A per-posting miss returns `None` and logs at `debug` level (never
  `warning`/`error`) — this is an expected, non-fatal per-item gap, not a source-level failure.
  `normalize_salary(WE_WORK_REMOTELY, None, parsed_ceiling, "USD")` is called with an explicit
  `"USD"` override (same reasoning as Remotive's and RemoteOK's own override) so
  `salary_currency` never silently defaults to `normalize_salary`'s own PLN fallback.

- **Canonical URL: `link`, confirmed to currently equal `guid`**: two live polls of the real feed
  a few minutes apart on 2026-07-15 showed `<link>` and `<guid>` byte-identical for all 100 common
  items across both polls — unlike Remotive's separate numeric `id` vs. `url` fields, this feed's
  two candidate identifiers currently carry the same value. A true multi-hour stability diff (a
  suggested cadence for future re-verification) was not performed within this implementation
  session; `link` is used as the stated baseline, and since it's presently identical to `guid`,
  either choice yields the same dedup behavior today. If a future observation shows the two
  fields diverging, this section and `map_offer`'s `canonical_url` line should be revisited
  together.

- **`remote` is hardcoded `True`, never computed**: We Work Remotely is remote-only by
  construction, identical rationale to RemoteOK and Remotive.

- **Seniority and contract type are both hardcoded `None`**: the feed carries no seniority signal
  at all (no `_SENIORITY_VOCAB[WE_WORK_REMOTELY]` entry, `normalize_seniority` is never called —
  same fabrication-risk avoidance as RemoteOK/Remotive). The RSS `<type>` field (observed values
  like `"Full-Time"`/`"Contract"`) is a work-time-schedule/employment-type value, not a legal
  contract form (UoP/B2B) this schema models, per CLAUDE.md's explicit Contract Type distinction —
  identical to how Remotive's `job_type` is never mapped into `contract_type`. `<category>` plus
  the comma-split `<skills>` field are merged (deduplicated, order-preserved) into
  `industry_tags`, the same pattern Remotive's `category`+`tags` merge establishes.

- **Registered in `CONNECTOR_REGISTRY`** as `WE_WORK_REMOTELY = "we_work_remotely"`, with no
  schedule-interval override — a single lightweight RSS GET per run isn't meaningfully more
  expensive than the shared 300s default, the same reasoning Remotive's own unthrottled entry
  uses. No scheduler, matcher, or frontend edit beyond the registry entry was needed —
  automatically scoring-eligible via `LANGCHAIN_SOURCES` and automatically visible to the
  frontend via `useKnownSources()`'s `GET /connectors` call, with zero `frontend/src/` edit — the
  same "adding a connector" outcome the connector extensibility work was built to guarantee.

- **Market-scope callout** (same note RemoteOK's and Remotive's own sections make): We Work
  Remotely, like RemoteOK and Remotive, is a global remote-first board, not Poland-specific.
