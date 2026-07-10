# Offer highlight is derived, not stored

The new-offer highlight (P3US35) is computed on every `GET /offers` read from `score_percent`, `link_opened_at`, and the client's `scoreAlertPrefs.minScorePercent` — there is no `is_highlighted` column, no "mark as seen" endpoint, and no per-session cache. We considered storing/caching the flag for cheaper reads, but rejected it: the acceptance criteria requires lowering the alert threshold in Settings to retroactively highlight previously-below-bar offers on the very next load, with no rescoring or backend change. A stored flag would need invalidation logic to react to a client-side preference change it can't see, and would silently drift stale otherwise.

## Consequences

Don't add a stored/cached highlight flag or a "seen" endpoint later purely for read performance — recomputing the predicate is what makes threshold changes and multi-tab/multi-device `link_opened_at` updates work correctly without extra invalidation code.
