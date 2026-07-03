from collections.abc import AsyncGenerator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.db.models import MatchScore, Profile, Source
from app.db.models import Offer as OfferModel
from app.ingestion.persist import ingest_offer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_source(session: AsyncSession, connector: str | None = None) -> int:
    source = Source(name=f"test-source-{uuid4()}", connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source.id


def _unique_url(path: str) -> str:
    return f"https://example.com/jobs/{uuid4()}/{path}"


async def _delete_sources_with_offers(session: AsyncSession, source_ids: list[int]) -> None:
    # Sources carrying a non-null connector are picked up by connector.is_not(None)
    # assertions elsewhere (e.g. test_scheduler_ensure_sources.py's exact-set check),
    # so any test that gives a Source a real-looking connector must clean up after itself.
    await session.execute(delete(OfferModel).where(OfferModel.source_id.in_(source_ids)))
    await session.execute(delete(Source).where(Source.id.in_(source_ids)))
    await session.commit()


async def _create_offer(session: AsyncSession, source_id: int, **overrides: object) -> int:
    mapped_fields: dict[str, object] = {
        "source_id": source_id,
        "title": "Backend Engineer",
        "company": "Acme",
        "canonical_url": _unique_url("offer"),
    }
    mapped_fields.update(overrides)
    result = await ingest_offer(session, mapped_fields, raw_payload={})
    assert result is not None
    return result[0].id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_returns_all_when_no_filters_given(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_a = await _create_source(db_session)
    source_b = await _create_source(db_session)
    offer_a = await _create_offer(db_session, source_a)
    offer_b = await _create_offer(db_session, source_b)
    await db_session.commit()

    response = await client.get("/offers")

    assert response.status_code == 200
    ids = {entry["id"] for entry in response.json()}
    assert offer_a in ids
    assert offer_b in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_source(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector_a = f"justjoinit-{uuid4()}"
    connector_b = f"nofluffjobs-{uuid4()}"
    source_a = await _create_source(db_session, connector=connector_a)
    source_b = await _create_source(db_session, connector=connector_b)
    offer_a = await _create_offer(db_session, source_a)
    offer_b = await _create_offer(db_session, source_b)
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector_a})

        assert response.status_code == 200
        ids = {entry["id"] for entry in response.json()}
        assert offer_a in ids
        assert offer_b not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_remote(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    remote_offer = await _create_offer(db_session, source_id, remote=True)
    onsite_offer = await _create_offer(db_session, source_id, remote=False)
    await db_session.commit()

    remote_response = await client.get("/offers", params={"remote": "true"})
    onsite_response = await client.get("/offers", params={"remote": "false"})

    remote_ids = {entry["id"] for entry in remote_response.json()}
    onsite_ids = {entry["id"] for entry in onsite_response.json()}
    assert remote_offer in remote_ids
    assert onsite_offer not in remote_ids
    assert onsite_offer in onsite_ids
    assert remote_offer not in onsite_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_seniority_substring_match(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    senior_offer = await _create_offer(db_session, source_id, seniority="senior, lead")
    junior_offer = await _create_offer(db_session, source_id, seniority="junior")
    await db_session.commit()

    response = await client.get("/offers", params={"seniority": "senior"})

    ids = {entry["id"] for entry in response.json()}
    assert senior_offer in ids
    assert junior_offer not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_min_salary_meets_or_exceeds(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    above_max = await _create_offer(db_session, source_id, salary_max=20000)
    below_max = await _create_offer(db_session, source_id, salary_max=10000)
    fallback_min = await _create_offer(db_session, source_id, salary_min=18000, salary_max=None)
    await db_session.commit()

    response = await client.get("/offers", params={"min_salary": 15000})

    ids = {entry["id"] for entry in response.json()}
    assert above_max in ids
    assert fallback_min in ids
    assert below_max not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_grade(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    scored_offer = await _create_offer(db_session, source_id)
    unscored_offer = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add(
        MatchScore(
            offer_id=scored_offer,
            profile_id=profile.id,
            engine="langchain",
            grade="A",
            dimensions={},
        )
    )
    await db_session.commit()

    response = await client.get("/offers", params={"grade": "A"})

    ids = {entry["id"] for entry in response.json()}
    assert scored_offer in ids
    assert unscored_offer not in ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_unknown_source_filter_returns_empty_list_not_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/offers", params={"source": "totally-unknown-connector"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_combines_source_and_remote_filters(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector_a = f"source-a-{uuid4()}"
    connector_b = f"source-b-{uuid4()}"
    source_a = await _create_source(db_session, connector=connector_a)
    source_b = await _create_source(db_session, connector=connector_b)
    a_remote = await _create_offer(db_session, source_a, remote=True)
    a_onsite = await _create_offer(db_session, source_a, remote=False)
    b_remote = await _create_offer(db_session, source_b, remote=True)
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector_a, "remote": "true"})

        ids = {entry["id"] for entry in response.json()}
        assert ids == {a_remote}
        assert a_onsite not in ids
        assert b_remote not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_detail_includes_normalised_fields_and_raw_payload(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    raw_payload = {"id": "abc123", "nested": {"k": "v"}}
    result = await ingest_offer(
        db_session,
        {
            "source_id": source_id,
            "title": "Backend Engineer",
            "company": "Acme",
            "canonical_url": _unique_url("detail"),
        },
        raw_payload=raw_payload,
    )
    await db_session.commit()
    assert result is not None
    offer_id = result[0].id

    response = await client.get(f"/offers/{offer_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Backend Engineer"
    assert body["company"] == "Acme"
    assert body["raw_payload"] == raw_payload


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_unknown_id_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/offers/999999999")

    assert response.status_code == 404
    assert "999999999" in response.json()["detail"]
