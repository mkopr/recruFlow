# Architecture

## Repository layout

```
recruFlow/
├── app/            # Python application package (placeholder — P0US6 adds app/main.py)
├── tests/          # Unit tests (pure filesystem/import checks, no external services)
│   └── integration/  # Tests requiring external services (DB, Ollama, sjctl, ...)
├── pyproject.toml
├── uv.lock
├── Makefile
├── .env.example
└── .gitignore
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

Currently a placeholder exposing only `__version__`. P0US6 (FastAPI skeleton) adds
`app/main.py` and the rest of the application code inside this package.

### Makefile targets

Only targets meaningful with just the Python project in place today:

- `install` — `uv sync --all-groups`.
- `format` — `uv run ruff format .`.
- `lint` — `uv run ruff check .` + `uv run mypy .`.
- `typecheck` — `uv run mypy .`.
- `test` / `test-unit` / `test-integration` — `uv run pytest`, scoped by the `integration`
  marker.
- `ci` — runs `format lint typecheck test` in sequence.
- `clean` — removes `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `dist`,
  `build`.

Targets depending on infrastructure introduced by later stories (`dev`, `migrate`, `seed`,
`generate-types`, `sjctl-version`) are deliberately out of scope here and will be added by
P0US4, P0US5, P0US7, and P0US9 respectively.
