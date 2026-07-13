from datetime import UTC, datetime

from app.api.routes.offers import _match_score_response, _offer_detail, _offer_summary
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel


def test_offer_summary_maps_all_scalar_fields() -> None:
    posted_at = datetime(2026, 6, 1, tzinfo=UTC)
    created_at = datetime(2026, 6, 2, tzinfo=UTC)
    offer = OfferModel(
        id=1,
        source_id=2,
        external_id="ext-1",
        canonical_url="https://example.com/jobs/1",
        dedup_hash="hash",
        title="Backend Engineer",
        company="Acme",
        location="Warsaw",
        remote=True,
        seniority="senior, lead",
        salary_min=15000,
        salary_max=25000,
        salary_currency="PLN",
        contract_type="B2B",
        description="some text",
        posted_at=posted_at,
        industry_tags=["fintech"],
        applied=False,
        hide=False,
        raw_payload={},
        created_at=created_at,
    )

    result = _offer_summary(offer, "justjoinit", 77)

    assert result.id == 1
    assert result.score_percent == 77
    assert result.source == "justjoinit"
    assert result.external_id == "ext-1"
    assert result.canonical_url == "https://example.com/jobs/1"
    assert result.title == "Backend Engineer"
    assert result.company == "Acme"
    assert result.location == "Warsaw"
    assert result.remote is True
    assert result.seniority == "senior, lead"
    assert result.salary_min == 15000
    assert result.salary_max == 25000
    assert result.salary_currency == "PLN"
    assert result.contract_type == "B2B"
    assert result.posted_at == posted_at
    assert result.industry_tags == ["fintech"]
    assert result.created_at == created_at


def test_offer_summary_uses_given_source_label_verbatim() -> None:
    offer = OfferModel(
        id=1,
        title="Backend Engineer",
        company="Acme",
        remote=False,
        applied=False,
        hide=False,
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    result = _offer_summary(offer, "solid_jobs")

    assert result.source == "solid_jobs"
    assert result.external_id is None
    assert result.canonical_url is None
    assert result.location is None
    assert result.seniority is None
    assert result.salary_min is None
    assert result.salary_max is None
    assert result.contract_type is None
    assert result.posted_at is None
    assert result.industry_tags == []
    assert result.score_percent is None


def test_offer_summary_includes_applied_hide_notes() -> None:
    offer = OfferModel(
        id=1,
        title="Backend Engineer",
        company="Acme",
        remote=False,
        applied=True,
        hide=False,
        notes="some notes",
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    result = _offer_summary(offer, "justjoinit")

    assert result.applied is True
    assert result.hide is False
    assert result.notes == "some notes"


def test_offer_summary_notes_defaults_to_none() -> None:
    offer = OfferModel(
        id=1,
        title="Backend Engineer",
        company="Acme",
        remote=False,
        applied=False,
        hide=False,
        notes=None,
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    result = _offer_summary(offer, "justjoinit")

    assert result.notes is None


def test_offer_detail_includes_description_and_raw_payload() -> None:
    offer = OfferModel(
        id=1,
        title="Backend Engineer",
        company="Acme",
        remote=False,
        applied=False,
        hide=False,
        description="some text",
        raw_payload={"nested": {"k": "v"}},
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
        updated_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    result = _offer_detail(offer, "nofluffjobs")

    assert result.raw_payload == {"nested": {"k": "v"}}
    assert result.description == "some text"
    assert result.source == "nofluffjobs"
    assert result.title == "Backend Engineer"
    assert result.company == "Acme"


def test_offer_detail_raw_payload_defaults_are_not_silently_dropped() -> None:
    offer = OfferModel(
        id=1,
        title="Backend Engineer",
        company="Acme",
        remote=False,
        applied=False,
        hide=False,
        raw_payload={},
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
        updated_at=datetime(2026, 6, 3, tzinfo=UTC),
    )

    result = _offer_detail(offer, "justjoinit")

    assert result.raw_payload == {}


def test_match_score_response_maps_all_fields() -> None:
    created_at = datetime(2026, 6, 2, tzinfo=UTC)
    row = MatchScoreModel(
        id=1,
        offer_id=2,
        profile_id=3,
        engine="langchain",
        score_percent=62,
        dimensions={"salary_fit": 0.6},
        rationale="text",
        created_at=created_at,
    )

    result = _match_score_response(row)

    assert result.id == 1
    assert result.offer_id == 2
    assert result.profile_id == 3
    assert result.engine == "langchain"
    assert result.score_percent == 62
    assert result.dimensions == {"salary_fit": 0.6}
    assert result.rationale == "text"
    assert result.created_at == created_at


def test_match_score_response_allows_null_rationale() -> None:
    row = MatchScoreModel(
        id=1,
        offer_id=2,
        profile_id=3,
        engine="langchain",
        score_percent=92,
        dimensions={},
        rationale=None,
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )

    result = _match_score_response(row)

    assert result.rationale is None
