.PHONY: install lint format test test-unit test-integration typecheck ci clean up sjctl-version

install:
	uv sync --all-groups
	cd frontend && pnpm install
	uv run pre-commit install

up:
	docker compose up --build

sjctl-version:
	docker compose exec api sjctl version

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

test:
	uv run pytest

test-unit:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

ci: format lint typecheck test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache dist build
