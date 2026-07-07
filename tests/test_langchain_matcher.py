import httpx
import pytest
from app.connectors.solid_jobs import map_solid_jobs_offer
from app.llm.matcher import (
    DIMENSION_WEIGHTS,
    GradeScale,
    MatcherError,
    _cap_grade_for_deal_breaker,
    _deal_breaker_hit,
    _MatcherOutput,
    _weighted_total,
    build_grade_scale,
    is_langchain_source,
    score_offer_with_langchain,
)
from app.schemas.offer import Offer
from app.schemas.profile import Profile
from app.schemas.scoring_config import ScoringConfig
from langchain_core.messages import BaseMessage

_STRONG_OUTPUT_KWARGS = {
    "skill_match": 0.95,
    "salary_fit": 0.9,
    "seniority_fit": 0.9,
    "work_mode_location": 0.9,
    "contract_type": 0.9,
    "red_flags": 0.95,
    "rationale": (
        "skill match (30%): strong overlap. salary fit (25%): within target. "
        "seniority fit (15%): matches. work mode/location (15%): remote as preferred. "
        "contract type (10%): B2B as preferred. red flags (5%): none found."
    ),
}

_LOW_OUTPUT_KWARGS = {
    "skill_match": 0.1,
    "salary_fit": 0.1,
    "seniority_fit": 0.1,
    "work_mode_location": 0.1,
    "contract_type": 0.1,
    "red_flags": 0.1,
    "rationale": "Poor fit across every dimension.",
}


def _profile(**overrides: object) -> Profile:
    defaults: dict[str, object] = {
        "salary_min": 15000,
        "salary_target": 20000,
        "deal_breakers": [],
    }
    defaults.update(overrides)
    return Profile(**defaults)


def _offer(**overrides: object) -> Offer:
    defaults: dict[str, object] = {
        "source_id": 1,
        "title": "Senior Backend Engineer",
        "company": "Acme",
        "description": "A great remote B2B role.",
        "contract_type": "B2B",
        "location": "Warsaw",
    }
    defaults.update(overrides)
    return Offer(**defaults)


class _FakeChain:
    def __init__(self, output: _MatcherOutput) -> None:
        self._output = output

    async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
        return self._output


class _FailingChain:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
        raise self._exc


@pytest.mark.asyncio
async def test_score_offer_with_langchain_produces_valid_match_score_with_langchain_engine() -> (
    None
):
    output = _MatcherOutput(**_STRONG_OUTPUT_KWARGS)

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=_profile(),
        offer=_offer(),
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.engine == "langchain"
    assert set(score.dimensions) == set(DIMENSION_WEIGHTS)


@pytest.mark.asyncio
async def test_score_offer_with_langchain_caps_grade_at_d_when_deal_breaker_matched() -> None:
    output = _MatcherOutput(**_STRONG_OUTPUT_KWARGS)
    profile = _profile(deal_breakers=["on-site only"])
    offer = _offer(description="This is an On-Site Only role, no exceptions.")

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=profile,
        offer=offer,
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.grade in ("D", "F")
    assert "on-site only" in score.rationale.lower()


@pytest.mark.asyncio
async def test_score_offer_with_langchain_no_deal_breaker_high_fit_scores_well() -> None:
    output = _MatcherOutput(**_STRONG_OUTPUT_KWARGS)

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=_profile(),
        offer=_offer(),
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.grade in ("A", "B")


@pytest.mark.asyncio
async def test_score_offer_with_langchain_low_fit_scores_poorly() -> None:
    output = _MatcherOutput(**_LOW_OUTPUT_KWARGS)

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=_profile(),
        offer=_offer(),
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.grade in ("D", "F")


@pytest.mark.asyncio
async def test_score_offer_with_langchain_missing_salary_scores_conservatively() -> None:
    output = _MatcherOutput(**{**_STRONG_OUTPUT_KWARGS, "salary_fit": 0.95})
    profile = _profile(salary_min=None, salary_target=None)

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=profile,
        offer=_offer(),
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.dimensions["salary_fit"] <= 0.5
    assert "salary" in score.rationale.lower()


@pytest.mark.asyncio
async def test_score_offer_with_langchain_wraps_llm_connection_failure() -> None:
    with pytest.raises(MatcherError):
        await score_offer_with_langchain(
            offer_id=1,
            profile_id=2,
            profile=_profile(),
            offer=_offer(),
            chain_factory=lambda: _FailingChain(httpx.HTTPError("connection refused")),
        )


@pytest.mark.asyncio
async def test_score_offer_with_langchain_wraps_unexpected_failure() -> None:
    with pytest.raises(MatcherError):
        await score_offer_with_langchain(
            offer_id=1,
            profile_id=2,
            profile=_profile(),
            offer=_offer(),
            chain_factory=lambda: _FailingChain(RuntimeError("something broke")),
        )


def test_weighted_total_matches_manual_calculation() -> None:
    output = _MatcherOutput(
        skill_match=0.8,
        salary_fit=0.6,
        seniority_fit=1.0,
        work_mode_location=0.4,
        contract_type=0.2,
        red_flags=1.0,
        rationale="irrelevant",
    )

    expected = 0.8 * 0.30 + 0.6 * 0.25 + 1.0 * 0.15 + 0.4 * 0.15 + 0.2 * 0.10 + 1.0 * 0.05

    assert _weighted_total(output) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("weighted_total", "expected_grade"),
    [
        (0.85, "A"),
        (0.849999, "B"),
        (0.70, "B"),
        (0.699999, "C"),
        (0.55, "C"),
        (0.549999, "D"),
        (0.40, "D"),
        (0.399999, "F"),
        (0.0, "F"),
    ],
)
def test_grade_scale_boundaries(weighted_total: float, expected_grade: str) -> None:
    assert GradeScale().grade_for(weighted_total) == expected_grade


def test_grade_scale_accepts_custom_thresholds() -> None:
    custom_scale = GradeScale(thresholds=((0.5, "A"), (0.3, "B")))

    assert custom_scale.grade_for(0.5) == "A"
    assert custom_scale.grade_for(0.35) == "B"
    assert custom_scale.grade_for(0.1) == "F"


def test_build_grade_scale_uses_config_thresholds() -> None:
    config = ScoringConfig(grade_a=0.9, grade_b=0.75, grade_c=0.6, grade_d=0.45)
    scale = build_grade_scale(config)

    assert scale.grade_for(0.9) == "A"
    assert scale.grade_for(0.5) == "D"


def test_build_grade_scale_below_grade_d_returns_f() -> None:
    config = ScoringConfig(grade_a=0.9, grade_b=0.75, grade_c=0.6, grade_d=0.45)
    scale = build_grade_scale(config)

    assert scale.grade_for(0.4) == "F"


@pytest.mark.parametrize(
    ("grade", "expected"),
    [("A", "D"), ("B", "D"), ("C", "D"), ("D", "D"), ("F", "F")],
)
def test_cap_grade_for_deal_breaker_only_lowers_never_raises(grade: str, expected: str) -> None:
    assert _cap_grade_for_deal_breaker(grade) == expected  # type: ignore[arg-type]


def test_deal_breaker_word_boundary_avoids_java_javascript_false_positive() -> None:
    profile = _profile(deal_breakers=["Java"])
    offer = _offer(description="We use JavaScript and TypeScript extensively.")

    assert _deal_breaker_hit(profile, offer) is None


def test_deal_breaker_matches_punctuation_variants() -> None:
    profile = _profile(deal_breakers=["on-site only"])

    assert _deal_breaker_hit(profile, _offer(description="This is onsite only.")) == "on-site only"
    assert _deal_breaker_hit(profile, _offer(description="This is on site only.")) == "on-site only"


@pytest.mark.parametrize(
    ("connector", "expected"),
    [
        ("justjoinit", True),
        ("nofluffjobs", True),
        ("solid_jobs", True),
        ("unknown-connector", False),
        (None, False),
    ],
)
def test_is_langchain_source_true_for_all_three_connectors_false_for_unknown(
    connector: str | None, expected: bool
) -> None:
    assert is_langchain_source(connector) is expected


@pytest.mark.asyncio
async def test_score_offer_with_langchain_handles_solid_jobs_offer_missing_optional_fields() -> (
    None
):
    raw = {"title": "Backend Engineer", "company": "Acme"}
    mapped_fields = map_solid_jobs_offer(1, raw)
    offer = Offer(**mapped_fields)

    output = _MatcherOutput(**_STRONG_OUTPUT_KWARGS)

    score = await score_offer_with_langchain(
        offer_id=1,
        profile_id=2,
        profile=_profile(),
        offer=offer,
        chain_factory=lambda: _FakeChain(output),
    )

    assert score.engine == "langchain"
    assert set(score.dimensions) == set(DIMENSION_WEIGHTS)


def test_dimension_weights_sum_to_one() -> None:
    assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)
