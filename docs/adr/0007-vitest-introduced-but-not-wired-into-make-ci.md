# Vitest introduced for US17, but not wired into make ci

US17 (offer list page) is the first frontend story with real interactive behavior — filters, async fetch, loading states — rather than static content, so we introduced `vitest` + `@testing-library/react` and wrote real component tests instead of continuing the `tests/test_frontend_api_client.py`-style Python content-assertion precedent from earlier stories.

However, `pnpm test` is deliberately **not** added to the Makefile's `test`/`ci` targets or the GitHub Actions workflow. It runs as a separate, manually-invoked command. This keeps `make ci` and CI green while the new frontend test setup beds in, at the cost of frontend tests not yet being a hard gate. If a frontend test regresses, nothing currently blocks it from being merged.

If frontend tests prove stable, the natural next step is folding `pnpm test` into `make test`/`make ci` and the GitHub Actions workflow — not re-litigating whether vitest is the right tool.
