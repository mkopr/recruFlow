import xml.etree.ElementTree as ET
from typing import Any
from uuid import uuid4

import httpx
import pytest
from app.connectors.we_work_remotely import WE_WORK_REMOTELY_RSS_URL, run_we_work_remotely_ingestion
from app.db.models import IngestionFailure, Source
from app.db.models import Offer as OfferModel
from app.ingestion.normalize import WE_WORK_REMOTELY
from app.llm.matcher import _MatcherOutput
from app.scoring.batch import run_batch_scoring
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_batch_scoring import _create_profile, _delete_sources_and_dependents
from tests.integration.test_langchain_matcher_batch import _STRONG_OUTPUT_KWARGS, _FakeChain
from tests.integration.test_offers_routes import _deactivate_all_profiles

_ITEM_FIELDS: tuple[str, ...] = (
    "title",
    "region",
    "country",
    "state",
    "skills",
    "category",
    "type",
    "description",
    "pubDate",
    "guid",
    "link",
)


class _FakeResponse:
    def __init__(self, *, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _item(job_id: int, **overrides: Any) -> dict[str, str | None]:
    item: dict[str, str | None] = {
        "title": f"Acme Corp {job_id}: Senior Backend Engineer",
        "link": f"https://weworkremotely.com/remote-jobs/acme-corp-{job_id}",
        "guid": f"https://weworkremotely.com/remote-jobs/acme-corp-{job_id}",
        "pubDate": "Tue, 14 Jul 2026 15:29:26 +0000",
        "region": "Anywhere in the World",
        "country": "Germany",
        "state": None,
        "skills": "Python, Django",
        "category": "Programming",
        "type": "Full-Time",
        "description": (
            "<p><strong>Headquarters:</strong> Berlin</p>"
            "<p><strong>Up to USD 100,000</strong> per year</p>"
        ),
    }
    item.update(overrides)
    return item


def _build_rss(items: list[dict[str, str | None]]) -> str:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "We Work Remotely"
    for item_data in items:
        item_el = ET.SubElement(channel, "item")
        for field in _ITEM_FIELDS:
            value = item_data.get(field)
            if value is not None:
                ET.SubElement(item_el, field).text = value
    return ET.tostring(rss, encoding="unicode")


def _expected_raw_payload(item_data: dict[str, str | None]) -> dict[str, str | None]:
    return {field: item_data.get(field) or None for field in _ITEM_FIELDS}


def _feed_response(items: list[dict[str, str | None]]) -> Any:
    rss_text = _build_rss(items)

    def _get(url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> _FakeResponse:
        assert url == WE_WORK_REMOTELY_RSS_URL
        return _FakeResponse(text=rss_text)

    return _get


async def _create_source(session: AsyncSession, connector: str | None = None) -> Source:
    source = Source(name=f"we-work-remotely-{uuid4()}", connector=connector, config_json={})
    session.add(source)
    await session.flush()
    return source


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_persists_and_maps_offers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    job1 = _item(int(uuid4().int % 1_000_000))
    job2 = _item(int(uuid4().int % 1_000_000))

    monkeypatch.setattr(httpx, "get", _feed_response([job1, job2]))

    result = await run_we_work_remotely_ingestion(db_session, source)
    await db_session.commit()

    assert result.ok is True
    assert result.fetched == 2
    assert result.created == 2

    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    jobs_by_url = {job1["link"]: job1, job2["link"]: job2}
    for row in rows:
        assert row.remote is True
        expected_job = jobs_by_url[row.canonical_url]
        assert row.raw_payload == _expected_raw_payload(expected_job)
        assert row.salary_max == 100000
        assert row.salary_currency == "USD"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_rerun_dedups_across_runs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    job = _item(int(uuid4().int % 1_000_000))

    monkeypatch.setattr(httpx, "get", _feed_response([job]))

    first = await run_we_work_remotely_ingestion(db_session, source)
    await db_session.commit()
    second = await run_we_work_remotely_ingestion(db_session, source)
    await db_session.commit()

    assert first.created == 1
    assert second.fetched == 1
    assert second.created == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_respects_fetch_range(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    source.config_json = {
        "fetch_range": {"mode": "range", "since": "2026-07-01T00:00:00+00:00", "until": None},
    }
    in_range_job = _item(int(uuid4().int % 1_000_000), pubDate="Mon, 13 Jul 2026 07:05:10 +0000")
    out_of_range_job = _item(
        int(uuid4().int % 1_000_000), pubDate="Mon, 01 Jun 2026 00:00:00 +0000"
    )

    monkeypatch.setattr(httpx, "get", _feed_response([in_range_job, out_of_range_job]))

    result = await run_we_work_remotely_ingestion(db_session, source)
    await db_session.commit()

    assert result.ok is True
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].canonical_url == in_range_job["link"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_records_dead_letter_when_company_unparseable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)
    good_job = _item(int(uuid4().int % 1_000_000))
    # No ": " separator in the title -- `_split_company_and_title` can't isolate a company,
    # so `map_offer` falls back to `company=""`, which fails `Offer`'s min_length=1 and routes
    # through the existing VALIDATION_FAILED dead-letter path.
    bad_job = _item(int(uuid4().int % 1_000_000), title="Senior Backend Engineer no colon here")

    monkeypatch.setattr(httpx, "get", _feed_response([good_job, bad_job]))

    result = await run_we_work_remotely_ingestion(db_session, source)
    await db_session.commit()

    assert result.created == 1
    rows = (
        (await db_session.execute(select(OfferModel).where(OfferModel.source_id == source.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].canonical_url == good_job["link"]

    failures = (
        (
            await db_session.execute(
                select(IngestionFailure).where(IngestionFailure.source_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(failures) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_returns_failure_result_on_first_page_fetch_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session)

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    result = await run_we_work_remotely_ingestion(db_session, source)

    assert result.ok is False
    assert result.error_message is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_we_work_remotely_ingestion_scoring_eligibility(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = await _create_source(db_session, connector=WE_WORK_REMOTELY)
    job = _item(int(uuid4().int % 1_000_000), description=None)
    monkeypatch.setattr(httpx, "get", _feed_response([job]))

    try:
        ingestion_result = await run_we_work_remotely_ingestion(db_session, source)
        await db_session.commit()
        assert ingestion_result.created == 1

        await _deactivate_all_profiles(db_session)
        await _create_profile(db_session)
        await db_session.commit()

        summary = await run_batch_scoring(
            db_session,
            connectors={WE_WORK_REMOTELY},
            chain_factory=lambda: _FakeChain(_MatcherOutput(**_STRONG_OUTPUT_KWARGS)),
        )
        await db_session.commit()

        assert summary.scored == 1
        assert summary.failed == 0
    finally:
        await _delete_sources_and_dependents(db_session, [source.id])
