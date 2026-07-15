from collections.abc import AsyncGenerator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from app.db.models import Profile as ProfileModel
from app.db.models import Source
from app.ingestion import registry
from app.ingestion.registry import ConnectorSpec
from app.ingestion.types import IngestionResult
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_offers_routes import (
    _create_match_score,
    _create_offer,
    _create_profile,
    _create_source,
    _deactivate_all_profiles,
    _delete_sources_with_offers,
)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _fake_connector(label: str = "fake") -> str:
    return f"{label}-{uuid4()}"


def _register_fake_connector(monkeypatch: pytest.MonkeyPatch, connector: str) -> None:
    async def _unused_dispatch(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        raise AssertionError("never dispatched by this test")

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        connector,
        ConnectorSpec(name=connector, label=connector, dispatch=_unused_dispatch),
    )


def _connector_option(body: list[dict[str, object]], connector: str) -> dict[str, object]:
    return next(entry for entry in body if entry["id"] == connector)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_connectors_matches_registry(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Monkeypatching a throwaway extra entry into CONNECTOR_REGISTRY and asserting it appears
    # in the response proves the endpoint reads live off the registry rather than a hardcoded
    # frontend-facing list.
    async def _unused_dispatch(
        session: AsyncSession, source: Source, force_refresh: bool
    ) -> IngestionResult:
        raise AssertionError("never dispatched by this test")

    monkeypatch.setitem(
        registry.CONNECTOR_REGISTRY,
        "throwaway",
        ConnectorSpec(name="throwaway", label="Throwaway", dispatch=_unused_dispatch),
    )

    response = await client.get("/connectors")

    assert response.status_code == 200
    body = response.json()
    expected = {(spec.name, spec.label) for spec in registry.CONNECTOR_REGISTRY.values()}
    actual = {(entry["id"], entry["label"]) for entry in body}
    assert actual == expected
    assert ("throwaway", "Throwaway") in actual


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_connectors_reports_supports_fetch_scope_correctly(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/connectors")

    assert response.status_code == 200
    body = response.json()
    supported = {entry["id"] for entry in body if entry["supports_fetch_scope"]}
    unsupported = {entry["id"] for entry in body if not entry["supports_fetch_scope"]}
    assert supported == {"solid_jobs", "bulldogjob", "pracuj"}
    assert unsupported == set(registry.CONNECTOR_REGISTRY.keys()) - supported


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectors_offer_count_matches_actual_row_count(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector_a = _fake_connector("a")
    connector_b = _fake_connector("b")
    _register_fake_connector(monkeypatch, connector_a)
    _register_fake_connector(monkeypatch, connector_b)

    source_a = await _create_source(db_session, connector=connector_a)
    source_b = await _create_source(db_session, connector=connector_b)
    try:
        for _ in range(3):
            await _create_offer(db_session, source_a)
        for _ in range(2):
            await _create_offer(db_session, source_b)
        await db_session.commit()

        response = await client.get("/connectors")

        assert response.status_code == 200
        body = response.json()
        assert _connector_option(body, connector_a)["offer_count"] == 3
        assert _connector_option(body, connector_b)["offer_count"] == 2
    finally:
        await _delete_sources_with_offers(db_session, [source_a, source_b])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectors_offer_count_includes_hidden_and_applied_offers(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _register_fake_connector(monkeypatch, connector)

    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id, hide=True)
        await _create_offer(db_session, source_id, applied=True)
        await db_session.commit()

        response = await client.get("/connectors")

        assert response.status_code == 200
        body = response.json()
        assert _connector_option(body, connector)["offer_count"] == 2
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectors_scored_unscored_split_matches_active_profile(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _register_fake_connector(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        active_profile_id = await _create_profile(db_session)
        scored_offer = await _create_offer(db_session, source_id)
        await _create_offer(db_session, source_id)
        await _create_match_score(db_session, scored_offer, active_profile_id)
        await db_session.commit()

        response = await client.get("/connectors")

        assert response.status_code == 200
        entry = _connector_option(response.json(), connector)
        assert entry["scored_count"] == 1
        assert entry["unscored_count"] == 1
        assert entry["offer_count"] == 2
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectors_scored_count_ignores_other_profiles(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _register_fake_connector(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        active_profile_id = await _create_profile(db_session)
        inactive_profile = ProfileModel(name=f"profile-{uuid4()}", is_active=False, data={})
        db_session.add(inactive_profile)
        await db_session.flush()

        offer_id = await _create_offer(db_session, source_id)
        await _create_match_score(db_session, offer_id, inactive_profile.id)
        await db_session.commit()

        response = await client.get("/connectors")

        assert response.status_code == 200
        entry = _connector_option(response.json(), connector)
        assert entry["scored_count"] == 0
        assert entry["unscored_count"] == 1
        assert active_profile_id != inactive_profile.id
    finally:
        await _delete_sources_with_offers(db_session, [source_id])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connectors_no_active_profile_means_everything_unscored(
    client: httpx.AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = _fake_connector()
    _register_fake_connector(monkeypatch, connector)

    await _deactivate_all_profiles(db_session)
    source_id = await _create_source(db_session, connector=connector)
    try:
        await _create_offer(db_session, source_id)
        await _create_offer(db_session, source_id)
        await db_session.commit()

        response = await client.get("/connectors")

        assert response.status_code == 200
        entry = _connector_option(response.json(), connector)
        assert entry["scored_count"] == 0
        assert entry["unscored_count"] == entry["offer_count"] == 2
    finally:
        await _delete_sources_with_offers(db_session, [source_id])
