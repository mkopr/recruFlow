import asyncio
import logging
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.api.routes import scoring as scoring_routes
from app.db.models import IngestionFailure, ScoringFailure, Source
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.db.session import get_sessionmaker
from app.ingestion import registry
from app.ingestion.normalize import JUSTJOINIT
from app.ingestion.registry import ConnectorSpec
from app.ingestion.types import IngestionResult
from app.llm.matcher import _MatcherOutput
from app.scoring import batch
from app.scoring.batch import (
    BatchScoringSummary,
    _fetch_unscored_offers,
    count_unscored_backlog,
    run_batch_scoring,
)
from langchain_core.messages import BaseMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration.test_langchain_matcher_batch import (
    _STRONG_OUTPUT_KWARGS,
    _FailingChain,
    _FakeChain,
    _SequencedChainBuilder,
)
from tests.integration.test_offers_routes import (
    _create_offer,
    _create_source,
    _deactivate_all_profiles,
)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _enable_logger() -> None:
    logging.getLogger("app.scoring.batch").disabled = False


def _fake_connector(label: str = "fake") -> str:
    return f"{label}-{uuid4()}"


def _isolate_langchain_sources(monkeypatch: pytest.MonkeyPatch, *connectors: str) -> None:
    # Real recruFlow offers accumulate over time via the live scheduler under the real
    # justjoinit/nofluffjobs/solid_jobs connectors, so a brand-new never-scored Profile
    # would otherwise see every historical offer as "unscored", making exact
    # scored/skipped/failed counts nondeterministic. Swapping in unique per-test connector
    # identities scopes each test to only the Source/Offer rows it creates itself, with no
    # change to production code paths. batch.py reads LANGCHAIN_SOURCES through the matcher
    # module at call time rather than holding its own copy, so patching it here suffices.
    fake = frozenset(connectors)
    monkeypatch.setattr("app.llm.matcher.LANGCHAIN_SOURCES", fake)


def _fake_spec(connector: str, dispatch: registry.Connector) -> ConnectorSpec:
    return ConnectorSpec(
        name=connector, label=registry.CONNECTOR_REGISTRY[connector].label, dispatch=dispatch
    )


async def _delete_sources_and_dependents(session: AsyncSession, source_ids: list[int]) -> None:
    # Source rows with a non-null connector are picked up by connector.is_not(None)
    # assertions elsewhere (e.g. test_scheduler_ensure_sources.py's exact-set check), so
    # every test here must clean up the fake-connector sources (and their offers/scores)
    # it creates, mirroring test_offers_routes.py's own _delete_sources_with_offers.
    offer_ids = select(OfferModel.id).where(OfferModel.source_id.in_(source_ids))
    await session.execute(delete(MatchScoreModel).where(MatchScoreModel.offer_id.in_(offer_ids)))
    await session.execute(delete(ScoringFailure).where(ScoringFailure.offer_id.in_(offer_ids)))
    await session.execute(
        delete(IngestionFailure).where(IngestionFailure.source_id.in_(source_ids))
    )
    await session.execute(delete(OfferModel).where(OfferModel.source_id.in_(source_ids)))
    await session.execute(delete(Source).where(Source.id.in_(source_ids)))
    await session.commit()


async def _set_fetch_range(
    session: AsyncSession, source_id: int, fetch_range: dict[str, Any]
) -> None:
    source = await session.get(Source, source_id)
    assert source is not None
    source.config_json = {**source.config_json, "fetch_range": fetch_range}
    await session.commit()


async def _create_profile(session: AsyncSession, *, is_active: bool = True) -> ProfileModel:
    profile = ProfileModel(
        name=f"test-profile-{uuid4()}", status="active", is_active=is_active, data={}
    )
    session.add(profile)
    await session.flush()
    return profile


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_scores_all_unscored_offers_across_all_three_sources(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    jj, nfj, sj = _fake_connector("jj"), _fake_connector("nfj"), _fake_connector("sj")
    _isolate_langchain_sources(monkeypatch, jj, nfj, sj)

    await _deactivate_all_profiles(db_session)
    jj_source = await _create_source(db_session, connector=jj)
    nfj_source = await _create_source(db_session, connector=nfj)
    sj_source = await _create_source(db_session, connector=sj)
    try:
        await _create_offer(db_session, jj_source)
        await _create_offer(db_session, nfj_source)
        await _create_offer(db_session, sj_source)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 3
        assert summary.skipped == 0
        assert summary.failed == 0
        assert len(summary.score_events) == 3

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 3
        assert all(row.engine == "langchain" for row in rows)
    finally:
        await _delete_sources_and_dependents(db_session, [jj_source, nfj_source, sj_source])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_does_not_rescore_already_scored_pairs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    jj, nfj, sj = _fake_connector("jj"), _fake_connector("nfj"), _fake_connector("sj")
    _isolate_langchain_sources(monkeypatch, jj, nfj, sj)

    def chain_factory() -> _FakeChain:
        return _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS))

    await _deactivate_all_profiles(db_session)
    jj_source = await _create_source(db_session, connector=jj)
    nfj_source = await _create_source(db_session, connector=nfj)
    sj_source = await _create_source(db_session, connector=sj)
    try:
        already_scored_offer_id = await _create_offer(db_session, jj_source)
        await _create_offer(db_session, nfj_source)
        await _create_offer(db_session, sj_source)
        profile = await _create_profile(db_session)
        await db_session.flush()

        db_session.add(
            MatchScoreModel(
                offer_id=already_scored_offer_id,
                profile_id=profile.id,
                engine="langchain",
                score_percent=77,
                dimensions={},
                rationale="pre-existing score",
            )
        )
        await db_session.commit()

        summary = await run_batch_scoring(db_session, chain_factory=chain_factory)
        await db_session.commit()

        assert summary.scored == 2
        assert summary.skipped == 1

        summary_2 = await run_batch_scoring(db_session, chain_factory=chain_factory)
        await db_session.commit()

        assert summary_2.scored == 0
        assert summary_2.skipped == 3

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 3
    finally:
        await _delete_sources_and_dependents(db_session, [jj_source, nfj_source, sj_source])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_serializes_concurrent_callers_to_prevent_duplicate_scores(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG29: two independent callers (e.g. the scheduled backlog job and a manual
    # /score/batch request) used to be able to run run_batch_scoring at the same time, each
    # opening its own session and fetching the same "unscored" offer before either committed,
    # producing two MatchScore rows for the same offer/profile pair. run_batch_scoring now
    # serializes on a module-level lock, so the second caller's own _fetch_unscored_offers
    # query only runs after the first caller has committed and excludes what it just scored.
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)
    sessionmaker = get_sessionmaker(db_engine)

    class _SlowChain:
        async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
            await asyncio.sleep(0.05)
            return _MatcherOutput(**_STRONG_OUTPUT_KWARGS)

    async with sessionmaker() as session:
        await _deactivate_all_profiles(session)
        source_id = await _create_source(session, connector=connector)
        await _create_offer(session, source_id)
        profile = await _create_profile(session)
        await session.commit()

    try:

        async def _call() -> BatchScoringSummary:
            async with sessionmaker() as session:
                summary = await run_batch_scoring(session, chain_factory=lambda: _SlowChain())
                await session.commit()
                return summary

        summary_a, summary_b = await asyncio.gather(_call(), _call())

        assert summary_a.scored + summary_b.scored == 1

        async with sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
    finally:
        async with sessionmaker() as session:
            await _delete_sources_and_dependents(session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_score_batch_scores_unscored_offers_via_http(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)
    # /score/batch has no request field for injecting a chain factory (nor should it -- that's
    # an internal collaborator, not part of the HTTP contract), so this test binds one via the
    # real chain_factory parameter and swaps in the bound callable for the route's own reference.
    monkeypatch.setattr(
        scoring_routes,
        "run_batch_scoring",
        partial(
            run_batch_scoring,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        ),
    )

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        profile = await _create_profile(db_session)
        await db_session.commit()

        response = await client.post("/score/batch")

        assert response.status_code == 200
        body = response.json()
        assert body == {"scored": 1, "skipped": 0, "failed": 0, "remaining": 0}

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_score_batch_returns_zero_counts_when_no_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)

    response = await client.post("/score/batch")

    assert response.status_code == 200
    assert response.json() == {"scored": 0, "skipped": 0, "failed": 0, "remaining": 0}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_profile_switch_causes_previously_scored_offers_to_be_picked_up_again(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    def chain_factory() -> _FakeChain:
        return _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS))

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        profile_a = await _create_profile(db_session)
        await db_session.commit()

        summary_a = await run_batch_scoring(db_session, chain_factory=chain_factory)
        await db_session.commit()
        assert summary_a.scored == 1
        assert summary_a.skipped == 0

        await _deactivate_all_profiles(db_session)
        profile_b = await _create_profile(db_session)
        await db_session.commit()

        summary_b = await run_batch_scoring(db_session, chain_factory=chain_factory)
        await db_session.commit()
        assert summary_b.scored == 1
        assert summary_b.skipped == 0

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(
                        MatchScoreModel.profile_id.in_([profile_a.id, profile_b.id])
                    )
                )
            )
            .scalars()
            .all()
        )
        profile_ids_scored = {row.profile_id for row in rows}
        assert profile_a.id in profile_ids_scored
        assert profile_b.id in profile_ids_scored
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_partial_failure_does_not_abort_batch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)
    chains: Iterator[_FakeChain | _FailingChain] = iter(
        [_FailingChain(), _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS))]
    )

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        offer_1_id = await _create_offer(db_session, source_id)
        offer_2_id = await _create_offer(db_session, source_id)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(db_session, chain_factory=_SequencedChainBuilder(chains))
        await db_session.commit()

        assert summary.scored == 1
        assert summary.failed == 1
        assert summary.skipped == 0

        rows = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        # BUG24: scoring now works newest-first, so offer_2 (created later, no
        # posted_at) is processed first and gets the failing chain; offer_1 is
        # processed second and succeeds.
        assert rows[0].offer_id == offer_1_id
        assert offer_2_id != rows[0].offer_id
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_logs_per_run_summary(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        await _create_profile(db_session)
        await db_session.commit()

        with caplog.at_level(logging.INFO, logger="app.scoring.batch"):
            await run_batch_scoring(
                db_session,
                chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
            )
        await db_session.commit()

        assert any(
            "scored=1" in record.getMessage()
            and "skipped=0" in record.getMessage()
            and "failed=0" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_scheduler_run_does_not_trigger_batch_scoring_on_success(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG29: ingestion used to unconditionally trigger a scoring run of its own, racing the
    # dedicated `scoring:backlog` job (BUG24) and producing duplicate MatchScore rows for the
    # same offer/profile pair. The backlog job now owns draining unscored offers exclusively.
    async def _fake(session: AsyncSession, source: Source, force_refresh: bool) -> IngestionResult:
        return IngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setitem(registry.CONNECTOR_REGISTRY, JUSTJOINIT, _fake_spec(JUSTJOINIT, _fake))

    calls: list[None] = []

    async def _fake_run_batch_scoring(session: AsyncSession) -> BatchScoringSummary:
        calls.append(None)
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    monkeypatch.setattr(batch, "run_batch_scoring", _fake_run_batch_scoring)

    response = await scheduled_client.post("/scheduler/run/justjoinit")

    assert response.status_code == 200
    assert len(calls) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_scheduler_run_does_not_trigger_batch_scoring_when_connector_errors(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(session: AsyncSession, source: Source, force_refresh: bool) -> IngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setitem(registry.CONNECTOR_REGISTRY, JUSTJOINIT, _fake_spec(JUSTJOINIT, _raise))

    calls: list[None] = []

    async def _fake_run_batch_scoring(session: AsyncSession) -> BatchScoringSummary:
        calls.append(None)
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    monkeypatch.setattr(batch, "run_batch_scoring", _fake_run_batch_scoring)

    response = await scheduled_client.post("/scheduler/run/justjoinit")

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert len(calls) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_caps_work_per_run_and_reports_remaining_backlog(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG16: a single trigger (manual /ingest, manual /scheduler/run, or an automatic
    # APScheduler job) must not block on an unbounded unscored-offer backlog, so
    # run_batch_scoring caps how much it scores per call and reports how much is left.
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        for _ in range(3):
            await _create_offer(db_session, source_id)
        await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            limit=2,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 2
        assert summary.failed == 0
        assert summary.remaining == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_prefers_newest_offers_first(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG24: scoring must work newest-to-oldest (by posted_at, falling back to
    # created_at for offers with no posted_at) so a capped run scores what the user
    # is actually looking at (the offer list's default sort is newest-first), not
    # whatever happens to have the lowest DB id.
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        oldest_id = await _create_offer(db_session, source_id, posted_at=now - timedelta(days=10))
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=5))
        newest_id = await _create_offer(db_session, source_id, posted_at=now)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            limit=1,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        scored_offer_id = (
            await db_session.execute(
                select(MatchScoreModel.offer_id).where(MatchScoreModel.profile_id == profile.id)
            )
        ).scalar_one()
        assert scored_offer_id == newest_id
        assert scored_offer_id != oldest_id
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_falls_back_to_created_at_when_posted_at_is_null(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        older_no_posted_at = await _create_offer(db_session, source_id, posted_at=None)
        newer_no_posted_at = await _create_offer(db_session, source_id, posted_at=None)
        profile = await _create_profile(db_session)
        await db_session.commit()

        # created_at is a server default stamped at insert time, so the second offer
        # created is the "newer" one when posted_at is null for both.
        summary = await run_batch_scoring(
            db_session,
            limit=1,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        scored_offer_id = (
            await db_session.execute(
                select(MatchScoreModel.offer_id).where(MatchScoreModel.profile_id == profile.id)
            )
        ).scalar_one()
        assert scored_offer_id == newer_no_posted_at
        assert scored_offer_id != older_no_posted_at
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_unscored_backlog_returns_zero_when_no_active_profile(
    db_session: AsyncSession,
) -> None:
    await _deactivate_all_profiles(db_session)

    assert await count_unscored_backlog(db_session) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_unscored_backlog_reflects_live_state_before_any_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # BUG24: the backlog must be visible before a run ever completes -- a brand-new
    # active profile has never been scored against, so this must equal the full
    # eligible offer count, not 0.
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        await _create_offer(db_session, source_id)
        await _create_profile(db_session)
        await db_session.commit()

        assert await count_unscored_backlog(db_session) == 2

        await run_batch_scoring(
            db_session,
            limit=1,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert await count_unscored_backlog(db_session) == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoring_status_reports_live_unscored_backlog(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        await _create_offer(db_session, source_id)
        await _create_profile(db_session)
        await db_session.commit()

        response = await client.get("/scoring/status")

        assert response.status_code == 200
        assert response.json()["unscored_backlog"] == 2
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoring_status_reflects_last_completed_run(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        await _create_profile(db_session)
        await db_session.commit()

        await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        response = await client.get("/scoring/status")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is False
        assert body["last_scored"] == 1
        assert body["last_failed"] == 0
        assert body["remaining_backlog"] == 0
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_unscored_offers_excludes_offers_outside_source_range(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        in_range = await _create_offer(db_session, source_id, posted_at=now - timedelta(days=5))
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=30))
        await _create_offer(db_session, source_id, posted_at=now + timedelta(days=30))
        profile = await _create_profile(db_session)
        await _set_fetch_range(
            db_session,
            source_id,
            {
                "mode": "range",
                "since": (now - timedelta(days=10)).isoformat(),
                "until": (now + timedelta(days=10)).isoformat(),
            },
        )

        selected = await _fetch_unscored_offers(db_session, profile.id, limit=10)

        assert [offer.id for offer, _ in selected] == [in_range]
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_unscored_offers_mode_all_returns_everything(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=400))
        await _create_offer(db_session, source_id, posted_at=now)
        profile = await _create_profile(db_session)
        await _set_fetch_range(db_session, source_id, {"mode": "all"})

        selected = await _fetch_unscored_offers(db_session, profile.id, limit=10)

        assert len(selected) == 2
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_unscored_offers_null_posted_at_excluded_when_until_in_past(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id, posted_at=None)
        profile = await _create_profile(db_session)
        now = datetime.now(UTC)
        await _set_fetch_range(
            db_session, source_id, {"mode": "range", "until": (now - timedelta(days=1)).isoformat()}
        )

        selected = await _fetch_unscored_offers(db_session, profile.id, limit=10)
        assert selected == []

        await _set_fetch_range(db_session, source_id, {"mode": "range", "until": None})

        selected_again = await _fetch_unscored_offers(db_session, profile.id, limit=10)
        assert len(selected_again) == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_unscored_backlog_matches_range_filtered_fetch(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=5))
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=30))
        profile = await _create_profile(db_session)
        await _set_fetch_range(
            db_session,
            source_id,
            {"mode": "range", "since": (now - timedelta(days=10)).isoformat()},
        )

        backlog = await count_unscored_backlog(db_session)
        selected = await _fetch_unscored_offers(db_session, profile.id, limit=1000)

        assert backlog == len(selected)
        assert backlog == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoring_status_unscored_backlog_matches_batch_run_with_range(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        await _create_offer(db_session, source_id, posted_at=now)
        await _create_offer(db_session, source_id, posted_at=now - timedelta(days=30))
        await _create_profile(db_session)
        await _set_fetch_range(
            db_session,
            source_id,
            {"mode": "range", "since": (now - timedelta(days=1)).isoformat()},
        )

        status_response = await client.get("/scoring/status")
        reported_backlog = status_response.json()["unscored_backlog"]

        summary = await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert reported_backlog == 1
        assert summary.scored == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_narrowing_fetch_range_does_not_invalidate_existing_match_score(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        now = datetime.now(UTC)
        offer_id = await _create_offer(db_session, source_id, posted_at=now - timedelta(days=30))
        profile = await _create_profile(db_session)
        await db_session.commit()

        await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        before = (
            await db_session.execute(
                select(MatchScoreModel).where(
                    MatchScoreModel.offer_id == offer_id, MatchScoreModel.profile_id == profile.id
                )
            )
        ).scalar_one()
        before_snapshot = (
            before.id,
            before.score_percent,
            before.engine,
            before.created_at,
        )

        await _set_fetch_range(
            db_session, source_id, {"mode": "range", "since": (now - timedelta(days=1)).isoformat()}
        )

        after = (
            await db_session.execute(
                select(MatchScoreModel).where(
                    MatchScoreModel.offer_id == offer_id, MatchScoreModel.profile_id == profile.id
                )
            )
        ).scalar_one()
        after_snapshot = (after.id, after.score_percent, after.engine, after.created_at)

        assert before_snapshot == after_snapshot
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])
