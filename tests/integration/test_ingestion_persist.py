from uuid import uuid4

import pytest
from app.db.models import IngestionFailure, Source
from app.db.models import Offer as OfferModel
from app.ingestion.persist import ingest_offer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_source(session: AsyncSession) -> int:
    source = Source(name=f"test-source-{uuid4()}", config_json={})
    session.add(source)
    await session.flush()
    return source.id


def _unique_url(path: str) -> str:
    # dedup_hash is unique across the whole offers table (not scoped per source), and
    # these tests commit real rows to a persistent DB, so a fixed literal URL would
    # collide with rows left behind by other tests or previous suite runs.
    return f"https://example.com/jobs/{uuid4()}/{path}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_persists_raw_payload_byte_for_byte(db_session: AsyncSession) -> None:
    source_id = await _create_source(db_session)
    mapped_fields = {
        "source_id": source_id,
        "title": f"Backend Engineer {uuid4()}",
        "company": "Acme",
        "canonical_url": _unique_url("1"),
    }
    raw_payload = {"id": "abc123", "nested": {"k": "v"}}

    result = await ingest_offer(db_session, mapped_fields, raw_payload)
    await db_session.commit()

    assert result is not None
    row, _ = result
    assert row.raw_payload == {"id": "abc123", "nested": {"k": "v"}}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_dedups_by_canonical_url_on_reingest(db_session: AsyncSession) -> None:
    source_id = await _create_source(db_session)
    mapped_fields = {
        "source_id": source_id,
        "title": f"Backend Engineer {uuid4()}",
        "company": "Acme",
        "canonical_url": _unique_url("1"),
    }

    first = await ingest_offer(db_session, mapped_fields, raw_payload={"seen": "first"})
    await db_session.commit()
    second = await ingest_offer(db_session, mapped_fields, raw_payload={"seen": "second"})
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is False

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_dedups_by_fallback_when_no_canonical_url(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"
    mapped_fields = {
        "source_id": source_id,
        "title": unique_title,
        "company": "Acme",
        "location": "Warsaw",
    }

    await ingest_offer(db_session, mapped_fields, raw_payload={})
    await db_session.commit()
    await ingest_offer(db_session, mapped_fields, raw_payload={})
    await db_session.commit()

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_does_not_merge_distinct_offers(db_session: AsyncSession) -> None:
    source_id = await _create_source(db_session)

    await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"Backend Engineer {uuid4()}",
            "company": "Acme",
            "canonical_url": _unique_url("1"),
        },
        raw_payload={},
    )
    await db_session.commit()
    await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"Data Engineer {uuid4()}",
            "company": "Widgets Inc",
            "canonical_url": _unique_url("2"),
        },
        raw_payload={},
    )
    await db_session.commit()

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_returns_none_and_does_not_persist_invalid_offer(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)

    result = await ingest_offer(
        db_session, {"source_id": source_id, "company": "Acme"}, raw_payload={}
    )
    await db_session.commit()

    assert result is None
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 0

    failures = (
        (
            await db_session.execute(
                select(IngestionFailure).where(IngestionFailure.source_id == source_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(failures) == 1
    assert failures[0].failure_type == "validation_failed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_reingest_returns_same_row_id(db_session: AsyncSession) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"
    mapped_fields = {
        "source_id": source_id,
        "title": unique_title,
        "company": "Acme",
        "canonical_url": _unique_url("1"),
    }

    first = await ingest_offer(db_session, mapped_fields, raw_payload={})
    await db_session.commit()
    second = await ingest_offer(db_session, mapped_fields, raw_payload={})
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert first[0].id == second[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_skips_content_duplicate_across_different_canonical_urls(
    db_session: AsyncSession,
) -> None:
    source_a = await _create_source(db_session)
    source_b = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_a,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_b,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("2"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is False
    assert second[0].id == first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_treats_both_null_salary_as_matching(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("1"),
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("2"),
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is False
    assert second[0].id == first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_does_not_skip_when_salary_min_differs(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("2"),
            "salary_min": 12000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is True
    assert second[0].id != first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_does_not_skip_when_currency_differs(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("2"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "USD",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is True
    assert second[0].id != first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_does_not_skip_when_title_differs(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_suffix = uuid4()

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"Backend Engineer {unique_suffix}",
            "company": "Acme",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"Data Engineer {unique_suffix}",
            "company": "Acme",
            "canonical_url": _unique_url("2"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is True
    assert second[0].id != first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_does_not_skip_when_company_differs(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": f"Acme {uuid4()}",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": f"Widgets Inc {uuid4()}",
            "canonical_url": _unique_url("2"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is True
    assert second[0].id != first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_content_duplicate_check_is_case_sensitive(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_suffix = uuid4()

    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"backend engineer {unique_suffix}",
            "company": "acme",
            "canonical_url": _unique_url("1"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": f"BACKEND ENGINEER {unique_suffix}",
            "company": "ACME",
            "canonical_url": _unique_url("2"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is True
    assert second[0].id != first[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_offer_content_duplicate_independent_of_dedup_hash_path(
    db_session: AsyncSession,
) -> None:
    source_id = await _create_source(db_session)
    unique_title = f"Backend Engineer {uuid4()}"

    # Two distinct, comparable canonical_urls: the URL-based dedup_hash path alone
    # would NOT catch this as a duplicate, only the content-based check should.
    first = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("mirror-a"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()
    second = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": unique_title,
            "company": "Acme",
            "canonical_url": _unique_url("mirror-b"),
            "salary_min": 10000,
            "salary_max": 15000,
            "salary_currency": "PLN",
        },
        raw_payload={},
    )
    await db_session.commit()

    assert first is not None
    assert second is not None
    assert second[1] is False
    assert second[0].id == first[0].id

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source_id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
