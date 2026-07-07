import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import uvicorn
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Profile as ProfileModel
from app.db.session import get_engine, get_sessionmaker
from app.llm import matcher
from app.llm.matcher import _MatcherOutput
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import AppStatus

from tests.integration.conftest import reset_test_profiles
from tests.integration.test_offers_routes import (
    _create_offer,
    _create_source,
    _delete_sources_with_offers,
)

# This file spins up a real uvicorn server per test (see `sse_client` below) to
# exercise genuine HTTP streaming. sse_starlette's shutdown watcher otherwise
# auto-detects *any* uvicorn Server's `should_exit` (via signal-handler
# introspection) and latches its process-wide `AppStatus.should_exit` flag on
# permanently -- once one test's server shuts down, every subsequent test's SSE
# stream in this process would terminate immediately on connect. Each test here
# already closes its own client-side stream before tearing down its server, so
# the auto-drain feature isn't needed.
AppStatus.disable_automatic_graceful_drain()  # type: ignore[no-untyped-call]

_STRONG_OUTPUT_KWARGS = {
    "skill_match": 0.9,
    "salary_fit": 0.9,
    "seniority_fit": 0.9,
    "work_mode_location": 0.9,
    "contract_type": 0.9,
    "red_flags": 0.9,
    "rationale": "Strong fit across all six dimensions.",
}

_WEAK_OUTPUT_KWARGS = {
    "skill_match": 0.1,
    "salary_fit": 0.1,
    "seniority_fit": 0.1,
    "work_mode_location": 0.1,
    "contract_type": 0.1,
    "red_flags": 0.1,
    "rationale": "Weak fit across all six dimensions.",
}

_TEST_PROFILE_NAME = "test-scoring-events-profile"


class _FakeChain:
    def __init__(self, output: _MatcherOutput) -> None:
        self._output = output

    async def ainvoke(self, messages: object) -> _MatcherOutput:
        return self._output


class _FakeLLM:
    def __init__(self, output: _MatcherOutput) -> None:
        self._output = output

    def with_structured_output(self, *args: object, **kwargs: object) -> _FakeChain:
        return _FakeChain(self._output)


def _patch_matcher_for_fake_connector(
    monkeypatch: pytest.MonkeyPatch, connector: str, output_kwargs: dict[str, object]
) -> None:
    monkeypatch.setattr(matcher, "LANGCHAIN_SOURCES", frozenset({connector}))
    monkeypatch.setattr(matcher, "_build_llm", lambda: _FakeLLM(_MatcherOutput(**output_kwargs)))


async def _activate_fresh_profile(session: AsyncSession) -> None:
    # salary_min/salary_target must be set: score_offer_with_langchain caps
    # salary_fit at 0.5 for a profile with no salary preference, which would
    # otherwise pull a "strong" 0.9-across-the-board fake LLM output below the
    # grade A threshold.
    await reset_test_profiles(session, [_TEST_PROFILE_NAME])
    profile = ProfileModel(
        name=_TEST_PROFILE_NAME,
        status="active",
        is_active=True,
        data={"salary_min": 100000, "salary_target": 120000},
    )
    session.add(profile)
    await session.commit()


async def _next_grade_a_event(
    lines: AsyncIterator[str], *, timeout: float = 5
) -> dict[str, object]:
    async def _read() -> dict[str, object]:
        async for line in lines:
            if line.startswith("data:"):
                return json.loads(line.removeprefix("data:").strip())  # type: ignore[no-any-return]
        raise AssertionError("SSE stream ended before a grade_a event arrived")

    return await asyncio.wait_for(_read(), timeout=timeout)


@pytest_asyncio.fixture
async def sse_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    # GET /scoring/events never completes until the client disconnects, but
    # httpx's ASGITransport (used by every other integration test's
    # `scheduled_client` fixture) buffers a whole ASGI call to completion
    # before returning anything -- including response headers -- so it
    # deadlocks against a genuinely long-lived SSE stream. A real socket (a
    # live uvicorn server bound to an OS-assigned port, same `app` + lifespan)
    # is the only way to exercise true incremental streaming here.
    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="on", log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        yield client

    server.should_exit = True
    await server_task


@pytest.mark.integration
@pytest.mark.asyncio
async def test_grade_a_event_fires_exactly_once_on_new_grade_a_score(
    sse_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-{uuid4()}"
    _patch_matcher_for_fake_connector(monkeypatch, connector, _STRONG_OUTPUT_KWARGS)

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        await _activate_fresh_profile(session)
        source_id = await _create_source(session, connector=connector)
        offer_id = await _create_offer(session, source_id)
        await session.commit()

    try:
        async with sse_client.stream("GET", "/scoring/events") as stream:
            lines = stream.aiter_lines()
            await asyncio.sleep(0.1)

            batch_response = await sse_client.post("/score/batch")
            assert batch_response.status_code == 200
            assert batch_response.json()["scored"] == 1

            event = await _next_grade_a_event(lines)
            assert event["offer_id"] == offer_id
            assert event["title"] == "Backend Engineer"
            assert event["company"] == "Acme"

            second_response = await sse_client.post("/score/batch")
            assert second_response.status_code == 200
            assert second_response.json()["scored"] == 0

            with pytest.raises(asyncio.TimeoutError):
                await _next_grade_a_event(lines, timeout=1)
    finally:
        async with sessionmaker() as session:
            await _delete_sources_with_offers(session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preexisting_grade_a_scores_do_not_fire_on_connect(
    sse_client: httpx.AsyncClient,
) -> None:
    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        source_id = await _create_source(session, connector=f"fake-{uuid4()}")
        offer_id = await _create_offer(session, source_id)
        profile = ProfileModel(name=f"unused-{uuid4()}", status="active", is_active=False, data={})
        session.add(profile)
        await session.flush()
        score = MatchScoreModel(
            offer_id=offer_id,
            profile_id=profile.id,
            engine="langchain",
            grade="A",
            dimensions={},
        )
        session.add(score)
        await session.commit()

    try:
        async with sse_client.stream("GET", "/scoring/events") as stream:
            with pytest.raises(asyncio.TimeoutError):
                await _next_grade_a_event(stream.aiter_lines(), timeout=1)
    finally:
        async with sessionmaker() as session:
            await _delete_sources_with_offers(session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_subscribers_each_receive_the_event(
    sse_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-{uuid4()}"
    _patch_matcher_for_fake_connector(monkeypatch, connector, _STRONG_OUTPUT_KWARGS)

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        await _activate_fresh_profile(session)
        source_id = await _create_source(session, connector=connector)
        offer_id = await _create_offer(session, source_id)
        await session.commit()

    try:
        async with (
            sse_client.stream("GET", "/scoring/events") as stream_a,
            sse_client.stream("GET", "/scoring/events") as stream_b,
        ):
            await asyncio.sleep(0.1)

            batch_response = await sse_client.post("/score/batch")
            assert batch_response.status_code == 200

            event_a = await _next_grade_a_event(stream_a.aiter_lines())
            event_b = await _next_grade_a_event(stream_b.aiter_lines())
            assert event_a["offer_id"] == offer_id
            assert event_b["offer_id"] == offer_id
    finally:
        async with sessionmaker() as session:
            await _delete_sources_with_offers(session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_grade_a_score_does_not_publish(
    sse_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = f"fake-{uuid4()}"
    _patch_matcher_for_fake_connector(monkeypatch, connector, _WEAK_OUTPUT_KWARGS)

    engine = get_engine()
    sessionmaker = get_sessionmaker(engine)
    async with sessionmaker() as session:
        await _activate_fresh_profile(session)
        source_id = await _create_source(session, connector=connector)
        await _create_offer(session, source_id)
        await session.commit()

    try:
        async with sse_client.stream("GET", "/scoring/events") as stream:
            await asyncio.sleep(0.1)

            batch_response = await sse_client.post("/score/batch")
            assert batch_response.status_code == 200
            assert batch_response.json()["scored"] == 1

            with pytest.raises(asyncio.TimeoutError):
                await _next_grade_a_event(stream.aiter_lines(), timeout=1)
    finally:
        async with sessionmaker() as session:
            await _delete_sources_with_offers(session, [source_id])
