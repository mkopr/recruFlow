from pathlib import Path

REQUIRED_PATTERNS = [
    "__pycache__/",
    ".venv/",
    ".mypy_cache/",
    "node_modules/",
    ".env",
    "*.db",
]


def test_gitignore_covers_required_artefacts() -> None:
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    content = gitignore.read_text()
    for pattern in REQUIRED_PATTERNS:
        assert pattern in content, f"{pattern} is missing from .gitignore"
