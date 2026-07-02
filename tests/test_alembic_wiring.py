from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_alembic_ini_exists() -> None:
    assert (REPO_ROOT / "alembic.ini").exists()


def test_alembic_env_uses_declarative_base_metadata() -> None:
    content = (REPO_ROOT / "alembic" / "env.py").read_text()
    assert "app.db.models" in content
    assert "target_metadata" in content
