.PHONY: install lint format test test-unit test-integration test-frontend typecheck ci clean up migrate seed generate-types db-test-up

install:
	uv sync --all-groups
	cd frontend && pnpm install
	uv run pre-commit install

up:
	docker compose up --build

migrate:
	docker compose exec api alembic upgrade head

seed:
	docker compose exec api python -m app.db.seed

generate-types:
	cd frontend && pnpm run generate-types

format:
	uv run ruff format .
	cd frontend && pnpm format

lint:
	uv run ruff check .
	uv run mypy .
	cd frontend && pnpm lint

typecheck:
	uv run mypy .
	cd frontend && pnpm run typecheck

# BUG28: integration tests blanket-reset whole tables and must never run against the real `db`
# service's data, so they target the dedicated `db_test` compose service instead (see
# tests/integration/conftest.py). Only bring it up when DATABASE_URL isn't already set by the
# caller (e.g. CI provides its own ephemeral Postgres and sets DATABASE_URL itself).
db-test-up:
	@if [ -z "$$DATABASE_URL" ]; then docker compose up -d --wait db_test; fi

test: db-test-up
	uv run pytest

test-unit:
	uv run pytest -m "not integration"

test-integration: db-test-up
	uv run pytest -m integration

# Not part of `ci`/`test` yet — see docs/adr/0007-vitest-introduced-but-not-wired-into-make-ci.md
test-frontend:
	cd frontend && pnpm test

ci: format lint typecheck test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache dist build
