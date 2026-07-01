import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = REPO_ROOT / "frontend"

REQUIRED_GITIGNORE_PATTERNS = [
    "node_modules/",
    "frontend/dist/",
    "frontend/.vite/",
]


def test_frontend_package_json_is_valid_json() -> None:
    package_json = FRONTEND / "package.json"
    assert package_json.exists()
    json.loads(package_json.read_text())


def test_package_json_declares_required_scripts() -> None:
    parsed = json.loads((FRONTEND / "package.json").read_text())
    for script in ["dev", "build", "lint", "format", "typecheck"]:
        assert script in parsed["scripts"], f"{script} missing from package.json scripts"


def test_tsconfig_app_strict_mode_enabled() -> None:
    parsed = json.loads((FRONTEND / "tsconfig.app.json").read_text())
    assert parsed["compilerOptions"]["strict"] is True


def test_tsconfig_root_uses_project_references() -> None:
    parsed = json.loads((FRONTEND / "tsconfig.json").read_text())
    paths = [ref["path"] for ref in parsed["references"]]
    assert "./tsconfig.app.json" in paths
    assert "./tsconfig.node.json" in paths


def test_pnpm_lock_committed_and_nonempty() -> None:
    lockfile = FRONTEND / "pnpm-lock.yaml"
    assert lockfile.exists()
    assert len(lockfile.read_text().strip()) > 0


def test_tailwind_dependencies_declared() -> None:
    parsed = json.loads((FRONTEND / "package.json").read_text())
    dev_deps = parsed["devDependencies"]
    assert "tailwindcss" in dev_deps
    assert "@tailwindcss/vite" in dev_deps


def test_vite_config_registers_tailwind_plugin() -> None:
    content = (FRONTEND / "vite.config.ts").read_text()
    assert "@tailwindcss/vite" in content
    assert "tailwindcss()" in content


def test_eslint_config_ignores_dist() -> None:
    eslint_config = FRONTEND / "eslint.config.js"
    assert eslint_config.exists()
    assert "dist" in eslint_config.read_text()


def test_prettier_config_present_and_valid() -> None:
    prettier_config = FRONTEND / ".prettierrc.json"
    assert prettier_config.exists()
    parsed = json.loads(prettier_config.read_text())
    assert "printWidth" in parsed


def test_index_css_imports_tailwind() -> None:
    content = (FRONTEND / "src" / "index.css").read_text()
    assert '@import "tailwindcss"' in content or "@import 'tailwindcss'" in content


def test_app_component_uses_tailwind_utility_class() -> None:
    content = (FRONTEND / "src" / "App.tsx").read_text()
    assert re.search(r"className=[\"'][^\"']*\b(bg-|text-|flex)\b", content)


def test_makefile_wires_frontend_into_install_lint_format_typecheck() -> None:
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

    assert "pnpm install" in "\n".join(blocks.get("install", []))
    assert "pnpm lint" in "\n".join(blocks.get("lint", []))
    assert "pnpm format" in "\n".join(blocks.get("format", []))
    typecheck_block = "\n".join(blocks.get("typecheck", []))
    assert "pnpm" in typecheck_block
    assert "typecheck" in typecheck_block


def test_readme_documents_frontend_section() -> None:
    content = (REPO_ROOT / "README.md").read_text()
    assert "## Frontend" in content
    for phrase in ["pnpm install", "pnpm dev", "pnpm lint", "pnpm format", "strict", "Tailwind"]:
        assert phrase in content, f"README Frontend section missing: {phrase}"


def test_gitignore_still_covers_frontend_artifacts() -> None:
    content = (REPO_ROOT / ".gitignore").read_text()
    for pattern in REQUIRED_GITIGNORE_PATTERNS:
        assert pattern in content, f"{pattern} is missing from .gitignore"
