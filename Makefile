.PHONY: install lint format test test-unit test-integration typecheck ci clean

install:
	uv sync --all-groups

format:
	uv run ruff format .

lint:
	uv run ruff check .
	uv run mypy .

typecheck:
	uv run mypy .

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
