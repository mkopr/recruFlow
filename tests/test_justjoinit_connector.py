import json
import logging
from typing import Any

import httpx
import pytest
from app.connectors import justjoinit
from app.connectors.justjoinit import (
    _extract_offer_list,
    _fetch_justjoinit_json,
    map_justjoinit_offer,
)
from app.ingestion.normalize import JUSTJOINIT


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
    logging.getLogger("app.connectors.justjoinit").disabled = False


def test_fetch_justjoinit_json_returns_none_and_logs_on_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.justjoinit"):
        result = _fetch_justjoinit_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_justjoinit_json_returns_none_and_logs_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    request = httpx.Request("GET", "https://justjoin.it/api/candidate-api/offers")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    with caplog.at_level(logging.ERROR, logger="app.connectors.justjoinit"):
        result = _fetch_justjoinit_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_justjoinit_json_returns_none_and_logs_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    json_error = json.JSONDecodeError("Expecting value", "not json{{{", 0)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(text="not json{{{", json_error=json_error),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.justjoinit"):
        result = _fetch_justjoinit_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_justjoinit_json_returns_parsed_payload_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"title": "a"}], "meta": {"next": {"cursor": None, "itemsCount": 100}}}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=payload))

    result = _fetch_justjoinit_json()

    assert result == payload


def test_extract_offer_list_reads_named_key_from_dict_payload() -> None:
    result = _extract_offer_list({"data": [{"title": "a"}, {"title": "b"}]})

    assert result == [{"title": "a"}, {"title": "b"}]


def test_extract_offer_list_reads_bare_list_payload() -> None:
    result = _extract_offer_list([{"title": "a"}])

    assert result == [{"title": "a"}]


def test_extract_offer_list_returns_none_for_unexpected_shape() -> None:
    result = _extract_offer_list({"unexpected": "shape"})

    assert result is None


def test_map_justjoinit_offer_maps_all_known_fields(caplog: pytest.LogCaptureFixture) -> None:
    _enable_logger()
    logging.getLogger("app.ingestion.normalize").disabled = False
    raw = {
        "guid": "d751ca8f-672c-4991-b382-77419b435764",
        "slug": "danone-sap-fi-product-owner-i2p-invoice-management--warszawa-pm",
        "title": "SAP FI Product Owner",
        "workplaceType": "hybrid",
        "workingTime": "full_time",
        "experienceLevel": "manager",
        "city": "Warszawa",
        "street": "Bobrowiecka 8",
        "companyName": "DANONE",
        "locations": [{"city": "Warszawa", "street": "Bobrowiecka 8"}],
        "employmentTypes": [
            {
                "from": 20000.0,
                "to": 25000.0,
                "currency": "PLN",
                "currencySource": "original",
                "type": "b2b",
                "unit": "Month",
                "gross": False,
            },
            {
                "from": 4500.0,
                "to": 5625.0,
                "currency": "EUR",
                "currencySource": "conversion",
                "type": "b2b",
                "unit": "Month",
                "gross": False,
            },
        ],
        "publishedAt": "2026-07-03T09:00:11.757Z",
    }

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = map_justjoinit_offer(1, raw)

    assert result == {
        "source_id": 1,
        "external_id": "d751ca8f-672c-4991-b382-77419b435764",
        "canonical_url": (
            "https://justjoin.it/job-offer/"
            "danone-sap-fi-product-owner-i2p-invoice-management--warszawa-pm"
        ),
        "title": "SAP FI Product Owner",
        "company": "DANONE",
        "location": "Warszawa",
        "remote": False,
        "seniority": "lead",
        "salary_min": 20000,
        "salary_max": 25000,
        "salary_currency": "PLN",
        "contract_type": "b2b",
        "posted_at": "2026-07-03T09:00:11.757Z",
        "description": None,
    }
    assert any(
        "net" in r.getMessage() or "gross" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
    )


def test_map_justjoinit_offer_handles_missing_optional_fields() -> None:
    raw = {"title": "Backend Engineer", "companyName": "Acme"}

    result = map_justjoinit_offer(1, raw)

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


def test_map_justjoinit_offer_maps_remote_via_shared_normalizer() -> None:
    # JustJoin.it's own workplaceType enum is {"remote", "hybrid", "office"} -- mapped to a
    # boolean via the shared app.ingestion.normalize.normalize_remote function.
    remote_raw = {"title": "x", "companyName": "y", "workplaceType": "remote"}
    hybrid_raw = {"title": "x", "companyName": "y", "workplaceType": "hybrid"}
    office_raw = {"title": "x", "companyName": "y", "workplaceType": "office"}

    assert map_justjoinit_offer(1, remote_raw)["remote"] is True
    assert map_justjoinit_offer(1, hybrid_raw)["remote"] is False
    assert map_justjoinit_offer(1, office_raw)["remote"] is False


def test_map_justjoinit_offer_joins_multiple_locations() -> None:
    raw = {
        "title": "x",
        "companyName": "y",
        "locations": [{"city": "Warszawa"}, {"city": "Kraków"}],
    }

    result = map_justjoinit_offer(1, raw)

    assert result["location"] == "Warszawa, Kraków"


def test_map_justjoinit_offer_uses_first_employment_type_as_primary() -> None:
    # real JustJoin.it offers can list several contract-type entries (b2b, permanent, ...);
    # only the first/primary entry is mapped -- a documented known limitation (see
    # ARCHITECTURE.md's JustJoin.it connector section).
    raw = {
        "title": "x",
        "companyName": "y",
        "employmentTypes": [
            {"from": 100, "to": 200, "currency": "PLN", "type": "b2b"},
            {"from": 50, "to": 90, "currency": "PLN", "type": "permanent"},
        ],
    }

    result = map_justjoinit_offer(1, raw)

    assert result["salary_min"] == 100
    assert result["salary_max"] == 200
    assert result["contract_type"] == "b2b"


def test_map_justjoinit_offer_calls_shared_normalize_functions(
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

    monkeypatch.setattr(justjoinit, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(justjoinit, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(justjoinit, "normalize_salary", _record("normalize_salary"))

    raw = {
        "title": "Backend Engineer",
        "companyName": "Acme",
        "workplaceType": "remote",
        "experienceLevel": "senior",
        "employmentTypes": [{"from": 18000, "to": 24000, "currency": "PLN"}],
    }
    map_justjoinit_offer(1, raw)

    assert calls["normalize_remote"][0] == JUSTJOINIT
    assert calls["normalize_seniority"][0] == JUSTJOINIT
    assert calls["normalize_salary"][0] == JUSTJOINIT
