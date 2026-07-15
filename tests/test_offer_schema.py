from datetime import UTC, datetime

import pytest
from app.schemas.offer import Offer
from pydantic import ValidationError


def test_offer_accepts_valid_payload_with_all_fields() -> None:
    posted_at = datetime(2026, 6, 1, tzinfo=UTC)

    offer = Offer(
        source_id=1,
        canonical_url="https://example.com/jobs/1",
        title="Backend Engineer",
        company="Acme",
        location="Warsaw",
        remote=True,
        seniority="mid",
        salary_min=15000,
        salary_max=20000,
        salary_currency="PLN",
        contract_type="b2b",
        posted_at=posted_at,
        description="Great role",
        industry_tags=["fintech", "backend"],
    )

    dumped = offer.model_dump()
    assert dumped["source_id"] == 1
    assert dumped["canonical_url"] == "https://example.com/jobs/1"
    assert dumped["title"] == "Backend Engineer"
    assert dumped["company"] == "Acme"
    assert dumped["location"] == "Warsaw"
    assert dumped["remote"] is True
    assert dumped["seniority"] == "mid"
    assert dumped["salary_min"] == 15000
    assert dumped["salary_max"] == 20000
    assert dumped["salary_currency"] == "PLN"
    assert dumped["contract_type"] == "b2b"
    assert dumped["posted_at"] == posted_at
    assert dumped["description"] == "Great role"
    assert dumped["industry_tags"] == ["fintech", "backend"]


def test_offer_accepts_minimal_payload_and_applies_defaults() -> None:
    offer = Offer(source_id=1, title="Backend Engineer", company="Acme")

    assert offer.remote is False
    assert offer.salary_currency == "PLN"
    assert offer.canonical_url is None
    assert offer.description is None
    assert offer.industry_tags == []


def test_offer_rejects_missing_title() -> None:
    with pytest.raises(ValidationError):
        Offer(source_id=1, company="Acme")  # type: ignore[call-arg]


def test_offer_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        Offer(source_id=1, title="   ", company="Acme")


def test_offer_rejects_missing_company() -> None:
    with pytest.raises(ValidationError):
        Offer(source_id=1, title="Backend Engineer")  # type: ignore[call-arg]


def test_offer_normalizes_empty_canonical_url_to_none() -> None:
    offer = Offer(source_id=1, title="Backend Engineer", company="Acme", canonical_url="   ")

    assert offer.canonical_url is None


def test_offer_rejects_salary_min_greater_than_max() -> None:
    with pytest.raises(ValidationError, match="salary_min must not exceed salary_max"):
        Offer(
            source_id=1,
            title="Backend Engineer",
            company="Acme",
            salary_min=20000,
            salary_max=10000,
        )


def test_offer_accepts_salary_min_equal_to_max() -> None:
    offer = Offer(
        source_id=1,
        title="Backend Engineer",
        company="Acme",
        salary_min=15000,
        salary_max=15000,
    )

    assert offer.salary_min == offer.salary_max == 15000


def test_offer_rejects_title_exceeding_max_length() -> None:
    with pytest.raises(ValidationError):
        Offer(source_id=1, title="x" * 501, company="Acme")


def test_offer_accepts_location_exceeding_255_chars() -> None:
    """BUG44: joined multi-region locations (e.g. We Work Remotely) can exceed 255 chars;
    location must not be capped or the whole offer gets dropped rather than just truncated."""
    long_location = ", ".join(f"Country {i}" for i in range(40))
    assert len(long_location) > 255

    offer = Offer(source_id=1, title="Backend Engineer", company="Acme", location=long_location)

    assert offer.location == long_location
