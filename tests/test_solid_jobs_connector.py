import json
import logging
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
    def __init__(
        self,
        *,
        json_data: Any = None,
        text: str = "",
        status_error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self._json_data = json_data
        self.text = text
        self._status_error = status_error
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


def _enable_logger() -> None:
    # see tests/test_ingestion_validate.py: alembic's fileConfig (triggered by
    # integration tests in the same session) can disable this logger.
    logging.getLogger("app.connectors.solid_jobs").disabled = False


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


def test_fetch_solid_jobs_json_returns_none_and_logs_on_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _fetch_solid_jobs_json("https://solid.jobs/public-api/offers/IT", params={})

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_solid_jobs_json_returns_none_and_logs_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    request = httpx.Request("GET", "https://solid.jobs/public-api/offers/IT")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _fetch_solid_jobs_json("https://solid.jobs/public-api/offers/IT", params={})

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_solid_jobs_json_returns_none_and_logs_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    json_error = json.JSONDecodeError("Expecting value", "not json{{{", 0)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(text="not json{{{", json_error=json_error),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _fetch_solid_jobs_json("https://solid.jobs/public-api/offers/IT", params={})

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


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


def test_extract_offers_reads_bare_list_payload() -> None:
    result = _extract_offers([{"title": "a"}])

    assert result == [{"title": "a"}]


def test_extract_offers_reads_results_key_from_dict_payload() -> None:
    result = _extract_offers({"jobs": [{"title": "a"}], "totalCount": 1})

    assert result == [{"title": "a"}]


def test_extract_offers_returns_none_for_unexpected_shape() -> None:
    result = _extract_offers({"unexpected": "shape"})

    assert result is None


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
