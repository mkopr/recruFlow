from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.connectors.http import BlockedFetchError
from app.db.models import IngestionFailure, ScoringFailure
from app.dlq import retry as dlq_retry_module
from app.schemas.match_score import MatchScore as MatchScoreSchema
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_langchain_matcher_batch import _create_profile
from tests.integration.test_offers_routes import (
    _create_offer,
    _create_source,
    _delete_sources_with_offers,
    _unique_url,
)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _seed_ingestion_failure(
    session: AsyncSession,
    *,
    source_id: int,
    dedup_key: str,
    failure_type: str = "run_fetch_failed",
    error_message: str = "boom",
    raw_payload: dict[str, object] | None = None,
    status: str = "open",
    occurred_at: datetime | None = None,
    url: str | None = None,
    blocked_status: int | None = None,
) -> IngestionFailure:
    row = IngestionFailure(
        source_id=source_id,
        dedup_key=dedup_key,
        failure_type=failure_type,
        error_message=error_message,
        raw_payload=raw_payload,
        status=status,
        occurred_at=occurred_at or datetime.now(UTC),
        url=url,
        blocked_status=blocked_status,
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_scoring_failure(
    session: AsyncSession,
    *,
    offer_id: int,
    profile_id: int,
    dedup_key: str,
    error_message: str = "boom",
    status: str = "open",
    occurred_at: datetime | None = None,
) -> ScoringFailure:
    row = ScoringFailure(
        offer_id=offer_id,
        profile_id=profile_id,
        dedup_key=dedup_key,
        failure_type="scoring_failed",
        error_message=error_message,
        status=status,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row


async def _delete_failures(
    session: AsyncSession, *, ingestion_ids: list[int], scoring_ids: list[int]
) -> None:
    if ingestion_ids:
        await session.execute(
            delete(IngestionFailure).where(IngestionFailure.id.in_(ingestion_ids))
        )
    if scoring_ids:
        await session.execute(delete(ScoringFailure).where(ScoringFailure.id.in_(scoring_ids)))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_ingestion_failures_paginates_and_filters(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    now = datetime.now(UTC)
    rows = [
        await _seed_ingestion_failure(
            db_session,
            source_id=source_id,
            dedup_key=f"source:{source_id}:{i}",
            failure_type="page_fetch_failed" if i == 0 else "run_fetch_failed",
            occurred_at=now - timedelta(minutes=i),
        )
        for i in range(3)
    ]
    await db_session.commit()

    try:
        page_1 = await client.get("/failures/ingestion", params={"source": connector, "limit": 2})
        assert page_1.status_code == 200
        body_1 = page_1.json()
        assert body_1["total"] == 3
        assert [item["id"] for item in body_1["items"]] == [rows[0].id, rows[1].id]

        page_2 = await client.get(
            "/failures/ingestion", params={"source": connector, "limit": 2, "offset": 2}
        )
        body_2 = page_2.json()
        assert [item["id"] for item in body_2["items"]] == [rows[2].id]

        filtered = await client.get(
            "/failures/ingestion",
            params={"source": connector, "failure_type": "page_fetch_failed"},
        )
        filtered_body = filtered.json()
        assert filtered_body["total"] == 1
        assert filtered_body["items"][0]["id"] == rows[0].id
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id for row in rows], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_scoring_failures_paginates_and_filters(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    profile = await _create_profile(db_session)
    now = datetime.now(UTC)
    rows = [
        await _seed_scoring_failure(
            db_session,
            offer_id=offer_id,
            profile_id=profile.id,
            dedup_key=f"offer:{offer_id}:profile:{profile.id}:{i}",
            occurred_at=now - timedelta(minutes=i),
        )
        for i in range(3)
    ]
    await db_session.commit()

    try:
        response = await client.get(
            "/failures/scoring", params={"offer_id": offer_id, "profile_id": profile.id, "limit": 2}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert [item["id"] for item in body["items"]] == [rows[0].id, rows[1].id]
    finally:
        await _delete_failures(db_session, ingestion_ids=[], scoring_ids=[row.id for row in rows])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_ingestion_source_filter_unknown_connector_returns_empty_not_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/failures/ingestion", params={"source": "totally-unknown-xyz"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_unknown_process_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/failures/bogus")

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_each_process_only_returns_its_own_table(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    profile = await _create_profile(db_session)

    ingestion_row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"source:{source_id}:shared",
        failure_type="shared_type",
    )
    scoring_row = await _seed_scoring_failure(
        db_session,
        offer_id=offer_id,
        profile_id=profile.id,
        dedup_key="offer:shared:profile:shared",
    )
    # Give the scoring row the same failure_type string to guard against a copy-paste
    # registry mixup (e.g. the ingestion filter accidentally matching scoring rows).
    scoring_row.failure_type = "shared_type"
    await db_session.commit()

    try:
        ingestion_response = await client.get(
            "/failures/ingestion", params={"source": connector, "failure_type": "shared_type"}
        )
        ingestion_body = ingestion_response.json()
        assert ingestion_body["total"] == 1
        assert ingestion_body["items"][0]["id"] == ingestion_row.id

        scoring_response = await client.get(
            "/failures/scoring", params={"offer_id": offer_id, "failure_type": "shared_type"}
        )
        scoring_body = scoring_response.json()
        assert scoring_body["total"] == 1
        assert scoring_body["items"][0]["id"] == scoring_row.id
    finally:
        await _delete_failures(
            db_session, ingestion_ids=[ingestion_row.id], scoring_ids=[scoring_row.id]
        )
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_rejects_page_size_above_max(client: httpx.AsyncClient) -> None:
    response = await client.get("/failures/ingestion", params={"limit": 10000})

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_default_status_open_excludes_resolved(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    open_row = await _seed_ingestion_failure(
        db_session, source_id=source_id, dedup_key=f"source:{source_id}:open"
    )
    resolved_row = await _seed_ingestion_failure(
        db_session, source_id=source_id, dedup_key=f"source:{source_id}:resolved", status="resolved"
    )
    await db_session.commit()

    try:
        default_response = await client.get("/failures/ingestion", params={"source": connector})
        default_body = default_response.json()
        assert [item["id"] for item in default_body["items"]] == [open_row.id]

        all_response = await client.get(
            "/failures/ingestion", params={"source": connector, "status": "all"}
        )
        all_ids = {item["id"] for item in all_response.json()["items"]}
        assert all_ids == {open_row.id, resolved_row.id}
    finally:
        await _delete_failures(
            db_session, ingestion_ids=[open_row.id, resolved_row.id], scoring_ids=[]
        )
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_failures_status_abandoned_is_filterable(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    open_row = await _seed_ingestion_failure(
        db_session, source_id=source_id, dedup_key=f"source:{source_id}:open"
    )
    abandoned_row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"source:{source_id}:abandoned",
        failure_type="detail_fetch_blocked",
        status="abandoned",
    )
    await db_session.commit()

    try:
        default_response = await client.get("/failures/ingestion", params={"source": connector})
        default_ids = {item["id"] for item in default_response.json()["items"]}
        assert default_ids == {open_row.id}

        abandoned_response = await client.get(
            "/failures/ingestion", params={"source": connector, "status": "abandoned"}
        )
        abandoned_body = abandoned_response.json()
        assert [item["id"] for item in abandoned_body["items"]] == [abandoned_row.id]

        all_response = await client.get(
            "/failures/ingestion", params={"source": connector, "status": "all"}
        )
        all_ids = {item["id"] for item in all_response.json()["items"]}
        assert all_ids == {open_row.id, abandoned_row.id}
    finally:
        await _delete_failures(
            db_session, ingestion_ids=[open_row.id, abandoned_row.id], scoring_ids=[]
        )
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_detail_fetch_blocked_success_persists_offer_and_resolves(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    blocked_url = _unique_url("blocked")
    row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"source:{source_id}:detail_url:test",
        failure_type="detail_fetch_blocked",
        error_message="blocked: HTTP 403",
        url=blocked_url,
        blocked_status=403,
    )
    await db_session.commit()

    detail_retry = AsyncMock(return_value=True)
    fake_spec = SimpleNamespace(detail_retry=detail_retry)
    monkeypatch.setattr(dlq_retry_module, "CONNECTOR_REGISTRY", {connector: fake_spec})

    try:
        response = await client.post(f"/failures/ingestion/{row.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "resolved"
        detail_retry.assert_awaited_once()
        assert detail_retry.call_args.args[2] == blocked_url

        await db_session.refresh(row)
        assert row.status == "resolved"
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_detail_fetch_blocked_still_blocked_stays_open_with_incremented_error(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-detail-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    blocked_url = _unique_url("blocked")
    row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"source:{source_id}:detail_url:test",
        failure_type="detail_fetch_blocked",
        error_message="blocked: HTTP 403",
        url=blocked_url,
        blocked_status=403,
    )
    await db_session.commit()

    async def _still_blocked(session: Any, source: Any, url: str) -> bool:
        raise BlockedFetchError(403)

    fake_spec = SimpleNamespace(detail_retry=_still_blocked)
    monkeypatch.setattr(dlq_retry_module, "CONNECTOR_REGISTRY", {connector: fake_spec})

    try:
        response = await client.post(f"/failures/ingestion/{row.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "open"
        assert "403" in body["error_message"]
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_validation_failure_success_persists_offer_and_resolves(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    canonical_url = _unique_url("retry")
    raw_payload = {
        "source_id": source_id,
        "title": f"Backend Engineer {uuid4()}",
        "company": "Acme",
        "canonical_url": canonical_url,
    }
    row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"validation:{canonical_url}",
        failure_type="validation_failed",
        raw_payload=raw_payload,
    )
    await db_session.commit()

    try:
        response = await client.post(f"/failures/ingestion/{row.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "resolved"

        await db_session.refresh(row)
        assert row.status == "resolved"
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_validation_failure_still_invalid_stays_open(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"validation:{source_id}:still-invalid",
        failure_type="validation_failed",
        raw_payload={"source_id": source_id, "company": "Acme"},
        error_message="old error",
    )
    await db_session.commit()

    try:
        response = await client.post(f"/failures/ingestion/{row.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "open"
        assert body["error_message"] != "old error"
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_scoring_failure_success_persists_match_score_and_resolves(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"justjoinit-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    profile = await _create_profile(db_session)
    row = await _seed_scoring_failure(
        db_session,
        offer_id=offer_id,
        profile_id=profile.id,
        dedup_key=f"offer:{offer_id}:profile:{profile.id}",
    )
    await db_session.commit()

    async def _fake_score(
        *, offer_id: int, profile_id: int, profile: object, offer: object
    ) -> MatchScoreSchema:
        return MatchScoreSchema(
            offer_id=offer_id,
            profile_id=profile_id,
            engine="langchain",
            score_percent=80,
            dimensions={"skill_match": 0.8},
            rationale="retried successfully",
        )

    monkeypatch.setattr(dlq_retry_module, "score_offer_with_langchain", _fake_score)

    try:
        response = await client.post(f"/failures/scoring/{row.id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "resolved"

        await db_session.refresh(row)
        assert row.status == "resolved"
    finally:
        await _delete_failures(db_session, ingestion_ids=[], scoring_ids=[row.id])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_fetch_failure_resolves_when_retriggered_ingestion_succeeds(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    row = await _seed_ingestion_failure(
        db_session,
        source_id=source_id,
        dedup_key=f"source:{source_id}",
        failure_type="run_fetch_failed",
    )
    await db_session.commit()

    async def _fake_trigger_ingest(source: str, *, force_refresh: bool = False) -> object:
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(dlq_retry_module, "trigger_ingest", _fake_trigger_ingest)

    try:
        response = await client.post(f"/failures/ingestion/{row.id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
    finally:
        await _delete_failures(db_session, ingestion_ids=[row.id], scoring_ids=[])
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_unknown_process_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/failures/bogus/1/retry")

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_unknown_failure_id_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/failures/ingestion/999999999/retry")

    assert response.status_code == 404
