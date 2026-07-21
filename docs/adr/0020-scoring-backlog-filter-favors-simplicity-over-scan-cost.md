# Scoring backlog filter favors code simplicity over per-call scan cost

`_fetch_unscored_offers` and `_count_unscored_offers` (`app/scoring/batch.py`) were made Fetch-Range-aware: an offer is only a scoring candidate if it falls inside its Source's `fetch_range` window. That window lives in `Source.config_json`, a JSONB column, and the "undated offer counts as now" rule (ADR 0017) is evaluated per offer, not once per query.

We chose to materialize the full unscored+non-failed candidate set for the active Profile and filter it in Python (`_in_fetch_range`), replacing the previous `.limit(limit)` / `func.count()` SQL-side approach entirely — both the fetch path and the count path now read every candidate row on every call.

This has a real, non-hypothetical cost: the dev DB carries ~14,000 unscored offers today, and `GET /scoring/status` — which calls `_count_unscored_offers` — is polled by the frontend every 1.5 seconds while a batch scoring run is in progress. That means a ~14K-row fetch-and-filter on close to every heartbeat of the progress UI, not just once per batch run.

We accepted this because:
- The alternative (pushing `since`/`until` extraction and comparison into SQL via JSONB path operators, with a `COALESCE`-style null-`posted_at`-as-now fallback) duplicates `resolve_fetch_range`'s parsing and fail-open logic in a second, SQL-shaped form — two places to keep in sync for one filtering rule.
- This is a single-user, local-network tool; a 14K-row Postgres read plus a Python loop is low-single-digit milliseconds of work, well under any threshold a human polling a progress bar would notice.
- This work ships its own release valve for the underlying growth (`DELETE /offers?older_than=`), so the table isn't destined to grow unbounded without the user having a lever to pull.

If profiling ever shows this materialize-then-filter step is a measurable cost — e.g. after the offers table grows another order of magnitude, or if `GET /scoring/status`'s poll cadence tightens — the fix is to push the common case (`mode: "all"` or no `fetch_range` at all, which is likely the majority of sources) down into the SQL `WHERE` clause, and only fall back to the Python predicate for sources actually configured with `mode: "range"`. We deliberately did not build that now: it would have been optimizing for a scale this deployment doesn't have yet.
