# Architecture

## Repository layout

```
recruFlow/
├── app/            # Python application package (P0US4 adds a /health stub; P0US6 adds the rest)
│   └── main.py     # FastAPI app object, GET /health only
├── frontend/       # React + Vite + TypeScript frontend (P0US2)
│   ├── src/        # App source (main.tsx, App.tsx, index.css, vite-env.d.ts)
│   ├── nginx.conf  # SPA server block for the production Docker image (P0US4)
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── tsconfig.json       # references-only root config
│   ├── tsconfig.app.json   # strict app config (src/)
│   ├── tsconfig.node.json  # config for vite.config.ts (node context)
│   ├── vite.config.ts
│   └── eslint.config.js
├── tests/          # Unit tests (pure filesystem/import checks, no external services)
│   └── integration/  # Tests requiring external services (DB, Ollama, sjctl, ...)
├── pyproject.toml
├── uv.lock
├── Makefile
├── .pre-commit-config.yaml
├── .env.example
├── .gitignore
├── Dockerfile            # multi-stage: builder (uv sync) -> runtime (uvicorn + sjctl)
├── Dockerfile.frontend   # multi-stage: dev (Vite dev server) -> build -> production (nginx)
├── .dockerignore
└── docker-compose.yml    # api, frontend, db, ollama — each with a health check
```

### Dependency groups (`pyproject.toml`)

- `main` — runtime dependencies of the FastAPI application: `fastapi`, `uvicorn`, the async
  SQLAlchemy stack (`sqlalchemy[asyncio]`, `asyncpg`), `alembic`, `pydantic`,
  `pydantic-settings`. Later phases add further runtime deps here incrementally
  (`langchain`/`langgraph`/`langchain-ollama` in P3US2, `playwright` in P5US6,
  `weasyprint`/`python-docx` in P4US4/P6US4) as the story that needs them lands.
- `dev` — local developer tooling: `ruff`, `mypy`, `pre-commit`.
- `test` — test-only dependencies: `pytest`, `pytest-asyncio`, `httpx`, `pytest-cov`.

### `app/` package

Exposes `__version__` (P0US1) plus, as of P0US4, `app/main.py`: a minimal FastAPI app with a
single `GET /health` route returning `{"status": "ok"}`. This exists only so the `api` Compose
service has a real HTTP endpoint to health-check — it does not load settings, open a DB session,
or wire OpenAPI docs. P0US6 (FastAPI skeleton) replaces this stub with full Pydantic Settings
loading, the DB session dependency, and the rest of the application's routers.

### `frontend/` project

React + Vite + TypeScript, styled with Tailwind CSS, managed with `pnpm`.

- **TypeScript project references**: `tsconfig.json` is a references-only root (`files: []`)
  pointing at `tsconfig.app.json` (strict, browser `lib`, covers `src/`) and
  `tsconfig.node.json` (covers `vite.config.ts`, which runs in a Node context with different
  `lib`/`module` needs). This mirrors the official Vite React-TS template so editor tooling and
  build-time config type-check independently of app source.
- **Tailwind CSS v4**: wired via the `@tailwindcss/vite` plugin in `vite.config.ts` — no
  `tailwind.config.js` or `postcss.config.js`; content scanning is automatic and Tailwind is
  enabled by a single `@import "tailwindcss";` in `src/index.css`.
- **ESLint flat config** (`eslint.config.js`): `@eslint/js` recommended +
  `typescript-eslint` recommended + `eslint-plugin-react-hooks` +
  `eslint-plugin-react-refresh`, with `eslint-config-prettier` applied last so no ESLint
  stylistic rule conflicts with Prettier. `dist` is excluded via `ignores` so a local
  `pnpm build` doesn't break `pnpm lint`.
- **Prettier** (`.prettierrc.json`): `printWidth: 100` to mirror the Python side's
  `ruff` line-length 100.
- `pnpm-lock.yaml` is committed, same reproducible-install precedent as `uv.lock`.

### Makefile targets

- `install` — `uv sync --all-groups` + `cd frontend && pnpm install`.
- `format` — `uv run ruff format .` + `cd frontend && pnpm format`.
- `lint` — `uv run ruff check .` + `uv run mypy .` + `cd frontend && pnpm lint`.
- `typecheck` — `uv run mypy .` + `cd frontend && pnpm run typecheck` (`tsc --noEmit`).
- `test` / `test-unit` / `test-integration` — `uv run pytest`, scoped by the `integration`
  marker. Python-only; no frontend test runner is in scope yet.
- `ci` — runs `format lint typecheck test` in sequence; now covers both stacks since `lint`,
  `format`, and `typecheck` each fan out to the frontend toolchain.
- `clean` — removes `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`,
  `build`.
- `dev` — `docker compose up --build`; brings up all four Compose services with hot reload for
  `api` and `frontend` (P0US4).
- `sjctl-version` — `docker compose exec api sjctl version`; prints the `sjctl` binary version
  installed inside the `api` container (P0US4).

Targets depending on infrastructure introduced by later stories (`migrate`, `seed`,
`generate-types`) are deliberately out of scope here and will be added by P0US5, P0US7, and
P0US9 respectively.

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

`docker-compose.yml` defines four services, brought up together by `make dev`. Service names,
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
- The `Dockerfile` multi-stage build installs `sjctl` (the SOLID.Jobs CLI) into the `runtime`
  stage via its official install script
  (`scripts/install-sjctl.sh` from `solid-company/solid-jobs-skills`), with cosign signature
  verification skipped (`SJCTL_SKIP_COSIGN=1`, since `cosign` isn't installed in this image) —
  the script still verifies the release asset's sha256 checksum. `make sjctl-version` runs
  `sjctl version` inside the running `api` container.
- `Dockerfile.frontend` has three stages: `dev` (Vite dev server, used by `docker-compose.yml`),
  `build` (`pnpm build`, produces `frontend/dist`), and `production` (nginx serving the built
  static assets via `frontend/nginx.conf`, an SPA fallback for client-side routing added in
  later phases). Only `dev` is wired into Compose today; `production` is built but not yet
  deployed anywhere.
