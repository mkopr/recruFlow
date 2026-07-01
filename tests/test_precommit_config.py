import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

REQUIRED_HOOK_IDS = {
    "trailing-whitespace",
    "ruff-check",
    "ruff-format",
    "mypy",
    "eslint",
    "uv-lock-check",
    "pnpm-lock-check",
}


def _load_config() -> dict[str, Any]:
    config: dict[str, Any] = yaml.safe_load(PRECOMMIT_CONFIG.read_text())
    return config


def _all_hooks_in_order() -> list[dict[str, Any]]:
    config = _load_config()
    hooks: list[dict[str, Any]] = []
    for repo in config["repos"]:
        hooks.extend(repo["hooks"])
    return hooks


def _hook_by_id(hook_id: str) -> dict[str, Any]:
    for hook in _all_hooks_in_order():
        if hook["id"] == hook_id:
            return hook
    raise AssertionError(f"hook {hook_id!r} not found")


def test_precommit_config_exists_and_is_valid_yaml() -> None:
    assert PRECOMMIT_CONFIG.exists()
    config = yaml.safe_load(PRECOMMIT_CONFIG.read_text())
    assert isinstance(config, dict)
    assert isinstance(config["repos"], list)
    assert len(config["repos"]) > 0


def test_precommit_config_declares_all_required_hook_categories() -> None:
    ids = {hook["id"] for hook in _all_hooks_in_order()}
    assert ids.issuperset(REQUIRED_HOOK_IDS)


def test_precommit_uses_pre_commit_hooks_repo_for_trailing_whitespace() -> None:
    config = _load_config()
    matching = [r for r in config["repos"] if r["repo"].endswith("pre-commit-hooks")]
    assert matching, "no pre-commit-hooks repo entry found"
    hook_ids = {hook["id"] for hook in matching[0]["hooks"]}
    assert "trailing-whitespace" in hook_ids


def test_local_hooks_use_system_language_and_skip_filenames() -> None:
    config = _load_config()
    local_repos = [r for r in config["repos"] if r["repo"] == "local"]
    assert local_repos, "no local repo entry found"
    for repo in local_repos:
        for hook in repo["hooks"]:
            assert hook["language"] == "system", hook["id"]
            assert hook["pass_filenames"] is False, hook["id"]


def test_ruff_hooks_declare_auto_fix() -> None:
    assert "--fix" in _hook_by_id("ruff-check")["entry"]
    assert "--fix" in _hook_by_id("eslint")["entry"]


def test_auto_fix_hooks_precede_non_fixable_checks() -> None:
    ids = [hook["id"] for hook in _all_hooks_in_order()]
    for fixer in ["ruff-check", "ruff-format", "eslint"]:
        assert ids.index(fixer) < ids.index("mypy")
    for fixer_dependency in ["uv-lock-check", "pnpm-lock-check"]:
        assert ids.index("ruff-check") < ids.index(fixer_dependency)


def test_lockfile_hooks_target_correct_files() -> None:
    uv_lock_hook = _hook_by_id("uv-lock-check")
    assert re.search(uv_lock_hook["files"], "pyproject.toml")
    assert re.search(uv_lock_hook["files"], "uv.lock")

    pnpm_lock_hook = _hook_by_id("pnpm-lock-check")
    assert re.search(pnpm_lock_hook["files"], "frontend/package.json")
    assert re.search(pnpm_lock_hook["files"], "frontend/pnpm-lock.yaml")


def test_no_duplicate_hook_ids() -> None:
    ids = [hook["id"] for hook in _all_hooks_in_order()]
    assert len(ids) == len(set(ids))


def test_makefile_install_target_runs_pre_commit_install() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    lines = makefile.splitlines()

    blocks: dict[str, list[str]] = {}
    current_target: str | None = None
    for line in lines:
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            current_target = line.split(":", 1)[0].strip()
            blocks[current_target] = []
        elif current_target is not None:
            blocks[current_target].append(line)

    assert "pre-commit install" in "\n".join(blocks.get("install", []))


def test_readme_documents_precommit_section() -> None:
    content = (REPO_ROOT / "README.md").read_text()
    assert "## Pre-commit hooks" in content
    for phrase in [
        "pre-commit install",
        "pre-commit run --all-files",
        "trailing-whitespace",
        "ruff check --fix",
        "mypy",
        "eslint",
        "uv lock --check",
        "frozen-lockfile",
    ]:
        assert phrase in content, f"README Pre-commit hooks section missing: {phrase}"


def test_architecture_documents_precommit_file() -> None:
    content = (REPO_ROOT / "ARCHITECTURE.md").read_text()
    assert ".pre-commit-config.yaml" in content
