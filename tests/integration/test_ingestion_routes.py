import asyncio
from functools import partial
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors import justjoinit, nofluffjobs, solid_jobs
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT
from app.ingestion.persist import ingest_offer
from app.ingestion.types import IngestionResult as JustJoinItIngestionResult
from app.ingestion.types import IngestionResult as NoFluffJobsIngestionResult
from app.ingestion.types import IngestionResult as SolidJobsIngestionResult
from app.llm.matcher import _MatcherOutput
from app.scoring import batch
from app.scoring.batch import run_batch_scoring
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_batch_scoring import (
    _create_profile,
    _delete_sources_and_dependents,
    _isolate_langchain_sources,
)
from tests.integration.test_justjoinit_connector_ingestion import (
    _FakeResponse,
    _paged_payload,
    _raw_offer,
)
from tests.integration.test_langchain_matcher_batch import _STRONG_OUTPUT_KWARGS, _FakeChain
from tests.integration.test_offers_routes import _create_source, _deactivate_all_profiles


def _unique_url(path: str) -> str:
    return f"https://example.com/jobs/{uuid4()}/{path}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_triggers_fetch_and_returns_new_updated_count(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=5, created=3)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")

    assert response.status_code == 200
    assert response.json() == {
        "source": "justjoinit",
        "ok": True,
        "fetched": 5,
        "created": 3,
        "error_message": None,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_persists_offers_end_to_end_visible_in_db(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    canonical_url = _unique_url("solid-jobs-offer")

    async def _fake(
        session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        await ingest_offer(
            session,
            {
                "source_id": source.id,
                "title": "Backend Engineer",
                "company": "Acme",
                "canonical_url": canonical_url,
            },
            raw_payload={"id": "abc"},
        )
        return SolidJobsIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/solid_jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["fetched"] == 1
    assert body["created"] == 1

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        row = await session.scalar(
            select(OfferModel).where(OfferModel.canonical_url == canonical_url)
        )
    assert row is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_defaults_to_force_refresh_false_to_keep_incremental_early_stop(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG18: the "Fetch now" button (the only caller of POST /ingest/{source} reachable from
    # the UI) must not silently disable BUG02/ADR0009's incremental early-stop by hardcoding
    # force_refresh=True. Default behavior has to match POST /scheduler/run/{source}.
    captured: dict[str, bool] = {}

    async def _fake(
        session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        captured["force_refresh"] = force_refresh
        return SolidJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/solid_jobs")

    assert response.status_code == 200
    assert captured["force_refresh"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_accepts_explicit_force_refresh_query_param_opt_in(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A genuine full re-sync is still reachable, but only via an explicit opt-in query param
    # rather than being the button's unconditional default (BUG18 suggested fix #2).
    captured: dict[str, bool] = {}

    async def _fake(
        session: AsyncSession, source: Source, *, campaign: str, force_refresh: bool = False
    ) -> SolidJobsIngestionResult:
        captured["force_refresh"] = force_refresh
        return SolidJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(solid_jobs, "run_solid_jobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/solid_jobs", params={"force_refresh": "true"})

    assert response.status_code == 200
    assert captured["force_refresh"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_sets_source_last_fetched_at_on_success(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")
    assert response.status_code == 200

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    assert entries[JUSTJOINIT]["last_fetched_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_does_not_set_source_last_fetched_at_on_failure(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    status_before = await scheduled_client.get("/scheduler/status")
    before = {
        entry["connector"]: entry["last_fetched_at"] for entry in status_before.json()["sources"]
    }

    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    response = await scheduled_client.post("/ingest/justjoinit")
    assert response.status_code == 200
    assert response.json()["ok"] is False

    status_after = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_after.json()["sources"]}
    assert entries[JUSTJOINIT]["last_fetched_at"] == before[JUSTJOINIT]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_unknown_source_returns_404_with_clear_message(
    scheduled_client: httpx.AsyncClient,
) -> None:
    response = await scheduled_client.post("/ingest/does-not-exist")

    assert response.status_code == 404
    assert "unknown connector" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_known_connector_without_configured_source_returns_404(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, "fake_connector", registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    response = await scheduled_client.post("/ingest/fake_connector")

    assert response.status_code == 404
    assert "no configured source" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_connector_exception_returns_200_ok_false_with_error_message(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> NoFluffJobsIngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(nofluffjobs, "run_nofluffjobs_ingestion", _fake)

    response = await scheduled_client.post("/ingest/nofluffjobs")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["fetched"] == 0
    assert body["created"] == 0
    assert "boom" in body["error_message"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint_responds_during_ingest_run(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        await asyncio.sleep(1.5)
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    task = asyncio.create_task(scheduled_client.post("/ingest/justjoinit"))
    await asyncio.sleep(0.2)

    loop = asyncio.get_event_loop()
    start = loop.time()
    health_response = await scheduled_client.get("/health")
    elapsed = loop.time() - start

    assert health_response.status_code == 200
    assert elapsed < 1.0

    await task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_triggers_batch_scoring_for_newly_persisted_offer(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG16: POST /ingest/{source} -- the only ingestion path FetchNowButton.tsx ever calls --
    # must trigger scoring same as POST /scheduler/run/{source} does. A fake connector name is
    # registered against the real justjoinit dispatcher, mirroring
    # test_ingest_known_connector_without_configured_source_returns_404's own pattern, so this
    # test can isolate LANGCHAIN_SOURCES to just its own Source instead of racing the huge
    # backlog of real, pre-existing justjoinit/nofluffjobs offers already in the shared dev DB.
    connector = f"justjoinit-{uuid4()}"
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, connector, registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )
    _isolate_langchain_sources(monkeypatch, connector)
    # conftest.py's `_stub_post_ingestion_batch_scoring` no-ops real scoring by default for
    # every other ingestion/scheduler test; this test is specifically about observing a real
    # MatchScore appear, so it restores the real implementation for its own duration, binding a
    # fake chain via the real chain_factory parameter instead of reaching into the matcher's
    # private LLM-chain builder.
    monkeypatch.setattr(
        batch,
        "run_batch_scoring",
        partial(
            run_batch_scoring,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        ),
    )

    canonical_url = _unique_url("justjoinit-scoring-offer")

    async def _fake(
        session: AsyncSession, source: Source, *, force_refresh: bool = False
    ) -> JustJoinItIngestionResult:
        await ingest_offer(
            session,
            {
                "source_id": source.id,
                "title": "Backend Engineer",
                "company": "Acme",
                "canonical_url": canonical_url,
            },
            raw_payload={"id": "abc"},
        )
        return JustJoinItIngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        await _deactivate_all_profiles(session)
        source_id = await _create_source(session, connector=connector)
        profile = await _create_profile(session)
        await session.commit()

    try:
        response = await scheduled_client.post(f"/ingest/{connector}")

        assert response.status_code == 200
        assert response.json()["ok"] is True

        async with sessionmaker() as session:
            offer_id = await session.scalar(
                select(OfferModel.id).where(OfferModel.canonical_url == canonical_url)
            )
            assert offer_id is not None

            score = await session.scalar(
                select(MatchScoreModel).where(
                    MatchScoreModel.offer_id == offer_id,
                    MatchScoreModel.profile_id == profile.id,
                )
            )
            assert score is not None
    finally:
        async with sessionmaker() as session:
            await _delete_sources_and_dependents(session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ingest_route_second_call_stops_early_instead_of_re_walking_full_catalog(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG18 regression: POST /ingest/{source} -- the only endpoint FetchNowButton.tsx calls --
    # must benefit from the same already_seen early-stop as POST /scheduler/run/{source}
    # instead of re-walking the full catalog on every click. A fake connector name is
    # registered against the real justjoinit dispatcher (mirroring
    # test_ingest_triggers_batch_scoring_for_newly_persisted_offer's pattern above) so this
    # test's pagination assertions aren't racing the shared dev DB's pre-existing offers.
    connector = f"justjoinit-{uuid4()}"
    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY, connector, registry.CONNECTOR_REGISTRY[JUSTJOINIT]
    )

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source = Source(
            name=connector,
            connector=connector,
            config_json={
                "page_size": 2,
                "already_seen_stop_threshold": 2,
                "rate_limit_delay_seconds": 0,
            },
        )
        session.add(source)
        await session.flush()
        source_id = source.id
        await session.commit()

    try:
        already_seen_offers = [_raw_offer(), _raw_offer()]
        monkeypatch.setattr(
            httpx,
            "get",
            lambda *a, **kw: _FakeResponse(
                json_data=_paged_payload(already_seen_offers, next_cursor=None)
            ),
        )
        first_response = await scheduled_client.post(f"/ingest/{connector}")
        assert first_response.status_code == 200
        assert first_response.json()["ok"] is True

        new_offers = [_raw_offer(), _raw_offer()]
        calls: list[int] = []

        def _fake_get(url: str, *, params: dict[str, Any], **kw: Any) -> _FakeResponse:
            cursor = params["from"]
            calls.append(cursor)
            if cursor == 0:
                return _FakeResponse(json_data=_paged_payload(new_offers, next_cursor=2))
            if cursor == 2:
                return _FakeResponse(json_data=_paged_payload(already_seen_offers, next_cursor=4))
            raise AssertionError(f"pagination should have stopped before requesting from={cursor}")

        monkeypatch.setattr(httpx, "get", _fake_get)

        second_response = await scheduled_client.post(f"/ingest/{connector}")

        assert second_response.status_code == 200
        body = second_response.json()
        assert calls == [0, 2]
        assert body["fetched"] == 4
        assert body["created"] == 2
    finally:
        async with sessionmaker() as session:
            await _delete_sources_and_dependents(session, [source_id])
