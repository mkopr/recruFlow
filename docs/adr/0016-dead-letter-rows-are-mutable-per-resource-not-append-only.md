# Dead letter failure rows are mutable, one per resource, not an append-only log

The pipeline dead letter queues (ingestion/scoring failures, P3US33) store at most one row per failing resource (a job posting, a source's ingestion, an offer×profile pair), keyed by a `dedup_key`. A recurring failure upserts the existing row (`ON CONFLICT (dedup_key) DO UPDATE`) rather than appending a new one, and a successful retry flips it to `status="resolved"` in place instead of deleting it.

We considered an append-only audit log (one row per occurrence, like `scheduler_runs`) but rejected it: the primary use case is "what's currently broken that I need to fix," and an append-only log would force every list view to de-duplicate down to "latest per resource" anyway. The trade-off is that per-resource occurrence history (how many times, how often) is not retained — only the latest failure and, once fixed, the fact that it was resolved. If future stories need frequency/trend data, that's a different table, not a reason to revisit this one.

This also makes retry idempotent by construction: `page_fetch_failed`/`run_fetch_failed` share a `source:{id}` dedup key, so retrying by re-triggering ingestion either resolves the row or lets the ordinary `record_failure` call re-open the *same* row — no special-casing needed to avoid duplicate rows on repeated failure.
