import app.db.models  # noqa: F401
from app.db.base import Base


def test_models_register_all_v1_tables() -> None:
    assert set(Base.metadata.tables.keys()) == {
        "sources",
        "offers",
        "profiles",
        "cv_versions",
        "match_scores",
        "applications",
    }


def test_offers_dedup_hash_is_unique_and_not_nullable() -> None:
    column = Base.metadata.tables["offers"].columns["dedup_hash"]
    assert column.unique is True
    assert column.nullable is False


def test_profiles_name_is_unique() -> None:
    column = Base.metadata.tables["profiles"].columns["name"]
    assert column.unique is True
    assert column.nullable is False
