from typing import Any

import pytest
from app.connectors.remotive import REMOTIVE_URL, RemotiveConnector
from app.ingestion.registry import CONNECTOR_REGISTRY


def test_default_url_returns_remotive_api() -> None:
    assert RemotiveConnector().default_url() == "https://remotive.com/api/remote-jobs"
    assert REMOTIVE_URL == "https://remotive.com/api/remote-jobs"


def test_build_params_returns_empty_dict_regardless_of_config() -> None:
    connector = RemotiveConnector()

    assert connector.build_params({"anything": "x"}, cursor=0, page_size=100) == {}


def test_next_cursor_always_returns_none() -> None:
    connector = RemotiveConnector()

    assert connector.next_cursor({}, [{}] * 5, cursor=0, page_size=100) is None
    assert connector.next_cursor({}, [], cursor=0, page_size=100) is None


def _fake_fetch_json(payload: Any) -> Any:
    calls: list[dict[str, Any]] = []

    def _fetch_json(url: str, *, source_name: str, logger: Any, params: dict[str, Any]) -> Any:
        calls.append({"url": url, "params": params})
        return payload

    _fetch_json.calls = calls  # type: ignore[attr-defined]
    return _fetch_json


def test_fetch_page_makes_exactly_one_request_regardless_of_configured_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # BUG45: Remotive's `category` query param is a no-op on the live API -- every category
    # value returns the identical full snapshot -- so N configured categories must still mean
    # exactly one HTTP request, with the filtering happening client-side afterwards instead.
    from app.connectors import remotive

    fake = _fake_fetch_json(
        {
            "jobs": [
                {"id": 1, "category": "Software Development"},
                {"id": 2, "category": "Quality Assurance"},
            ]
        }
    )
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    result = connector.fetch_page(
        {"categories": ["software-development", "qa"]}, cursor=0, page_size=100
    )

    assert result is not None
    offers, next_cursor = result
    assert offers == [
        {"id": 1, "category": "Software Development"},
        {"id": 2, "category": "Quality Assurance"},
    ]
    assert next_cursor is None
    assert fake.calls == [{"url": REMOTIVE_URL, "params": {}}]


def test_fetch_page_uses_default_categories_when_none_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connectors import remotive

    fake = _fake_fetch_json({"jobs": [{"id": 1, "category": "Software Development"}]})
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    result = connector.fetch_page({}, cursor=0, page_size=100)

    assert result is not None
    offers, _ = result
    assert offers == [{"id": 1, "category": "Software Development"}]


def test_fetch_page_filters_out_categories_not_in_configured_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Live evidence (2026-07-15): non-configured categories like Sales/Marketing/Medical had
    # been silently reaching the DB since P3US43 because server-side filtering never actually
    # worked -- this is the client-side filter that now makes the configured scope real.
    from app.connectors import remotive

    fake = _fake_fetch_json(
        {
            "jobs": [
                {"id": 1, "category": "Software Development"},
                {"id": 2, "category": "Sales"},
            ]
        }
    )
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    result = connector.fetch_page({"categories": ["software-development"]}, cursor=0, page_size=100)

    assert result is not None
    offers, _ = result
    assert offers == [{"id": 1, "category": "Software Development"}]


def test_fetch_page_warns_and_ignores_unrecognized_category_slug(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.connectors import remotive

    fake = _fake_fetch_json({"jobs": [{"id": 1, "category": "Software Development"}]})
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    with caplog.at_level("WARNING"):
        result = connector.fetch_page(
            {"categories": ["software-development", "not-a-real-slug"]}, cursor=0, page_size=100
        )

    assert result is not None
    offers, _ = result
    assert offers == [{"id": 1, "category": "Software Development"}]
    assert any("unrecognized category slug" in record.message for record in caplog.records)


def test_fetch_page_extracts_via_jobs_envelope_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.connectors import remotive

    fake = _fake_fetch_json(
        {
            "jobs": [
                {"id": 1, "category": "Software Development"},
                {"id": 2, "category": "Software Development"},
            ]
        }
    )
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    result = connector.fetch_page({"categories": ["software-development"]}, cursor=0, page_size=100)

    assert result is not None
    offers, _ = result
    assert offers == [
        {"id": 1, "category": "Software Development"},
        {"id": 2, "category": "Software Development"},
    ]


def test_fetch_page_returns_none_when_response_missing_jobs_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.connectors import remotive

    fake = _fake_fetch_json({"unexpected": "shape"})
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    with caplog.at_level("ERROR"):
        result = connector.fetch_page(
            {"categories": ["software-development"]}, cursor=0, page_size=100
        )

    assert result is None
    assert any(
        "Remotive returned unexpected JSON shape" in record.message for record in caplog.records
    )


def test_fetch_page_returns_none_when_fetch_json_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.connectors import remotive

    fake = _fake_fetch_json(None)
    monkeypatch.setattr(remotive, "fetch_json", fake)

    connector = RemotiveConnector()
    result = connector.fetch_page({"categories": ["software-development"]}, cursor=0, page_size=100)

    assert result is None


def test_map_remotive_offer_maps_all_known_fields() -> None:
    raw = {
        "id": 12345,
        "url": "https://remotive.com/remote-jobs/software-dev/backend-engineer-12345",
        "title": "Backend Engineer",
        "company_name": "Acme",
        "category": "Software Development",
        "tags": ["python", "backend"],
        "job_type": "full_time",
        "publication_date": "2026-06-01T00:00:00",
        "candidate_required_location": "Worldwide",
        "salary": "$70,000 - $90,000",
        "description": "great role",
    }

    result = RemotiveConnector().map_offer(1, raw)

    assert result["source_id"] == 1
    assert result["external_id"] == "12345"
    assert result["canonical_url"] == raw["url"]
    assert result["title"] == "Backend Engineer"
    assert result["company"] == "Acme"
    assert result["location"] == "Worldwide"
    assert result["remote"] is True
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_currency"] == "USD"
    assert result["contract_type"] is None
    assert result["posted_at"] == "2026-06-01T00:00:00+00:00"
    assert result["description"] == "great role"
    assert result["industry_tags"] == ["Software Development", "python", "backend"]


def test_map_remotive_offer_attaches_utc_to_naive_publication_date() -> None:
    # Remotive's `publication_date` has no timezone suffix (confirmed live 2026-07-14) --
    # passing it through unnormalized crashes `run_paginated_ingestion`'s fetch-range filter
    # with "can't compare offset-naive and offset-aware datetimes" on every real run.
    raw = {"publication_date": "2026-07-13T07:05:10"}

    result = RemotiveConnector().map_offer(1, raw)

    assert result["posted_at"] == "2026-07-13T07:05:10+00:00"


def test_map_remotive_offer_preserves_raw_salary_only_in_raw_payload() -> None:
    raw = {"salary": "$70,000 - $90,000"}

    result = RemotiveConnector().map_offer(1, raw)

    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert all(not isinstance(value, str) or "70,000" not in value for value in result.values())


def test_map_remotive_offer_handles_missing_optional_fields() -> None:
    result = RemotiveConnector().map_offer(1, {})

    assert result["external_id"] is None
    assert result["canonical_url"] is None
    assert result["title"] == ""
    assert result["company"] == ""
    assert result["location"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["salary_currency"] == "USD"
    assert result["contract_type"] is None
    assert result["posted_at"] is None
    assert result["description"] is None
    assert result["industry_tags"] == []
    assert result["remote"] is True
    assert result["seniority"] is None


def test_remotive_registered_in_connector_registry() -> None:
    from app.ingestion.normalize import REMOTIVE

    assert REMOTIVE in CONNECTOR_REGISTRY
    assert CONNECTOR_REGISTRY[REMOTIVE].label == "Remotive"
