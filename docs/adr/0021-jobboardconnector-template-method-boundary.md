# JobBoardConnector's abstract/hook/fixed-method boundary

**Context**: SOLID.Jobs, JustJoin.it, and NoFluffJobs each duplicated the same fetch → extract →
paginate scaffolding across three separate modules, and six more connectors were
queued to repeat it a fourth through ninth time with nothing catching a missed step — the worst
failure already seen in practice was a connector never added to `LANGCHAIN_SOURCES`: ingestion
succeeds, scoring silently never happens, forever.

**Decision**: `JobBoardConnector` (`app/connectors/base.py`) splits into three tiers, not two:

- **Abstract** (`default_url`, `build_params`, `next_cursor`, `map_offer`) — the pieces that
  encode what's structurally different about each job board's API: URL, request shape,
  pagination signal, response shape. No sensible default exists, so every subclass must supply
  them.
- **Hooks** (`build_url`, `envelope_key`/`extract_offers`, `build_headers`, `runner_kwargs`) —
  sensible defaults are provided, but a connector may need a per-API twist: SOLID.Jobs's static
  `X-Api-Version` header, JustJoin.it's rate-limit delay, NoFluffJobs's hardcoded single-page
  pagination and non-bare-list envelope extraction.
- **Fixed** (`fetch_page`, `run`) — never overridden. These exist specifically so a subclass
  *cannot* reimplement the fetch → extract → log-on-failure → next-cursor loop or the
  config-read → dispatch-to-`run_paginated_ingestion` wiring, which must stay byte-identical
  across every connector.

**Alternative considered**: a single declarative, config-driven connector (URL templates,
JSONPath-style envelope keys, no subclassing at all). Rejected — NoFluffJobs's no-pagination
quirk and JustJoin.it's rate limiting aren't expressible as pure data without still needing
per-connector code somewhere; a thin Python subclass costs the same as a config schema flexible
enough to cover those cases, but keeps type-checking and IDE navigation.

**Consequences**: each of the six later connectors implements exactly one connector file, overriding the 4 abstract
methods and a hook only when their API genuinely needs it — no other file changes required for a
"vanilla" connector.

**Follow-up (2026-07-15)**: this ADR's "no other file changes required" prediction held for
7 of 9 connectors, but Bulldogjob and Rocket Jobs turned out to need a genuine
escape hatch — no cursor-paginated endpoint exists for either, so both overrode the fixed
`fetch_page`/`run` methods this ADR says should never be overridden, and ended up ~90%
duplicated with each other in the process. A follow-up change added a second inheritance tier,
`SitemapDetailPageConnector` (`app/connectors/sitemap_detail.py`), between `JobBoardConnector`
and these two connectors: it re-fixes `run()` around the sitemap-enumeration/per-URL-detail-fetch
shape those two connectors share, so the original boundary's spirit — "the parts that must stay
identical across connectors of the same shape are fixed, not reimplemented per connector" —
still holds, just one level down. A 10th connector needing this same shape now costs one file
implementing 3 hooks, not a copy-paste from Bulldogjob or Rocket Jobs.
