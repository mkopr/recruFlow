# Connectors

[Architecture index](../../ARCHITECTURE.md)

Each job board integration is a `JobBoardConnector` subclass + a `ConnectorSpec` entry in
`CONNECTOR_REGISTRY` (`app/ingestion/registry.py`). Adding a new connector should require zero
edits to the scheduler, matcher, or frontend — see
[Ingestion pipeline: Connector extensibility + stop/start toggle](ingestion.md) and
[Ingestion pipeline: connector architecture cleanup](ingestion.md) for the shared registry pattern, and
[Ingestion pipeline: Cross-connector schema consistency](ingestion.md) for the shared mapping
contract every connector below follows.

- [SOLID.Jobs](connectors/solid-jobs.md) — direct HTTP API; supports Fetch Scope
- [JustJoin.it](connectors/justjoinit.md) — direct HTTP API
- [NoFluffJobs](connectors/nofluffjobs.md) — direct HTTP API
- [Bulldogjob](connectors/bulldogjob.md) — sitemap + embedded `NEXT_DATA`; supports Fetch Scope (`docs/adr/0027`)
- [Rocket Jobs](connectors/rocket-jobs.md) — sitemap + JSON-LD
- [Pracuj.pl](connectors/pracuj.md) — Playwright (Cloudflare-gated), listing-page enumeration; supports Fetch Scope
- [RemoteOK](connectors/remoteok.md) — direct API, no pagination
- [Remotive](connectors/remotive.md) — direct API, per-category fetch
- [We Work Remotely](connectors/we-work-remotely.md) — RSS only
- [The Protocol](connectors/the-protocol-spike-failed.md) — spike failed, not implemented (Cloudflare Managed Challenge)
