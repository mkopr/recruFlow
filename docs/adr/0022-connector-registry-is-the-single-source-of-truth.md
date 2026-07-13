# CONNECTOR_REGISTRY is the single source of truth for connector existence

**Context**: Before P3US37, adding a connector meant hand-editing six places — a new connector
module, `normalize.py`, `registry.py`, `scheduler/service.py`'s `DEFAULT_SOURCE_CONFIGS`,
`llm/matcher.py`'s `LANGCHAIN_SOURCES`, and five frontend call sites — with no compiler or test
catching an omission. The one failure already observed in this project: a connector missing from
`LANGCHAIN_SOURCES` ingests successfully but is never scored, with no error anywhere (fixed once
already for SOLID.Jobs by P3US23, see below).

**Decision**: `CONNECTOR_REGISTRY: dict[str, ConnectorSpec]` becomes the one place a connector is
declared to exist. Everything else derives from it: `ensure_sources_exist` seeds every registry
key with one shared default config template (replacing three near-duplicated
`DEFAULT_SOURCE_CONFIGS` entries); `LANGCHAIN_SOURCES = frozenset(CONNECTOR_REGISTRY.keys())`;
`GET /connectors` serves the frontend's connector list, replacing the hand-maintained
`KNOWN_SOURCES` constant.

**A real assumption this bakes in**: every registered connector is scored by the LangChain
Matcher — there is no other engine. This is not a new constraint invented by this ADR; P3US23/US24
already retired the originally-planned second scoring engine (`sjctl evaluate`, SOLID.Jobs-only)
and made LangChain cover all three sources (see ARCHITECTURE.md's P3US23 section). P3US37 removes
the last traces of the abandoned two-engine plan — the dead `"sjctl"` `MatchEngine` literal and
CLAUDE.md's stale wording — and makes the single-engine reality structural instead of incidental.
If a connector ever needs a different scoring engine, deriving `LANGCHAIN_SOURCES` straight from
the registry's keys would need revisiting (e.g. giving `ConnectorSpec` its own engine field) —
deliberately deferred rather than solved speculatively now, since no such connector exists or is
planned in P3US38-44.

**Consequences**: Adding a connector becomes a 2-step checklist — write the `JobBoardConnector`
subclass, add one `CONNECTOR_REGISTRY` entry. Scheduler seeding, matching eligibility, and every
frontend list pick it up automatically; there is nothing left to silently miss.
