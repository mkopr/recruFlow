from datetime import datetime

import pytest
from app.schemas.match_score import MatchScore
from pydantic import ValidationError


def test_match_score_accepts_valid_payload_with_langchain_engine() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        score_percent=75,
        dimensions={"skill_match": 0.8},
        rationale="Good skill overlap",
    )

    assert score.model_dump()["engine"] == "langchain"


def test_match_score_accepts_valid_payload_with_sjctl_engine() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="sjctl",
        score_percent=75,
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
            score_percent=75,
            dimensions={},
            rationale="text",
        )


def test_match_score_rejects_score_percent_below_zero() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=1,
            engine="langchain",
            score_percent=-1,
            dimensions={},
            rationale="text",
        )


def test_match_score_rejects_score_percent_above_100() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=1,
            engine="langchain",
            score_percent=101,
            dimensions={},
            rationale="text",
        )


def test_match_score_accepts_arbitrary_dimension_keys_without_dropping() -> None:
    dimensions = {"custom_dimension_one": 1.5, "custom_dimension_two": 0}

    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        score_percent=90,
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
            score_percent=90,
            dimensions={},
            rationale="text",
        )


def test_match_score_rejects_non_positive_profile_id() -> None:
    with pytest.raises(ValidationError):
        MatchScore(
            offer_id=1,
            profile_id=0,
            engine="langchain",
            score_percent=90,
            dimensions={},
            rationale="text",
        )


def test_match_score_created_at_defaults_when_omitted() -> None:
    score = MatchScore(
        offer_id=1,
        profile_id=1,
        engine="langchain",
        score_percent=90,
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
            score_percent=90,
            dimensions={"skill_match": "high"},
            rationale="text",
        )


def test_match_score_has_no_grade_field() -> None:
    score = MatchScore.model_validate(
        {
            "offer_id": 1,
            "profile_id": 1,
            "engine": "langchain",
            "score_percent": 80,
            "dimensions": {},
            "rationale": "text",
            "grade": "B",
        }
    )

    assert hasattr(score, "grade") is False
    assert "grade" not in score.model_dump()
