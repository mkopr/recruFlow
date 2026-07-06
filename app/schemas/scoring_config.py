from pydantic import BaseModel, Field, model_validator


class ScoringConfig(BaseModel):
    grade_a: float = Field(gt=0, le=1)
    grade_b: float = Field(gt=0, le=1)
    grade_c: float = Field(gt=0, le=1)
    grade_d: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _check_descending_thresholds(self) -> "ScoringConfig":
        if not (self.grade_a > self.grade_b > self.grade_c > self.grade_d):
            raise ValueError(
                "thresholds must be strictly descending: grade_a > grade_b > grade_c > grade_d"
            )
        return self


DEFAULT_SCORING_CONFIG = ScoringConfig(grade_a=0.85, grade_b=0.70, grade_c=0.55, grade_d=0.40)
