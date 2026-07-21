from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.db.models import (
    Application,
    CVVersion,
    IngestionFailure,
    MatchScore,
    Profile,
    ScoringFailure,
    Source,
)
from app.db.models import Offer as OfferModel
from app.ingestion.persist import ingest_offer
from sqlalchemy import delete, func, select, update
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
    # MatchScore/ScoringFailure/CVVersion/Application rows referencing these offers, and
    # IngestionFailure rows referencing these sources, must go first (FK on offer_id/source_id).
    offer_ids = select(OfferModel.id).where(OfferModel.source_id.in_(source_ids))
    await session.execute(delete(Application).where(Application.offer_id.in_(offer_ids)))
    await session.execute(delete(CVVersion).where(CVVersion.offer_id.in_(offer_ids)))
    await session.execute(delete(MatchScore).where(MatchScore.offer_id.in_(offer_ids)))
    await session.execute(delete(ScoringFailure).where(ScoringFailure.offer_id.in_(offer_ids)))
    await session.execute(
        delete(IngestionFailure).where(IngestionFailure.source_id.in_(source_ids))
    )
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


async def _create_profile(session: AsyncSession) -> int:
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    session.add(profile)
    await session.flush()
    return profile.id


async def _create_match_score(session: AsyncSession, offer_id: int, profile_id: int) -> int:
    score = MatchScore(
        offer_id=offer_id,
        profile_id=profile_id,
        engine="langchain",
        score_percent=80,
        dimensions={},
        rationale="test score",
    )
    session.add(score)
    await session.flush()
    return score.id


async def _create_scoring_failure(session: AsyncSession, offer_id: int, profile_id: int) -> int:
    failure = ScoringFailure(
        offer_id=offer_id,
        profile_id=profile_id,
        dedup_key=f"scoring-failure-{uuid4()}",
        failure_type="scoring_failed",
        status="open",
        error_message="test failure",
    )
    session.add(failure)
    await session.flush()
    return failure.id


async def _create_cv_version(session: AsyncSession, offer_id: int, profile_id: int) -> int:
    cv_version = CVVersion(
        offer_id=offer_id,
        profile_id=profile_id,
        cv_markdown="# CV",
        status="drafted",
    )
    session.add(cv_version)
    await session.flush()
    return cv_version.id


async def _create_application(session: AsyncSession, offer_id: int, profile_id: int) -> int:
    # "drafted" is recruFlow's own Application status vocabulary (CLAUDE.md's domain
    # glossary), distinct from the unrelated sjctl-track CLI's saved/applied/... states.
    application = Application(offer_id=offer_id, profile_id=profile_id, status="drafted")
    session.add(application)
    await session.flush()
    return application.id


async def _wipe_all_offers_and_dependents(session: AsyncSession) -> None:
    # DELETE /offers and GET /offers/cleanup-preview are deliberately global (no source/
    # connector scope, unlike every other endpoint in this file) -- they operate over every
    # offer in the table. db_test accumulates leftover offers across historical test runs
    # that a per-connector filter would normally isolate away from, so exact deleted/skipped
    # count assertions for these two endpoints require starting from a genuinely empty
    # table, not just cleaning up this test's own fixture rows. Sources are left untouched
    # (other tests assert on the live set of Source rows).
    await session.execute(delete(Application))
    await session.execute(delete(CVVersion))
    await session.execute(delete(MatchScore))
    await session.execute(delete(ScoringFailure))
    await session.execute(delete(OfferModel))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_returns_offers_from_multiple_sources_within_requested_scope(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # A request with no filters only returns page one against a dev DB that carries a large,
    # ever-growing real backlog, so two bare test offers would be buried past page one and
    # never come back — scope both sources to one shared connector instead so a single
    # `source` filter still exercises "multiple sources, one query" without competing
    # against the rest of the table.
    connector = f"multi-src-{uuid4()}"
    source_a = await _create_source(db_session, connector=connector)
    source_b = await _create_source(db_session, connector=connector)
    offer_a = await _create_offer(db_session, source_a)
    offer_b = await _create_offer(db_session, source_b)
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector})

        assert response.status_code == 200
        ids = {entry["id"] for entry in response.json()["items"]}
        assert offer_a in ids
        assert offer_b in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


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
        ids = {entry["id"] for entry in response.json()["items"]}
        assert offer_a in ids
        assert offer_b not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_remote(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Scoped to a dedicated connector: otherwise these two bare test offers compete
    # for page one against the dev DB's real backlog.
    connector = f"remote-filter-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    remote_offer = await _create_offer(db_session, source_id, remote=True)
    onsite_offer = await _create_offer(db_session, source_id, remote=False)
    await db_session.commit()

    try:
        remote_response = await client.get(
            "/offers", params={"source": connector, "remote": "true"}
        )
        onsite_response = await client.get(
            "/offers", params={"source": connector, "remote": "false"}
        )

        remote_ids = {entry["id"] for entry in remote_response.json()["items"]}
        onsite_ids = {entry["id"] for entry in onsite_response.json()["items"]}
        assert remote_offer in remote_ids
        assert onsite_offer not in remote_ids
        assert onsite_offer in onsite_ids
        assert remote_offer not in onsite_ids
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_seniority_substring_match(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Scoped to a dedicated connector: otherwise these two bare test offers compete
    # for page one against the dev DB's real backlog.
    connector = f"senior-filt-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    senior_offer = await _create_offer(db_session, source_id, seniority="senior, lead")
    junior_offer = await _create_offer(db_session, source_id, seniority="junior")
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector, "seniority": "senior"})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert senior_offer in ids
        assert junior_offer not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_filters_by_min_salary_meets_or_exceeds(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Scoped to a dedicated connector: otherwise these bare test offers compete
    # for page one against the dev DB's real backlog.
    connector = f"min-sal-filt-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    above_max = await _create_offer(db_session, source_id, salary_max=20000)
    below_max = await _create_offer(db_session, source_id, salary_max=10000)
    fallback_min = await _create_offer(db_session, source_id, salary_min=18000, salary_max=None)
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector, "min_salary": 15000})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert above_max in ids
        assert fallback_min in ids
        assert below_max not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_unknown_source_filter_returns_empty_list_not_error(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/offers", params={"source": "totally-unknown-connector"})

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


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

        ids = {entry["id"] for entry in response.json()["items"]}
        assert ids == {a_remote}
        assert a_onsite not in ids
        assert b_remote not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_orders_newest_first_by_default(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"order-test-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    older = await _create_offer(db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    newer = await _create_offer(db_session, source_id, posted_at=datetime(2026, 6, 1, tzinfo=UTC))
    no_posted_date = await _create_offer(db_session, source_id, posted_at=None)
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector})

        ids = [entry["id"] for entry in response.json()["items"]]
        assert ids == [newer, older, no_posted_date]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_paginates_with_limit_and_offset(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"page-test-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    third = await _create_offer(db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    second = await _create_offer(db_session, source_id, posted_at=datetime(2026, 2, 1, tzinfo=UTC))
    first = await _create_offer(db_session, source_id, posted_at=datetime(2026, 3, 1, tzinfo=UTC))
    await db_session.commit()

    try:
        page_one = await client.get(
            "/offers", params={"source": connector, "limit": 2, "offset": 0}
        )
        page_two = await client.get(
            "/offers", params={"source": connector, "limit": 2, "offset": 2}
        )

        assert [entry["id"] for entry in page_one.json()["items"]] == [first, second]
        assert page_one.json()["total"] == 3
        assert [entry["id"] for entry in page_two.json()["items"]] == [third]
        assert page_two.json()["total"] == 3
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_sorts_by_score_percent_desc_across_full_dataset(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Server-side sort must reflect the full dataset, not just the newest page: the
    # highest score here (92) belongs to the *oldest* posted offer, so a naive
    # posted_at-ordered page followed by client-side re-sort would never surface it
    # correctly once paginated.
    await _deactivate_all_profiles(db_session)
    connector = f"sort-score-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    low = await _create_offer(db_session, source_id, posted_at=datetime(2026, 6, 1, tzinfo=UTC))
    high = await _create_offer(db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    unscored = await _create_offer(
        db_session, source_id, posted_at=datetime(2026, 6, 2, tzinfo=UTC)
    )
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=low,
                profile_id=profile.id,
                engine="langchain",
                score_percent=30,
                dimensions={},
            ),
            MatchScore(
                offer_id=high,
                profile_id=profile.id,
                engine="langchain",
                score_percent=92,
                dimensions={},
            ),
        ]
    )
    await db_session.commit()

    try:
        response = await client.get(
            "/offers",
            params={"source": connector, "order_by": "score_percent", "order": "desc"},
        )

        ids = [entry["id"] for entry in response.json()["items"]]
        assert ids == [high, low, unscored]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_sorts_by_score_percent_asc_unscored_still_last(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"sort-asc-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    low = await _create_offer(db_session, source_id)
    high = await _create_offer(db_session, source_id)
    unscored = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=low,
                profile_id=profile.id,
                engine="langchain",
                score_percent=30,
                dimensions={},
            ),
            MatchScore(
                offer_id=high,
                profile_id=profile.id,
                engine="langchain",
                score_percent=92,
                dimensions={},
            ),
        ]
    )
    await db_session.commit()

    try:
        response = await client.get(
            "/offers",
            params={"source": connector, "order_by": "score_percent", "order": "asc"},
        )

        ids = [entry["id"] for entry in response.json()["items"]]
        assert ids == [low, high, unscored]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_score_sort_applies_before_pagination(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # Regression guard: page two of a score-sorted request must be the next-best
    # scores overall, not whatever posted_at-ordered offers landed there.
    await _deactivate_all_profiles(db_session)
    connector = f"sort-page-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    scores = {90: None, 70: None, 50: None, 30: None}
    offer_ids = {}
    for score in scores:
        offer_ids[score] = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=offer_ids[score],
                profile_id=profile.id,
                engine="langchain",
                score_percent=score,
                dimensions={},
            )
            for score in scores
        ]
    )
    await db_session.commit()

    try:
        page_two = await client.get(
            "/offers",
            params={
                "source": connector,
                "order_by": "score_percent",
                "order": "desc",
                "limit": 2,
                "offset": 2,
            },
        )

        ids = [entry["id"] for entry in page_two.json()["items"]]
        assert ids == [offer_ids[50], offer_ids[30]]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_order_asc_reverses_default_posted_at_sort(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"order-asc-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    older = await _create_offer(db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
    newer = await _create_offer(db_session, source_id, posted_at=datetime(2026, 6, 1, tzinfo=UTC))
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector, "order": "asc"})

        ids = [entry["id"] for entry in response.json()["items"]]
        assert ids == [older, newer]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_rejects_invalid_order_by(client: httpx.AsyncClient) -> None:
    response = await client.get("/offers", params={"order_by": "bogus_field"})

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_rejects_page_size_above_max(client: httpx.AsyncClient) -> None:
    response = await client.get("/offers", params={"limit": 10000})

    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_includes_active_profile_score_percent_inline(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"score-inline-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    scored_offer = await _create_offer(db_session, source_id)
    unscored_offer = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add(
        MatchScore(
            offer_id=scored_offer,
            profile_id=profile.id,
            engine="langchain",
            score_percent=77,
            dimensions={},
        )
    )
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector})

        by_id = {entry["id"]: entry["score_percent"] for entry in response.json()["items"]}
        assert by_id[scored_offer] == 77
        assert by_id[unscored_offer] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_inline_score_percent_uses_most_recent_score_for_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"score-latest-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=offer_id,
                profile_id=profile.id,
                engine="langchain",
                score_percent=62,
                dimensions={},
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            MatchScore(
                offer_id=offer_id,
                profile_id=profile.id,
                engine="langchain",
                score_percent=92,
                dimensions={},
                created_at=datetime(2026, 6, 2, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector})

        by_id = {entry["id"]: entry["score_percent"] for entry in response.json()["items"]}
        assert by_id[offer_id] == 92
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_min_score_keeps_offers_at_or_better(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"min-score-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    score_90 = await _create_offer(db_session, source_id)
    score_55 = await _create_offer(db_session, source_id)
    score_20 = await _create_offer(db_session, source_id)
    unscored = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=score_90,
                profile_id=profile.id,
                engine="langchain",
                score_percent=90,
                dimensions={},
            ),
            MatchScore(
                offer_id=score_55,
                profile_id=profile.id,
                engine="langchain",
                score_percent=55,
                dimensions={},
            ),
            MatchScore(
                offer_id=score_20,
                profile_id=profile.id,
                engine="langchain",
                score_percent=20,
                dimensions={},
            ),
        ]
    )
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector, "min_score": 50})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert ids == {score_90, score_55}
        assert score_20 not in ids
        assert unscored not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_min_score_scopes_to_active_profile_only(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"min-scope-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    active_profile = Profile(name=f"active-{uuid4()}", is_active=True, data={})
    other_profile = Profile(name=f"other-{uuid4()}", is_active=False, data={})
    db_session.add_all([active_profile, other_profile])
    await db_session.flush()
    db_session.add(
        MatchScore(
            offer_id=offer_id,
            profile_id=other_profile.id,
            engine="langchain",
            score_percent=95,
            dimensions={},
        )
    )
    await db_session.commit()

    try:
        response = await client.get("/offers", params={"source": connector, "min_score": 90})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert offer_id not in ids
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_detail_includes_applied_hide_notes_defaults(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    response = await client.get(f"/offers/{offer_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert body["hide"] is False
    assert body["notes"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_updates_only_fields_sent(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"patch-fields-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        response = await client.patch(f"/offers/{offer_id}", json={"applied": True})

        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is True
        assert body["hide"] is False
        assert body["notes"] is None

        follow_up = await client.get(f"/offers/{offer_id}")
        follow_up_body = follow_up.json()
        assert follow_up_body["applied"] is True
        assert follow_up_body["hide"] is False
        assert follow_up_body["notes"] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_empty_body_changes_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"patch-empty-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        response = await client.patch(f"/offers/{offer_id}", json={})

        assert response.status_code == 200
        body = response.json()
        assert body["applied"] is False
        assert body["hide"] is False
        assert body["notes"] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_unknown_offer_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.patch("/offers/999999999", json={"applied": True})

    assert response.status_code == 404
    assert "999999999" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_notes_no_max_length(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"patch-notes-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        long_notes = "x" * 5000
        response = await client.patch(f"/offers/{offer_id}", json={"notes": long_notes})

        assert response.status_code == 200
        assert response.json()["notes"] == long_notes
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_clearing_notes_with_explicit_null(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"patch-clear-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        first = await client.patch(f"/offers/{offer_id}", json={"notes": "foo"})
        assert first.json()["notes"] == "foo"

        second = await client.patch(f"/offers/{offer_id}", json={"notes": None})

        assert second.status_code == 200
        assert second.json()["notes"] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_detail_link_opened_at_starts_null(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    response = await client.get(f"/offers/{offer_id}")

    assert response.status_code == 200
    assert response.json()["link_opened_at"] is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_link_opened_sets_timestamp(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"link-open-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        response = await client.patch(f"/offers/{offer_id}", json={"link_opened": True})

        assert response.status_code == 200
        link_opened_at = response.json()["link_opened_at"]
        assert link_opened_at is not None

        follow_up = await client.get(f"/offers/{offer_id}")
        assert follow_up.json()["link_opened_at"] == link_opened_at
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_link_opened_is_idempotent(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"link-idem-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        first = await client.patch(f"/offers/{offer_id}", json={"link_opened": True})
        second = await client.patch(f"/offers/{offer_id}", json={"link_opened": True})

        assert first.json()["link_opened_at"] == second.json()["link_opened_at"]
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_link_opened_false_does_not_set_timestamp(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"link-false-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        response = await client.patch(f"/offers/{offer_id}", json={"link_opened": False})

        assert response.status_code == 200
        assert response.json()["link_opened_at"] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_patch_offer_link_opened_composes_with_other_fields(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"link-comp-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        response = await client.patch(
            f"/offers/{offer_id}", json={"link_opened": True, "applied": True}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["link_opened_at"] is not None
        assert body["applied"] is True
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_includes_link_opened_at(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"list-lo-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    opened_id = await _create_offer(db_session, source_id)
    unopened_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    opened_at = datetime.now(UTC)
    try:
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == opened_id).values(link_opened_at=opened_at)
        )
        await db_session.commit()

        response = await client.get("/offers", params={"source": connector})

        assert response.status_code == 200
        by_id = {entry["id"]: entry for entry in response.json()["items"]}
        assert by_id[opened_id]["link_opened_at"] is not None
        assert by_id[unopened_id]["link_opened_at"] is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_excludes_hidden_by_default(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"hide-default-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    visible_id = await _create_offer(db_session, source_id)
    hidden_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == hidden_id).values(hide=True)
        )
        await db_session.commit()

        response = await client.get("/offers", params={"source": connector})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert ids == {visible_id}
        assert response.json()["total"] == 1
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_show_hidden_true_includes_both(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"hide-show-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    visible_id = await _create_offer(db_session, source_id)
    hidden_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == hidden_id).values(hide=True)
        )
        await db_session.commit()

        response = await client.get("/offers", params={"source": connector, "show_hidden": "true"})

        ids = {entry["id"] for entry in response.json()["items"]}
        assert ids == {visible_id, hidden_id}
        assert response.json()["total"] == 2
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_applied_filter_is_tri_state(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    connector = f"applied-tri-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    applied_id = await _create_offer(db_session, source_id)
    not_applied_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    try:
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == applied_id).values(applied=True)
        )
        await db_session.commit()

        applied_true = await client.get("/offers", params={"source": connector, "applied": "true"})
        applied_false = await client.get(
            "/offers", params={"source": connector, "applied": "false"}
        )
        applied_omitted = await client.get("/offers", params={"source": connector})

        assert {e["id"] for e in applied_true.json()["items"]} == {applied_id}
        assert {e["id"] for e in applied_false.json()["items"]} == {not_applied_id}
        assert {e["id"] for e in applied_omitted.json()["items"]} == {
            applied_id,
            not_applied_id,
        }
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_offers_composes_applied_hidden_min_score(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    connector = f"compose-filt-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    matching = await _create_offer(db_session, source_id)
    wrong_applied = await _create_offer(db_session, source_id)
    wrong_hidden = await _create_offer(db_session, source_id)
    wrong_score = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()
    db_session.add_all(
        [
            MatchScore(
                offer_id=matching,
                profile_id=profile.id,
                engine="langchain",
                score_percent=80,
                dimensions={},
            ),
            MatchScore(
                offer_id=wrong_applied,
                profile_id=profile.id,
                engine="langchain",
                score_percent=80,
                dimensions={},
            ),
            MatchScore(
                offer_id=wrong_hidden,
                profile_id=profile.id,
                engine="langchain",
                score_percent=80,
                dimensions={},
            ),
            MatchScore(
                offer_id=wrong_score,
                profile_id=profile.id,
                engine="langchain",
                score_percent=10,
                dimensions={},
            ),
        ]
    )
    await db_session.commit()

    try:
        await db_session.execute(
            update(OfferModel)
            .where(OfferModel.id.in_([matching, wrong_hidden]))
            .values(applied=True)
        )
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == wrong_applied).values(applied=False)
        )
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == wrong_hidden).values(hide=True)
        )
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == wrong_score).values(applied=True)
        )
        await db_session.commit()

        response = await client.get(
            "/offers",
            params={
                "source": connector,
                "applied": "true",
                "show_hidden": "false",
                "min_score": 50,
            },
        )

        ids = {entry["id"] for entry in response.json()["items"]}
        assert ids == {matching}
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reingest_does_not_reset_user_owned_fields(db_session: AsyncSession) -> None:
    connector = f"reingest-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    mapped_fields: dict[str, object] = {
        "source_id": source_id,
        "title": "Backend Engineer",
        "company": "Acme",
        "canonical_url": _unique_url("reingest"),
    }

    try:
        first_result = await ingest_offer(db_session, mapped_fields, raw_payload={})
        await db_session.commit()
        assert first_result is not None
        offer_id = first_result[0].id

        await db_session.execute(
            update(OfferModel).where(OfferModel.id == offer_id).values(applied=True, notes="foo")
        )
        await db_session.commit()

        second_result = await ingest_offer(db_session, mapped_fields, raw_payload={})
        await db_session.commit()

        assert second_result is not None
        assert second_result[1] is False

        row = await db_session.get(OfferModel, offer_id)
        assert row is not None
        assert row.applied is True
        assert row.notes == "foo"
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reingest_does_not_reset_link_opened_at(db_session: AsyncSession) -> None:
    connector = f"reingest-lo-{uuid4()}"
    source_id = await _create_source(db_session, connector=connector)
    mapped_fields: dict[str, object] = {
        "source_id": source_id,
        "title": "Backend Engineer",
        "company": "Acme",
        "canonical_url": _unique_url("reingest-link-opened"),
    }

    try:
        first_result = await ingest_offer(db_session, mapped_fields, raw_payload={})
        await db_session.commit()
        assert first_result is not None
        offer_id = first_result[0].id

        opened_at = datetime.now(UTC)
        await db_session.execute(
            update(OfferModel).where(OfferModel.id == offer_id).values(link_opened_at=opened_at)
        )
        await db_session.commit()

        second_result = await ingest_offer(db_session, mapped_fields, raw_payload={})
        await db_session.commit()

        assert second_result is not None
        assert second_result[1] is False

        row = await db_session.get(OfferModel, offer_id)
        assert row is not None
        assert row.link_opened_at is not None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


async def _deactivate_all_profiles(session: AsyncSession) -> None:
    # Deactivating (rather than deleting) avoids tripping match_scores' profile_id
    # FK constraint on profiles owned by unrelated tests.
    await session.execute(update(Profile).values(is_active=False))
    await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_score_returns_most_recent_score_for_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()

    earlier = MatchScore(
        offer_id=offer_id,
        profile_id=profile.id,
        engine="langchain",
        score_percent=62,
        dimensions={},
        rationale="earlier",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    later = MatchScore(
        offer_id=offer_id,
        profile_id=profile.id,
        engine="langchain",
        score_percent=92,
        dimensions={},
        rationale="later",
        created_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    db_session.add_all([earlier, later])
    await db_session.commit()

    response = await client.get(f"/offers/{offer_id}/score")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == later.id
    assert body["score_percent"] == 92


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_score_returns_null_when_offer_has_no_score(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.commit()

    response = await client.get(f"/offers/{offer_id}/score")

    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_score_returns_null_when_no_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    await db_session.commit()

    response = await client.get(f"/offers/{offer_id}/score")

    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_offer_score_unknown_offer_id_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/offers/999999999/score")

    assert response.status_code == 404
    assert "999999999" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rescoring_offer_inserts_new_row_without_overwriting_existing(
    db_session: AsyncSession,
) -> None:
    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session)
    offer_id = await _create_offer(db_session, source_id)
    profile = Profile(name=f"profile-{uuid4()}", is_active=True, data={})
    db_session.add(profile)
    await db_session.flush()

    db_session.add(
        MatchScore(
            offer_id=offer_id,
            profile_id=profile.id,
            engine="langchain",
            score_percent=77,
            dimensions={},
            rationale="first",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()

    db_session.add(
        MatchScore(
            offer_id=offer_id,
            profile_id=profile.id,
            engine="langchain",
            score_percent=92,
            dimensions={},
            rationale="second",
            created_at=datetime(2026, 6, 1, tzinfo=UTC) + timedelta(hours=1),
        )
    )
    await db_session.commit()

    rows = (
        (
            await db_session.execute(
                select(MatchScore).where(
                    MatchScore.offer_id == offer_id, MatchScore.profile_id == profile.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_offers_removes_offers_older_than_cutoff(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _wipe_all_offers_and_dependents(db_session)
    source_id = await _create_source(db_session)
    try:
        cutoff = datetime(2026, 3, 1, tzinfo=UTC)
        older = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        newer = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        await db_session.commit()

        response = await client.delete("/offers", params={"older_than": cutoff.isoformat()})

        assert response.status_code == 200
        assert response.json() == {"deleted": 1, "skipped": 0}
        assert await db_session.get(OfferModel, older) is None
        assert await db_session.get(OfferModel, newer) is not None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_offers_skips_pipeline_offers(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _wipe_all_offers_and_dependents(db_session)
    source_id = await _create_source(db_session)
    try:
        cutoff = datetime(2026, 3, 1, tzinfo=UTC)
        old_no_application = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        old_with_application = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 2, tzinfo=UTC)
        )
        profile_id = await _create_profile(db_session)
        application_id = await _create_application(db_session, old_with_application, profile_id)
        await db_session.commit()

        response = await client.delete("/offers", params={"older_than": cutoff.isoformat()})

        assert response.status_code == 200
        assert response.json() == {"deleted": 1, "skipped": 1}
        assert await db_session.get(OfferModel, old_no_application) is None
        assert await db_session.get(OfferModel, old_with_application) is not None
        assert await db_session.get(Application, application_id) is not None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_offers_skips_null_posted_at(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _wipe_all_offers_and_dependents(db_session)
    source_id = await _create_source(db_session)
    try:
        undated = await _create_offer(db_session, source_id, posted_at=None)
        await db_session.commit()

        far_future_cutoff = datetime(2099, 1, 1, tzinfo=UTC)
        response = await client.delete(
            "/offers", params={"older_than": far_future_cutoff.isoformat()}
        )

        assert response.status_code == 200
        assert response.json() == {"deleted": 0, "skipped": 0}
        assert await db_session.get(OfferModel, undated) is not None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_offers_cascades_related_rows(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _wipe_all_offers_and_dependents(db_session)
    source_id = await _create_source(db_session)
    try:
        cutoff = datetime(2026, 3, 1, tzinfo=UTC)
        offer_id = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        profile_id = await _create_profile(db_session)
        score_id = await _create_match_score(db_session, offer_id, profile_id)
        failure_id = await _create_scoring_failure(db_session, offer_id, profile_id)
        cv_version_id = await _create_cv_version(db_session, offer_id, profile_id)
        await db_session.commit()

        response = await client.delete("/offers", params={"older_than": cutoff.isoformat()})

        assert response.status_code == 200
        assert response.json() == {"deleted": 1, "skipped": 0}
        assert await db_session.get(OfferModel, offer_id) is None
        assert await db_session.get(MatchScore, score_id) is None
        assert await db_session.get(ScoringFailure, failure_id) is None
        assert await db_session.get(CVVersion, cv_version_id) is None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_offers_missing_older_than_returns_422(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    source_id = await _create_source(db_session)
    try:
        await _create_offer(db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC))
        await db_session.commit()

        before = (
            await db_session.execute(select(func.count()).select_from(OfferModel))
        ).scalar_one()

        response = await client.delete("/offers")

        assert response.status_code == 422
        after = (
            await db_session.execute(select(func.count()).select_from(OfferModel))
        ).scalar_one()
        assert after == before
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_preview_offer_cleanup_reports_counts_without_deleting(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _wipe_all_offers_and_dependents(db_session)
    source_id = await _create_source(db_session)
    try:
        cutoff = datetime(2026, 3, 1, tzinfo=UTC)
        old_no_application = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 1, tzinfo=UTC)
        )
        old_with_application = await _create_offer(
            db_session, source_id, posted_at=datetime(2026, 1, 2, tzinfo=UTC)
        )
        profile_id = await _create_profile(db_session)
        await _create_application(db_session, old_with_application, profile_id)
        await db_session.commit()

        response = await client.get(
            "/offers/cleanup-preview", params={"older_than": cutoff.isoformat()}
        )

        assert response.status_code == 200
        assert response.json() == {"would_delete": 1, "would_skip": 1}
        assert await db_session.get(OfferModel, old_no_application) is not None
        assert await db_session.get(OfferModel, old_with_application) is not None
    finally:
        await _delete_sources_with_offers(db_session, [source_id])
