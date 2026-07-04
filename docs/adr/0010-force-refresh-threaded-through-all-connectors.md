# force_refresh: given real meaning for JustJoin.it, an honest documented no-op for NoFluffJobs

BUG06: `_dispatch_justjoinit`/`_dispatch_nofluffjobs` accepted `force_refresh: bool` (required by
the shared `Connector` protocol) and then never referenced it — `run_justjoinit_ingestion`/
`run_nofluffjobs_ingestion` didn't even accept the parameter. Only `_dispatch_solid_jobs` actually
threaded it through (per [ADR 0001](0001-solid-jobs-sync-vs-search-cache-strategy.md)). The
interface promised uniform behavior it didn't have.

We rejected dropping `force_refresh` from the two connectors' signatures (the bug report's other
suggested fix) because, since [BUG02](0009-justjoinit-incremental-pagination-strategy.md),
JustJoin.it actually has an incremental checkpoint `force_refresh` can meaningfully bypass: the
early-stop-on-consecutive-already-seen pagination logic. `run_justjoinit_ingestion(...,
force_refresh=True)` now skips that check, walking pagination all the way to `max_pages`
regardless of the already-seen streak — a genuine "re-walk the full catalog right now" behavior,
exactly what a job-seeker's manual "Fetch now" should mean.

NoFluffJobs has no equivalent checkpoint. Per ADR 0009, it deliberately has no pagination loop and
no incremental fetch of any kind — every call already issues one full live fetch of the
recommended-offers feed. There is nothing for `force_refresh` to bypass. Rather than re-hide this
behind a signature that doesn't accept the parameter (reintroducing the silent-drop the bug was
about), `run_nofluffjobs_ingestion` now accepts `force_refresh` for interface parity with its two
siblings, with an in-line comment explaining why it's a deliberate no-op. This keeps the
`Connector` protocol's `(session, source, force_refresh) -> IngestionResult` shape uniform across
all three dispatch adapters (required for `CONNECTOR_REGISTRY`'s dict-of-callables dispatch to stay
homogeneous) while making each connector's actual relationship to the flag explicit at the point
where it's decided, not silently swallowed one layer removed.
