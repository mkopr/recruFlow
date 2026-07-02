from pathlib import Path

MAKEFILE = Path(__file__).parent.parent / "Makefile"


def test_makefile_defines_migrate_target() -> None:
    content = MAKEFILE.read_text()
    assert "migrate:" in content
    assert "alembic upgrade head" in content


def test_makefile_defines_seed_target() -> None:
    content = MAKEFILE.read_text()
    assert "seed:" in content
    assert "python -m app.db.seed" in content
