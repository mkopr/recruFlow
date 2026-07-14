from typing import Any

import pytest
from app.connectors.remoteok import REMOTEOK_URL, RemoteOKConnector
from app.ingestion.registry import CONNECTOR_REGISTRY


def test_default_url_returns_remoteok_api() -> None:
    assert RemoteOKConnector().default_url() == "https://remoteok.com/api"
    assert REMOTEOK_URL == "https://remoteok.com/api"


def test_build_params_returns_empty_dict_regardless_of_config() -> None:
    connector = RemoteOKConnector()

    assert connector.build_params({"anything": "x"}, cursor=0, page_size=100) == {}


def test_extract_offers_drops_leading_metadata_element() -> None:
    connector = RemoteOKConnector()
    payload = [
        {"last_updated": "x", "legal": "y"},
        {"id": 1, "position": "A"},
        {"id": 2, "position": "B"},
    ]

    result = connector.extract_offers(payload)

    assert result == [{"id": 1, "position": "A"}, {"id": 2, "position": "B"}]


def test_extract_offers_returns_none_for_empty_list() -> None:
    connector = RemoteOKConnector()

    assert connector.extract_offers([]) is None


def test_extract_offers_returns_none_for_non_list_payload() -> None:
    connector = RemoteOKConnector()

    assert connector.extract_offers({"jobs": []}) is None


def test_extract_offers_returns_none_when_only_metadata_element_present() -> None:
    connector = RemoteOKConnector()

    assert connector.extract_offers([{"last_updated": "x"}]) == []


def test_next_cursor_always_returns_none() -> None:
    connector = RemoteOKConnector()

    assert connector.next_cursor({}, [{}] * 5, cursor=0, page_size=100) is None
    assert connector.next_cursor({}, [], cursor=0, page_size=100) is None


def test_map_remoteok_offer_maps_all_known_fields() -> None:
    raw = {
        "id": 12345,
        "slug": "acme-backend-engineer",
        "epoch": 1782888932,
        "date": "2026-06-01T00:00:00Z",
        "company": "Acme",
        "position": "Backend Engineer",
        "tags": ["python", "backend"],
        "description": "great role",
        "location": "Worldwide",
        "apply_url": "https://remoteok.com/apply/12345",
        "url": "https://remoteok.com/remote-jobs/12345",
        "salary_min": 60000,
        "salary_max": 90000,
    }

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["source_id"] == 1
    assert result["external_id"] == "12345"
    assert result["canonical_url"] == "https://remoteok.com/remote-jobs/12345"
    assert result["title"] == "Backend Engineer"
    assert result["company"] == "Acme"
    assert result["location"] == "Worldwide"
    assert result["remote"] is True
    assert result["seniority"] is None
    assert result["salary_min"] == 60000
    assert result["salary_max"] == 90000
    assert result["salary_currency"] == "USD"
    assert result["contract_type"] is None
    assert result["posted_at"] == "2026-06-01T00:00:00Z"
    assert result["description"] == "great role"
    assert result["industry_tags"] == ["python", "backend"]


def test_map_remoteok_offer_falls_back_to_apply_url_when_url_absent() -> None:
    raw = {"apply_url": "https://remoteok.com/apply/999"}

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["canonical_url"] == "https://remoteok.com/apply/999"


def test_map_remoteok_offer_normalizes_zero_salary_pair_to_none() -> None:
    raw = {"salary_min": 0, "salary_max": 0}

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["salary_min"] is None
    assert result["salary_max"] is None


def test_map_remoteok_offer_normalizes_each_zero_salary_field_independently() -> None:
    raw = {"salary_min": 0, "salary_max": 50000}

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["salary_min"] is None
    assert result["salary_max"] == 50000


def test_map_remoteok_offer_uses_usd_not_pln_as_salary_currency() -> None:
    raw = {"salary_min": 60000, "salary_max": 90000}

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["salary_currency"] == "USD"


def test_map_remoteok_offer_never_infers_seniority_from_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connectors import remoteok

    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("normalize_seniority must never be called by RemoteOKConnector")

    monkeypatch.setattr(remoteok, "normalize_seniority", _fail, raising=False)

    raw = {"tags": ["senior", "python", "remote"]}

    result = RemoteOKConnector().map_offer(1, raw)

    assert result["seniority"] is None


def test_map_remoteok_offer_handles_missing_optional_fields() -> None:
    result = RemoteOKConnector().map_offer(1, {})

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


def test_remoteok_registered_in_connector_registry() -> None:
    from app.ingestion.normalize import REMOTEOK

    assert REMOTEOK in CONNECTOR_REGISTRY
    assert CONNECTOR_REGISTRY[REMOTEOK].label == "RemoteOK"
