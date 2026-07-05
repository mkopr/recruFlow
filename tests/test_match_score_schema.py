from datetime import datetime

import pytest
from app.schemas.match_score import MatchScore
from pydantic import ValidationError


def test_match_score_accepts_valid_payload_with_langchain_engine() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        grade="B",
        dimensions={"skill_match": 0.8},
        rationale="Good skill overlap",
    )

    assert score.model_dump()["engine"] == "langchain"


def test_match_score_accepts_valid_payload_with_sjctl_engine() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="sjctl",
        grade="B",
        dimensions={"skill_match": 0.8},
        rationale="Good skill overlap",
    )

    assert score.model_dump()["engine"] == "sjctl"


def test_match_score_rejects_invalid_engine() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=1,
            engine="other",
            grade="B",
            dimensions={},
            rationale="text",
        )


def test_match_score_rejects_invalid_grade() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=1,
            engine="langchain",
            grade="Z",
            dimensions={},
            rationale="text",
        )


def test_match_score_accepts_arbitrary_dimension_keys_without_dropping() -> None:
    dimensions = {"custom_dimension_one": 1.5, "custom_dimension_two": 0}

    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        grade="A",
        dimensions=dimensions,
        rationale="text",
    )

    assert score.dimensions == {"custom_dimension_one": 1.5, "custom_dimension_two": 0}


def test_match_score_rejects_non_positive_offer_id() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=0,
            profile_id=1,
            engine="langchain",
            grade="A",
            dimensions={},
            rationale="text",
        )


def test_match_score_rejects_non_positive_profile_id() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=0,
            engine="langchain",
            grade="A",
            dimensions={},
            rationale="text",
        )


def test_match_score_created_at_defaults_when_omitted() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        grade="A",
        dimensions={},
        rationale="text",
    )

    assert isinstance(score.created_at, datetime)


def test_match_score_rejects_non_numeric_dimension_value() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=1,
            engine="langchain",
            grade="A",
            dimensions={"skill_match": "high"},
            rationale="text",
        )
