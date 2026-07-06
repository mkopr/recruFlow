import pytest
from app.schemas.scoring_config import ScoringConfig
from pydantic import ValidationError


def test_scoring_config_accepts_valid_descending_payload() -> None:
    config = ScoringConfig(grade_a=0.85, grade_b=0.70, grade_c=0.55, grade_d=0.40)

    assert config.grade_a == 0.85
    assert config.grade_d == 0.40


def test_scoring_config_rejects_non_descending_grade_b() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(grade_a=0.5, grade_b=0.6, grade_c=0.3, grade_d=0.1)


def test_scoring_config_rejects_non_descending_grade_c() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(grade_a=0.8, grade_b=0.5, grade_c=0.6, grade_d=0.1)


def test_scoring_config_rejects_non_descending_grade_d() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(grade_a=0.8, grade_b=0.6, grade_c=0.3, grade_d=0.4)


def test_scoring_config_rejects_grade_d_not_greater_than_zero() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(grade_a=0.8, grade_b=0.6, grade_c=0.3, grade_d=0)


def test_scoring_config_rejects_value_above_one() -> None:
    with pytest.raises(ValidationError):
        ScoringConfig(grade_a=1.01, grade_b=0.6, grade_c=0.3, grade_d=0.1)


def test_scoring_config_accepts_grade_a_exactly_one() -> None:
    config = ScoringConfig(grade_a=1.0, grade_b=0.6, grade_c=0.3, grade_d=0.1)

    assert config.grade_a == 1.0
