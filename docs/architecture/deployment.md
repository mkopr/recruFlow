# Deployment & CI

[Architecture index](../../ARCHITECTURE.md)

### Makefile targets

- `install` — `uv sync --all-groups` + `cd frontend && pnpm install`.
- `format` — `uv run ruff format .` + `cd frontend && pnpm format`.
- `lint` — `uv run ruff check .` + `uv run mypy .` + `cd frontend && pnpm lint`.
- `typecheck` — `uv run mypy .` + `cd frontend && pnpm run typecheck` (`tsc -b`, i.e. build mode
  — plain `tsc --noEmit` is a no-op against the references-only root `tsconfig.json`, since it
  has `files: []` and only `-b`/`--build` traverses `references`; fixed in P0US7 after discovering
  `pnpm run typecheck` was silently passing regardless of real type errors in `src/`).
- `test` / `test-unit` / `test-integration` — `uv run pytest`, scoped by the `integration`
  marker. Python-only.
- `test-frontend` (P1US8) — `cd frontend && pnpm test` (`vitest run`). Deliberately **not** part
  of `ci`/`test` yet — see `docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md`.
- `ci` — runs `format lint typecheck test` in sequence; now covers both stacks since `lint`,
  `format`, and `typecheck` each fan out to the frontend toolchain.
- `clean` — removes `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`,
  `build`.
- `up` — `docker compose up --build`; brings up all four Compose services with hot reload for
  `api` and `frontend` (P0US4).
- `migrate` — `docker compose exec api alembic upgrade head` (P0US5).
- `seed` — `docker compose exec api python -m app.db.seed` (P0US5).
- `generate-types` — `cd frontend && pnpm run generate-types`, which runs `openapi-typescript`
  against `http://localhost:8000/openapi.json` and writes `frontend/src/api/schema.d.ts` (P0US7).
  Requires the API to already be running (`make up`). Its output is committed to source control
  — CI does not start the API, so it never regenerates this file itself — and must be re-run
  manually after any API contract change.

- `install` now also runs `uv run pre-commit install` after the dependency/frontend install
  steps, registering the git hooks defined in `.pre-commit-config.yaml`.

### Pre-commit hooks (`.pre-commit-config.yaml`)

Hook definitions live in `.pre-commit-config.yaml`. Every hook except `trailing-whitespace`
(from the upstream `pre-commit/pre-commit-hooks` repo) is a `local` hook with
`language: system`, calling the same commands `make lint` / `make format` / `make typecheck`
already use (`uv run --frozen ruff check --fix`, `uv run --frozen ruff format`,
`pnpm exec eslint . --fix`, `uv run --frozen mypy .`) plus two lockfile-sync checks
(`uv lock --check`, `pnpm install --frozen-lockfile`). Using the project's own
uv/pnpm-managed toolchain instead of hosted mirrors (e.g. `astral-sh/ruff-pre-commit`,
`mirrors-mypy`) means pre-commit and `make ci` can never disagree about tool versions.
`--frozen` is required on every `uv run` hook: by default `uv run` auto-syncs the environment
before running, which silently rewrites `uv.lock` to match `pyproject.toml` — that would mask
real drift before the `uv-lock-check` hook ever runs. `--frozen` runs against the lock file
as committed, so `uv-lock-check` is the sole source of truth on lock/pyproject sync. Hooks
are ordered so auto-fixers run before non-fixable checks, per the "auto fix before check"
requirement.

## Docker Compose services (P0US4)

`docker-compose.yml` defines four services, brought up together by `make up`. Service names,
ports, and credentials match `.env.example` exactly.

| Service | Image / build target | Port | Healthcheck |
| --- | --- | --- | --- |
| `api` | `Dockerfile` target `runtime` | 8000 | `curl -f http://localhost:8000/health` |
| `frontend` | `Dockerfile.frontend` target `dev` | 5173 | `wget --spider http://localhost:5173` |
| `db` | `postgres:16-alpine` | 5432 | `pg_isready -U recruflow -d recruflow` |
| `ollama` | `ollama/ollama:latest` | 11434 | `ollama list` |

Notes:

- `api` and `frontend` bind-mount their source directories (`./app`, `./frontend`) so
  `uvicorn --reload` and the Vite dev server pick up local edits without a container rebuild.
  `frontend` also declares an anonymous volume on `/app/node_modules` so the host bind mount
  doesn't shadow the dependencies installed inside the image.
- `api` depends on `db` with `condition: service_healthy`, so it won't start accepting
  connections until Postgres is actually ready.
- `db` and `ollama` persist state in named volumes (`pgdata`, `ollama_data`) so data survives
  `docker compose down` (but not `docker compose down -v`).
- The `Dockerfile` runtime stage installs `curl`/`ca-certificates` via `apt-get` — kept solely for
  the `api` healthcheck above (`CMD curl -f http://localhost:8000/health`), not for anything
  SOLID.Jobs-related anymore (BUG10 removed the sjctl installer that used to be this block's other
  reason to exist; removing the block entirely broke the healthcheck, since nothing else in the
  image provides `curl` — caught by this story's own manual end-to-end test, not by `make ci`).
- `Dockerfile.frontend` has three stages: `dev` (Vite dev server, used by `docker-compose.yml`),
  `build` (`pnpm build`, produces `frontend/dist`), and `production` (nginx serving the built
  static assets via `frontend/nginx.conf`, an SPA fallback for client-side routing added in
  later phases). Only `dev` is wired into Compose today; `production` is built but not yet
  deployed anywhere.

## CI (GitHub Actions) (P0US8)

`.github/workflows/ci.yml` defines a single workflow with a single job, triggered on every
`pull_request` and every `push` to `main`. Rather than re-implementing `ruff check`, `mypy`,
`pytest`, `eslint`, and TypeScript type-checking as separate `run:` steps, the job's final step
is `make ci` — the same target developers already run locally (`format lint typecheck test`, in
that order, `format`'s auto-fixers running before the non-fixable `lint`/`typecheck` gates). This
guarantees local `make ci` and the GitHub Actions run can never drift apart, the same rationale
`.pre-commit-config.yaml` uses for calling Make-equivalent commands directly (see "Pre-commit
hooks" above) instead of hosted-mirror actions.

Supporting setup, in order:

- **Postgres service container**: `services.postgres` uses `postgres:16-alpine` with
  `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` all `recruflow`, port `5432`, and a
  `pg_isready -U recruflow -d recruflow` health check — an exact mirror of `docker-compose.yml`'s
  `db` service, so there is only one definition of "a correctly configured recruFlow Postgres"
  across local dev and CI. GitHub Actions service containers publish to `localhost` on the
  runner (not a Compose network hostname), so the job-level `DATABASE_URL` points at
  `localhost:5432` — this happens to be the exact same default `tests/integration/conftest.py`
  falls back to when `DATABASE_URL` is unset.
- **Dependency install**: `astral-sh/setup-uv@v6` (pinned to `0.11.23`, the version in local use)
  + `uv sync --all-groups --frozen` (`--frozen` fails loudly on lockfile drift instead of
  rewriting `uv.lock`, the same rationale pre-commit's `uv-lock-check` hook relies on), then
  `pnpm/action-setup@v4` + `actions/setup-node@v4` + `pnpm install --frozen-lockfile` in
  `frontend/` (mirrors the `pnpm-lock-check` pre-commit hook exactly).
- **Settings env vars**: `app/main.py` calls `get_settings()` at import time, and `Settings` has
  no defaults for `database_url`, `ollama_base_url`, or `ollama_model` (see "`app/config.py`"
  above) — any process importing `app.main` without these set raises `pydantic.ValidationError`
  before a single test runs. The workflow copies `.env.example` to `.env` (`cp .env.example
  .env`) so every other Settings field has a valid placeholder, then sets `DATABASE_URL`,
  `OLLAMA_BASE_URL`, and `OLLAMA_MODEL` at the job level — `pydantic-settings` gives explicit
  environment variables precedence over the same key in `.env`, so the job-level `DATABASE_URL`
  (pointing at `localhost`) overrides `.env.example`'s Compose-network value (`db:5432`) without
  editing the copied file.
- **`tsc --noEmit` vs. `tsc -b`**: the story's acceptance criteria literally says "runs ... `tsc
  --noEmit`", but as documented above under "Makefile targets", plain `tsc --noEmit` silently
  no-ops against this project's references-only root `tsconfig.json` (the P0US7 discovery). The
  workflow does not invoke `tsc --noEmit` directly — it gets type-checking for free through
  `make ci` → `typecheck` → `pnpm run typecheck` (`tsc -b`), which is the only command that
  actually traverses `frontend/tsconfig.json`'s `references` and catches real TypeScript errors.
  Implementing the AC literally would make the "CI fails on type error" scenario silently pass.
- **README badge**: deferred — this repository has no GitHub remote configured yet (`git remote
  -v` returns nothing), so there is no `owner/repo` to build a badge URL from. README documents
  the CI workflow's behavior and notes the badge is pending a remote.
