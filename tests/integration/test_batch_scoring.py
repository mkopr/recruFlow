import logging
from collections.abc import AsyncGenerator, Iterator
from functools import partial
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.api.routes import scoring as scoring_routes
from app.connectors import justjoinit
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.db.models import ScoringConfig as ScoringConfigModel
from app.db.models import Source
from app.ingestion.types import IngestionResult
from app.llm.matcher import _MatcherOutput
from app.scoring import batch
from app.scoring.batch import BatchScoringSummary, run_batch_scoring
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    # identities (and pointing both LANGCHAIN_SOURCES bindings at them) scopes each test to
    # only the Source/Offer rows it creates itself, with no change to production code paths.
    fake = frozenset(connectors)
    monkeypatch.setattr("app.llm.matcher.LANGCHAIN_SOURCES", fake)
    monkeypatch.setattr("app.scoring.batch.LANGCHAIN_SOURCES", fake)


async def _delete_sources_and_dependents(session: AsyncSession, source_ids: list[int]) -> None:
    # Source rows with a non-null connector are picked up by connector.is_not(None)
    # assertions elsewhere (e.g. test_scheduler_ensure_sources.py's exact-set check), so
    # every test here must clean up the fake-connector sources (and their offers/scores)
    # it creates, mirroring test_offers_routes.py's own _delete_sources_with_offers.
    offer_ids = select(OfferModel.id).where(OfferModel.source_id.in_(source_ids))
    await session.execute(delete(MatchScoreModel).where(MatchScoreModel.offer_id.in_(offer_ids)))
    await session.execute(delete(OfferModel).where(OfferModel.source_id.in_(source_ids)))
    await session.execute(delete(Source).where(Source.id.in_(source_ids)))
    await session.commit()


async def _create_profile(session: AsyncSession, *, is_active: bool = True) -> ProfileModel:
    profile = ProfileModel(
        name=f"test-profile-{uuid4()}", status="active", is_active=is_active, data={}
    )
    session.add(profile)
    await session.flush()
    return profile


async def _reset_scoring_config(session: AsyncSession) -> None:
    await session.execute(delete(ScoringConfigModel))
    await session.commit()


# All six dimensions at 0.6; the missing-salary conservatism cap (applied because the test
# profile has no salary_min/salary_target) pulls salary_fit down to 0.5, giving a weighted
# total of 0.575 -- "C" under the module's default thresholds but "A" under a custom scale
# with grade_a=0.5, proving the grade actually came from persisted config, not the default.
_MID_RANGE_OUTPUT_KWARGS = {
    "skill_match": 0.6,
    "salary_fit": 0.6,
    "seniority_fit": 0.6,
    "work_mode_location": 0.6,
    "contract_type": 0.6,
    "red_flags": 0.6,
    "rationale": "Middling fit across all six dimensions.",
}


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

        assert summary == BatchScoringSummary(scored=3, skipped=0, failed=0)

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
                grade="B",
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
        assert rows[0].offer_id == offer_2_id
        assert offer_1_id != rows[0].offer_id
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
async def test_post_scheduler_run_triggers_batch_scoring_after_ingestion_completes(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake(
        session: AsyncSession, source: object, *, force_refresh: bool = False
    ) -> IngestionResult:
        return IngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _fake)

    calls: list[None] = []

    async def _fake_run_batch_scoring(session: AsyncSession) -> BatchScoringSummary:
        calls.append(None)
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    monkeypatch.setattr(batch, "run_batch_scoring", _fake_run_batch_scoring)

    response = await scheduled_client.post("/scheduler/run/justjoinit")

    assert response.status_code == 200
    assert len(calls) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_scheduler_run_triggers_batch_scoring_even_when_connector_errors(
    scheduled_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise(session: AsyncSession, source: object, **kwargs: object) -> IngestionResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(justjoinit, "run_justjoinit_ingestion", _raise)

    calls: list[None] = []

    async def _fake_run_batch_scoring(session: AsyncSession) -> BatchScoringSummary:
        calls.append(None)
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    monkeypatch.setattr(batch, "run_batch_scoring", _fake_run_batch_scoring)

    response = await scheduled_client.post("/scheduler/run/justjoinit")

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert len(calls) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_batch_scoring_uses_persisted_scoring_config_thresholds(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _reset_scoring_config(db_session)
    db_session.add(ScoringConfigModel(grade_a=0.5, grade_b=0.4, grade_c=0.3, grade_d=0.2))
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_MID_RANGE_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        row = (
            await db_session.execute(
                select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
            )
        ).scalar_one()
        assert row.grade == "A"
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])
        await _reset_scoring_config(db_session)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_changing_scoring_config_does_not_rewrite_existing_match_score_grade(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _isolate_langchain_sources(monkeypatch, connector)

    await _reset_scoring_config(db_session)
    db_session.add(ScoringConfigModel(grade_a=0.85, grade_b=0.70, grade_c=0.55, grade_d=0.40))
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        profile = await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_MID_RANGE_OUTPUT_KWARGS)),
        )
        await db_session.commit()
        assert summary.scored == 1

        rows_before = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_before) == 1
        match_score_id = rows_before[0].id
        original_grade = rows_before[0].grade

        config_row = (await db_session.execute(select(ScoringConfigModel))).scalar_one()
        config_row.grade_a, config_row.grade_b = 0.2, 0.15
        config_row.grade_c, config_row.grade_d = 0.1, 0.05
        await db_session.commit()

        refetched = await db_session.get(MatchScoreModel, match_score_id)
        assert refetched is not None
        assert refetched.grade == original_grade

        rows_after = (
            (
                await db_session.execute(
                    select(MatchScoreModel).where(MatchScoreModel.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows_after) == 1
    finally:
        await _delete_sources_and_dependents(db_session, [source_id])
        await _reset_scoring_config(db_session)


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
