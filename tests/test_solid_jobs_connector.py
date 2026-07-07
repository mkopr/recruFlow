from typing import Any

import httpx
import pytest
from app.connectors import solid_jobs
from app.connectors.solid_jobs import (
    _extract_offers,
    _fetch_solid_jobs_json,
    build_offer_params,
    build_offer_url,
    map_solid_jobs_offer,
)
from app.ingestion.normalize import SOLID_JOBS


class _FakeResponse:
    def __init__(self, *, json_data: Any = None) -> None:
        self._json_data = json_data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._json_data


def test_build_offer_url_uses_division_from_config() -> None:
    result = build_offer_url({"division": "Engineering"})

    assert result == "https://solid.jobs/public-api/offers/Engineering"


def test_build_offer_url_defaults_division_to_it_when_absent() -> None:
    result = build_offer_url({})

    assert result == "https://solid.jobs/public-api/offers/IT"


def test_build_offer_params_always_sets_campaign_page_index_page_size_and_sort() -> None:
    result = build_offer_params({}, campaign="recruflow", page_index=0, page_size=100)

    assert result["campaign"] == "recruflow"
    assert result["pageIndex"] == 0
    assert result["pageSize"] == 100
    assert result["sortActive"] == "validFrom"
    assert result["sortDirection"] == "desc"


def test_build_offer_params_applies_cities_experience_terms_min_salary_from_config() -> None:
    result = build_offer_params(
        {
            "cities": ["Warsaw", "Krakow"],
            "experience_levels": ["Senior", "Regular"],
            "terms": ["python"],
            "min_salary": 18000,
        },
        campaign="recruflow",
        page_index=0,
        page_size=100,
    )

    assert result["search.cities"] == "Warsaw,Krakow"
    assert result["search.experiences"] == "Senior,Regular"
    assert result["search.searchTerm"] == "python"
    assert result["search.minimumSalary"] == 18000


def test_build_offer_params_omits_absent_filters() -> None:
    result = build_offer_params({}, campaign="recruflow", page_index=0, page_size=100)

    assert "search.cities" not in result
    assert "search.experiences" not in result
    assert "search.searchTerm" not in result
    assert "search.minimumSalary" not in result


def test_fetch_solid_jobs_json_pins_api_version_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse(json_data={"jobs": []})

    monkeypatch.setattr(httpx, "get", _fake_get)

    _fetch_solid_jobs_json("https://solid.jobs/public-api/offers/IT", params={})

    assert captured["headers"]["X-Api-Version"] == "1.0"


def test_fetch_solid_jobs_json_returns_parsed_payload_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"jobs": [{"title": "a"}], "pageIndex": 0, "pageSize": 1, "totalCount": 1}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=payload))

    result = _fetch_solid_jobs_json("https://solid.jobs/public-api/offers/IT", params={})

    assert result == payload


def test_extract_offers_delegates_to_shared_envelope_extractor_with_jobs_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # shared envelope-shape behaviour (bare list, dict-with-key, None, wrong type,
    # non-dict items) is covered once in tests/test_ingestion_normalize.py
    calls: dict[str, Any] = {}

    def _fake_extract_envelope_list(payload: Any, key: str, **kwargs: Any) -> Any:
        calls["args"] = (payload, key, kwargs)
        return [{"title": "a"}]

    monkeypatch.setattr(solid_jobs, "extract_envelope_list", _fake_extract_envelope_list)

    result = _extract_offers({"jobs": [{"title": "a"}]})

    assert result == [{"title": "a"}]
    assert calls["args"][1] == "jobs"
    assert calls["args"][2] == {}


def test_map_solid_jobs_offer_maps_all_known_fields() -> None:
    raw = {
        "jobOfferKey": "abc123",
        "url": "https://solid.jobs/o/x",
        "title": "Backend Engineer",
        "company": "Acme",
        "locations": ["Warsaw", "Krakow"],
        "isRemote": True,
        "isHybrid": False,
        "experienceLevel": "Senior",
        "salary": {"from": 18000, "to": 24000, "currency": "PLN", "employmentType": "b2b"},
        "contractTime": "full_time",
        "validFrom": "2026-06-01T00:00:00Z",
        "description": "great role",
    }

    result = map_solid_jobs_offer(1, raw)

    assert result == {
        "source_id": 1,
        "external_id": "abc123",
        "canonical_url": "https://solid.jobs/o/x",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Warsaw, Krakow",
        "remote": True,
        "seniority": "senior",
        "salary_min": 18000,
        "salary_max": 24000,
        "salary_currency": "PLN",
        "contract_type": "b2b",
        "posted_at": "2026-06-01T00:00:00Z",
        "description": "great role",
    }


def test_map_solid_jobs_offer_does_not_treat_hybrid_as_remote() -> None:
    raw = {"title": "Backend Engineer", "company": "Acme", "isRemote": False, "isHybrid": True}

    result = map_solid_jobs_offer(1, raw)

    assert result["remote"] is False


def test_map_solid_jobs_offer_handles_missing_optional_fields() -> None:
    raw = {"title": "Backend Engineer", "company": "Acme"}

    result = map_solid_jobs_offer(1, raw)

    assert result["external_id"] is None
    assert result["canonical_url"] is None
    assert result["location"] is None
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["contract_type"] is None
    assert result["posted_at"] is None
    assert result["description"] is None
    assert result["salary_currency"] == "PLN"
    assert result["remote"] is False


def test_map_solid_jobs_offer_calls_shared_normalize_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[Any, ...]] = {}

    def _record(name: str) -> Any:
        def _stub(*args: Any, **kwargs: Any) -> Any:
            calls[name] = args
            if name == "normalize_salary":
                return (None, None, "PLN")
            if name == "normalize_seniority":
                return None
            return False

        return _stub

    monkeypatch.setattr(solid_jobs, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(solid_jobs, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(solid_jobs, "normalize_salary", _record("normalize_salary"))

    raw = {
        "title": "Backend Engineer",
        "company": "Acme",
        "isRemote": True,
        "experienceLevel": "Senior",
        "salary": {"from": 18000, "to": 24000, "currency": "PLN"},
    }
    map_solid_jobs_offer(1, raw)

    assert calls["normalize_remote"][0] == SOLID_JOBS
    assert calls["normalize_seniority"][0] == SOLID_JOBS
    assert calls["normalize_salary"][0] == SOLID_JOBS
