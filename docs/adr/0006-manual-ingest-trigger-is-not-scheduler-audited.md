# Manual ingest trigger does not write to scheduler_runs

`POST /ingest/{source}` (US16) is a job-seeker-facing, on-demand fetch trigger, distinct from the scheduler subsystem's own audited manual trigger at `POST /scheduler/run/{source}`. It calls `resolve_source_by_connector` + `dispatch_ingestion` directly and deliberately does not call `app.scheduler.runs.start_run`/`finish_run_*`, so `GET /scheduler/status` reflects only automatic runs and `/scheduler/run/{source}`-triggered runs — never `/ingest/{source}` triggers, even though US17 wires its "Fetch now" button to `/ingest/{source}`.

This keeps the ingestion API lightweight and independent of the scheduler subsystem, at the deliberate cost of `/scheduler/status` not being a complete picture of "everything that fetched data recently." If that gap becomes a real usability problem, the fix is to have `/ingest/{source}` also write a `scheduler_runs` row — not to merge the two endpoints.
