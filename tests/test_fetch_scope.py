from app.ingestion.fetch_scope import (
    FETCH_SCOPE_ALL,
    FETCH_SCOPE_FILTERED,
    resolve_fetch_scope,
    resolve_fetch_scope_mode,
)
from app.schemas.profile import Profile


def test_resolve_fetch_scope_mode_defaults_to_all_for_missing_key() -> None:
    assert resolve_fetch_scope_mode(None) == FETCH_SCOPE_ALL
    assert resolve_fetch_scope_mode({}) == FETCH_SCOPE_ALL


def test_resolve_fetch_scope_mode_defaults_to_all_for_malformed_shape() -> None:
    assert resolve_fetch_scope_mode({"mode": "bogus"}) == FETCH_SCOPE_ALL


def test_resolve_fetch_scope_mode_recognizes_filtered() -> None:
    assert resolve_fetch_scope_mode({"mode": "filtered"}) == FETCH_SCOPE_FILTERED


def test_resolve_fetch_scope_all_mode_ignores_profile() -> None:
    resolution = resolve_fetch_scope("all", profile=None)

    assert resolution.mode == FETCH_SCOPE_ALL
    assert resolution.terms == []
    assert resolution.blocked_reason is None


def test_resolve_fetch_scope_filtered_blocks_on_missing_profile() -> None:
    resolution = resolve_fetch_scope("filtered", profile=None)

    assert resolution.mode == FETCH_SCOPE_FILTERED
    assert resolution.terms == []
    assert resolution.blocked_reason is not None


def test_resolve_fetch_scope_filtered_blocks_on_zero_hard_skills() -> None:
    profile = Profile(skills=[{"name": "Python", "hard": False}])

    resolution = resolve_fetch_scope("filtered", profile)

    assert resolution.terms == []
    assert resolution.blocked_reason is not None


def test_resolve_fetch_scope_filtered_returns_or_terms_for_multiple_hard_skills() -> None:
    profile = Profile(
        skills=[
            {"name": "Python", "hard": True},
            {"name": "Go", "hard": True},
            {"name": "SQL", "hard": False},
        ]
    )

    resolution = resolve_fetch_scope("filtered", profile)

    assert resolution.terms == ["Python", "Go"]
    assert resolution.blocked_reason is None
