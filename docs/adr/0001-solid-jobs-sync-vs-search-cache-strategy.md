> Superseded 2026-07-05 by [ADR 0012](0012-solid-jobs-direct-api-replaces-sjctl-subprocess.md) —
> kept for history; the sync/search subcommand split described below no longer reflects current
> behavior.

# SOLID.Jobs connector: subcommand choice drives cache behavior, not a flag

The SOLID.Jobs connector needs to satisfy "respect sjctl's local cache unless a re-fetch is explicitly requested." sjctl exposes no single "bypass cache" flag — instead it has two structurally different subcommands: `sync` (runs sjctl's own saved watches, returns only offers not seen before, no filter flags) and `search` (runs an ad hoc filtered query, always hits the live API, ignores watches entirely).

We map `force_refresh=False` (default) to `sync` and `force_refresh=True` to `search` with the Source's `config_json` filters applied. This means `force_refresh` doesn't just toggle caching — it switches which offers are even reachable: the default path is scoped to whatever watches were separately configured via `sjctl watch add`, while the force-refresh path is scoped to the Source's `config_json` filters (division/cities/min_salary/experience_levels/terms) and does not respect saved watches at all. A caller who expects `force_refresh=True` to just "re-check the same watches without the cache" will get different offers than expected.
