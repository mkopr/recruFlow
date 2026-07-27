from collections.abc import Iterator
from uuid import uuid4

import pytest
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.db.models import ScoringFailure
from app.ingestion.normalize import JUSTJOINIT, NOFLUFFJOBS, SOLID_JOBS
from app.llm.matcher import _MatcherOutput, score_offers_with_langchain
from langchain_core.messages import BaseMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_offers_routes import _create_offer, _create_source

_STRONG_OUTPUT_KWARGS = {
    "skill_match": 0.9,
    "salary_fit": 0.9,
    "seniority_fit": 0.9,
    "work_mode_location": 0.9,
    "contract_type": 0.9,
    "red_flags": 0.9,
    "rationale": "Strong fit across all six dimensions.",
}


class _FakeChain:
    def __init__(self, output: _MatcherOutput) -> None:
        self._output = output

    async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
        return self._output


class _FailingChain:
    async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
        raise RuntimeError("simulated matcher failure")


class _SequencedChain:
    """A single chain whose `ainvoke` result/exception varies call-to-call.

    `score_offers_with_langchain` now builds one chain per batch and reuses it
    across every offer, so a test simulating "offer N fails, offer N+1 succeeds" needs one
    chain object with call-ordered behavior, not a fresh chain per offer.
    """

    def __init__(self, outcomes: "Iterator[_MatcherOutput | BaseException]") -> None:
        self._outcomes = outcomes

    async def ainvoke(self, messages: list[BaseMessage]) -> _MatcherOutput:
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def _create_profile(session: AsyncSession) -> ProfileModel:
    profile = ProfileModel(name=f"test-profile-{uuid4()}", status="active", is_active=True, data={})
    session.add(profile)
    await session.flush()
    return profile


@pytest.mark.integration
@pytest.mark.asyncio
async def test_score_offers_with_langchain_scores_all_three_sources_including_solid_jobs(
    db_session: AsyncSession,
) -> None:
    jj_source = await _create_source(db_session, connector=JUSTJOINIT)
    nfj_source = await _create_source(db_session, connector=NOFLUFFJOBS)
    sj_source = await _create_source(db_session, connector=SOLID_JOBS)

    jj_offer_id = await _create_offer(db_session, jj_source)
    nfj_offer_id = await _create_offer(db_session, nfj_source)
    sj_offer_id = await _create_offer(db_session, sj_source)

    profile = await _create_profile(db_session)

    jj_offer = await db_session.get(OfferModel, jj_offer_id)
    nfj_offer = await db_session.get(OfferModel, nfj_offer_id)
    sj_offer = await db_session.get(OfferModel, sj_offer_id)
    assert jj_offer is not None and nfj_offer is not None and sj_offer is not None

    await score_offers_with_langchain(
        db_session,
        profile,
        [
            (jj_offer, JUSTJOINIT),
            (nfj_offer, NOFLUFFJOBS),
            (sj_offer, SOLID_JOBS),
        ],
        chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
    )

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
    assert {row.offer_id for row in rows} == {jj_offer_id, nfj_offer_id, sj_offer_id}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_score_offers_with_langchain_continues_batch_after_one_offer_fails(
    db_session: AsyncSession,
) -> None:
    outcomes: Iterator[_MatcherOutput | BaseException] = iter(
        [RuntimeError("simulated matcher failure"), _MatcherOutput(**_STRONG_OUTPUT_KWARGS)]
    )

    jj_source = await _create_source(db_session, connector=JUSTJOINIT)
    offer_1_id = await _create_offer(db_session, jj_source)
    offer_2_id = await _create_offer(db_session, jj_source)
    profile = await _create_profile(db_session)

    offer_1 = await db_session.get(OfferModel, offer_1_id)
    offer_2 = await db_session.get(OfferModel, offer_2_id)
    assert offer_1 is not None and offer_2 is not None

    await score_offers_with_langchain(
        db_session,
        profile,
        [(offer_1, JUSTJOINIT), (offer_2, JUSTJOINIT)],
        chain_factory=lambda: _SequencedChain(outcomes),
    )

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

    failures = (
        (
            await db_session.execute(
                select(ScoringFailure).where(ScoringFailure.offer_id == offer_1_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(failures) == 1
    assert failures[0].profile_id == profile.id
    assert failures[0].failure_type == "scoring_failed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_score_offers_with_langchain_empty_offer_list_returns_empty_list(
    db_session: AsyncSession,
) -> None:
    profile = await _create_profile(db_session)

    results = await score_offers_with_langchain(db_session, profile, [])

    assert results == []
