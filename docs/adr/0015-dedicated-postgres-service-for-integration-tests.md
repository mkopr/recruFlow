# Integration tests run against a dedicated `db_test` Postgres, not the real `db` service

`tests/integration/conftest.py`'s `reset_test_profiles` (and other fixtures) blanket-reset whole
tables (e.g. `UPDATE profiles SET is_active = false` with no `WHERE` clause — required so
`test_get_active_profile_returns_none_when_none_active` can assert on a globally-empty state).
Before this ADR, integration tests connected to the same long-lived Postgres instance `make up`
uses, so any `make test`/`make test-integration`/`make ci` run silently deactivated whatever
Profile a developer had marked active for real use, with no restore step anywhere.

The fix is a second, ephemeral `db_test` Compose service (`docker-compose.yml`, port 5433,
`recruflow_test` database, no named volume) that `make test`/`make test-integration` bring up via
`make db-test-up` before running pytest. `tests/integration/conftest.py` defaults `DATABASE_URL`
to this service instead of the real `db` service's port/database. CI is unaffected: it already
sets its own `DATABASE_URL` pointing at a fresh, ephemeral GitHub Actions Postgres service, and
`db-test-up`/conftest's default both back off via `os.environ.setdefault`-style checks whenever
`DATABASE_URL` is already set by the caller.

This also incidentally fixes the standing dev-DB-pollution issue (leaked `test-*`/`profile-*`
fixture rows accumulating in the real database over time), since test fixtures now only ever
write to `db_test`.
