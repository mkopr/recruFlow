from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db.models import Offer as OfferModel
from app.db.models import Profile as ProfileModel
from app.llm.matcher import _MatcherOutput, score_offers_with_langchain
from langchain_core.messages import BaseMessage

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


class _SequencedChainBuilder:
    def __init__(self, chains: "Iterator[_FakeChain | _FailingChain]") -> None:
        self._chains = chains

    def __call__(self) -> "_FakeChain | _FailingChain":
        return next(self._chains)


def _offer_row(offer_id: int) -> OfferModel:
    return cast(
        OfferModel,
        SimpleNamespace(
            id=offer_id,
            source_id=1,
            external_id=None,
            canonical_url=None,
            title="Senior Backend Engineer",
            company="Acme",
            location="Warsaw",
            remote=True,
            seniority="senior",
            salary_min=None,
            salary_max=None,
            salary_currency="PLN",
            contract_type="B2B",
            posted_at=None,
            description="A great remote B2B role.",
            industry_tags=[],
        ),
    )


def _profile_row(profile_id: int) -> ProfileModel:
    return cast(
        ProfileModel,
        SimpleNamespace(
            id=profile_id,
            data={"salary_min": 15000, "salary_target": 20000, "deal_breakers": []},
        ),
    )


@pytest.mark.asyncio
async def test_score_offers_with_langchain_records_scoring_failure_for_offer_that_raises() -> None:
    chains: Iterator[_FakeChain | _FailingChain] = iter(
        [_FailingChain(), _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS))]
    )
    profile_row = _profile_row(1)
    offer_1 = _offer_row(1)
    offer_2 = _offer_row(2)
    session = AsyncMock()
    session.add = MagicMock()

    results = await score_offers_with_langchain(
        session,
        profile_row,
        [(offer_1, "justjoinit"), (offer_2, "justjoinit")],
        chain_factory=_SequencedChainBuilder(chains),
    )

    assert len(results) == 1
    assert results[0].offer_id == 2

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "scoring_failures"

    session.add.assert_called_once()
    added_row = session.add.call_args[0][0]
    assert added_row.offer_id == 2
