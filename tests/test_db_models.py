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
        "scheduler_runs",
        "ingestion_failures",
        "scoring_failures",
    }


def test_offers_dedup_hash_is_unique_and_not_nullable() -> None:
    column = Base.metadata.tables["offers"].columns["dedup_hash"]
    assert column.unique is True
    assert column.nullable is False


def test_profiles_name_is_unique() -> None:
    column = Base.metadata.tables["profiles"].columns["name"]
    assert column.unique is True
    assert column.nullable is False


def test_offers_canonical_url_is_nullable() -> None:
    column = Base.metadata.tables["offers"].columns["canonical_url"]
    assert column.nullable is True


def test_offers_description_column_exists_and_is_nullable() -> None:
    assert "description" in Base.metadata.tables["offers"].columns
    assert Base.metadata.tables["offers"].columns["description"].nullable is True


def test_sources_connector_column_exists_and_is_nullable() -> None:
    assert "connector" in Base.metadata.tables["sources"].columns
    assert Base.metadata.tables["sources"].columns["connector"].nullable is True


def test_scheduler_runs_source_id_started_at_index_exists() -> None:
    index_names = {index.name for index in Base.metadata.tables["scheduler_runs"].indexes}
    assert "ix_scheduler_runs_source_id_started_at" in index_names


def test_ingestion_failures_source_id_occurred_at_index_exists() -> None:
    index_names = {index.name for index in Base.metadata.tables["ingestion_failures"].indexes}
    assert "ix_ingestion_failures_source_id_occurred_at" in index_names


def test_scoring_failures_offer_id_occurred_at_index_exists() -> None:
    index_names = {index.name for index in Base.metadata.tables["scoring_failures"].indexes}
    assert "ix_scoring_failures_offer_id_occurred_at" in index_names


def test_ingestion_failures_dedup_key_is_unique_and_not_nullable() -> None:
    column = Base.metadata.tables["ingestion_failures"].columns["dedup_key"]
    assert column.unique is True
    assert column.nullable is False


def test_scoring_failures_dedup_key_is_unique_and_not_nullable() -> None:
    column = Base.metadata.tables["scoring_failures"].columns["dedup_key"]
    assert column.unique is True
    assert column.nullable is False
