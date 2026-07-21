# CONNECTOR_REGISTRY is the single source of truth for connector existence

**Context**: Before this ADR, adding a connector meant hand-editing six places — a new connector
module, `normalize.py`, `registry.py`, `scheduler/service.py`'s `DEFAULT_SOURCE_CONFIGS`,
`llm/matcher.py`'s `LANGCHAIN_SOURCES`, and five frontend call sites — with no compiler or test
catching an omission. The one failure already observed in this project: a connector missing from
`LANGCHAIN_SOURCES` ingests successfully but is never scored, with no error anywhere (fixed once
already for SOLID.Jobs in an earlier change, see below).

**Decision**: `CONNECTOR_REGISTRY: dict[str, ConnectorSpec]` becomes the one place a connector is
declared to exist. Everything else derives from it: `ensure_sources_exist` seeds every registry
key with one shared default config template (replacing three near-duplicated
`DEFAULT_SOURCE_CONFIGS` entries); `LANGCHAIN_SOURCES = frozenset(CONNECTOR_REGISTRY.keys())`;
`GET /connectors` serves the frontend's connector list, replacing the hand-maintained
`KNOWN_SOURCES` constant.

**A real assumption this bakes in**: every registered connector is scored by the LangChain
Matcher — there is no other engine. This is not a new constraint invented by this ADR; an earlier
change already retired the originally-planned second scoring engine (`sjctl evaluate`,
SOLID.Jobs-only) and made LangChain cover all three sources (see `docs/architecture/matching.md`).
This ADR removes the last traces of the abandoned two-engine plan — the dead `"sjctl"`
`MatchEngine` literal and CLAUDE.md's stale wording — and makes the single-engine reality
structural instead of incidental. If a connector ever needs a different scoring engine, deriving
`LANGCHAIN_SOURCES` straight from the registry's keys would need revisiting (e.g. giving
`ConnectorSpec` its own engine field) — deliberately deferred rather than solved speculatively now,
since no such connector exists or is currently planned.

**Consequences**: Adding a connector becomes a 2-step checklist — write the `JobBoardConnector`
subclass, add one `CONNECTOR_REGISTRY` entry. Scheduler seeding, matching eligibility, and every
frontend list pick it up automatically; there is nothing left to silently miss.

**Follow-up (2026-07-15)**: two things this ADR didn't fully close regrew outside the
registry as later connectors were added, and were fixed in a follow-up change. First, `scheduler/service.py` grew its own
`_connector_config_overrides` `if connector == X` branching ladder for Pracuj/RemoteOK/Remotive's
seed defaults — the exact "hand-editing an outside-the-registry place" pattern this ADR set out
to eliminate, just reintroduced one layer down instead of at the connector-existence level this
ADR covers. `ConnectorSpec` now carries a `seed_config_overrides` field so these defaults travel
with the registry entry itself. Second, `registry.py` itself restated every connector's display
`label` as an independent string literal alongside its `dispatch`, a second source of truth for a
value each connector's own `.name` attribute already held — labels are now derived from the
connector instance (`label=<instance>.name`), mirroring this ADR's own
`LANGCHAIN_SOURCES = frozenset(CONNECTOR_REGISTRY.keys())` derivation. The "2-step checklist" in
Consequences still holds; both fixes make more of what a connector needs live inside those two
steps rather than requiring a third, unlisted edit.
