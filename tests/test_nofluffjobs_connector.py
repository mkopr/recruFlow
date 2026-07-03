import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.connectors import nofluffjobs
from app.connectors.nofluffjobs import (
    _extract_offer_list,
    _fetch_nofluffjobs_json,
    map_nofluffjobs_offer,
)
from app.ingestion.normalize import NOFLUFFJOBS


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
    logging.getLogger("app.connectors.nofluffjobs").disabled = False


def test_fetch_nofluffjobs_json_returns_none_and_logs_on_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.nofluffjobs"):
        result = _fetch_nofluffjobs_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_nofluffjobs_json_returns_none_and_logs_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    request = httpx.Request("GET", "https://nofluffjobs.com/api/joboffers/main")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    with caplog.at_level(logging.ERROR, logger="app.connectors.nofluffjobs"):
        result = _fetch_nofluffjobs_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_nofluffjobs_json_returns_none_and_logs_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    json_error = json.JSONDecodeError("Expecting value", "not json{{{", 0)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(text="not json{{{", json_error=json_error),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.nofluffjobs"):
        result = _fetch_nofluffjobs_json()

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_nofluffjobs_json_returns_parsed_payload_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"postings": [{"title": "a"}], "totalCount": 1, "totalPages": 1}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=payload))

    result = _fetch_nofluffjobs_json()

    assert result == payload


def test_extract_offer_list_reads_postings_key_from_dict_payload() -> None:
    result = _extract_offer_list({"postings": [{"title": "a"}, {"title": "b"}]})

    assert result == [{"title": "a"}, {"title": "b"}]


def test_extract_offer_list_treats_null_postings_as_empty_list() -> None:
    result = _extract_offer_list({"postings": None})

    assert result == []


def test_extract_offer_list_returns_none_for_unexpected_shape() -> None:
    result = _extract_offer_list({"unexpected": "shape"})

    assert result is None


def test_extract_offer_list_returns_none_for_bare_list_payload() -> None:
    # unlike JustJoin.it's endpoint, NoFluffJobs's confirmed response is always an
    # envelope dict with a "postings" key -- a bare list is not a shape it produces.
    result = _extract_offer_list([{"title": "a"}])

    assert result is None


def test_map_nofluffjobs_offer_maps_all_known_fields() -> None:
    raw = {
        "id": "senior-it-security-iam-consultant-reply-polska-Katowice",
        "name": "Reply Polska",
        "location": {
            "places": [
                {
                    "country": {"code": "POL", "name": "Poland"},
                    "city": "Katowice",
                    "street": "Wrocławska 54",
                    "postalCode": "40-217",
                    "url": "senior-it-security-iam-consultant-reply-polska-katowice",
                }
            ],
            "fullyRemote": False,
            "covidTimeRemotely": False,
            "hybridDesc": "Our standard is a hybrid working model with office presence in "
            "Katowice at least once per week.",
        },
        "posted": 1781505509147,
        "renewed": 1783060709147,
        "title": "Senior IT Security & IAM Consultant",
        "technology": "IAM",
        "category": "security",
        "seniority": ["Senior"],
        "url": "senior-it-security-iam-consultant-reply-polska-katowice",
        "regions": ["pl"],
        "fullyRemote": False,
        "salary": {
            "from": 13000.0,
            "to": 22000.0,
            "type": "permanent",
            "currency": "PLN",
            "disclosedAt": "VISIBLE",
            "flexibleUpperBound": False,
        },
        "reference": "HSINDAJA",
        "topInSearch": False,
        "highlighted": False,
    }

    result = map_nofluffjobs_offer(1, raw)

    assert result == {
        "source_id": 1,
        "external_id": "senior-it-security-iam-consultant-reply-polska-Katowice",
        "canonical_url": (
            "https://nofluffjobs.com/job/senior-it-security-iam-consultant-reply-polska-katowice"
        ),
        "title": "Senior IT Security & IAM Consultant",
        "company": "Reply Polska",
        "location": "Katowice",
        "remote": False,
        "seniority": "senior",
        "salary_min": 13000,
        "salary_max": 22000,
        "salary_currency": "PLN",
        "contract_type": "permanent",
        "posted_at": datetime(2026, 6, 15, 6, 38, 29, 147000, tzinfo=UTC),
        "description": None,
    }


def test_map_nofluffjobs_offer_handles_missing_optional_fields() -> None:
    raw = {"title": "Backend Engineer", "name": "Acme"}

    result = map_nofluffjobs_offer(1, raw)

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


def test_map_nofluffjobs_offer_maps_remote_via_shared_normalizer() -> None:
    # NoFluffJobs's own location.fullyRemote is already a literal boolean matching the
    # `Remote` glossary definition exactly -- routed through the shared
    # app.ingestion.normalize.normalize_remote function unchanged.
    remote_raw = {"title": "x", "name": "y", "location": {"fullyRemote": True}}
    hybrid_raw = {"title": "x", "name": "y", "location": {"fullyRemote": False}}

    assert map_nofluffjobs_offer(1, remote_raw)["remote"] is True
    assert map_nofluffjobs_offer(1, hybrid_raw)["remote"] is False


def test_map_nofluffjobs_offer_joins_multiple_locations() -> None:
    raw = {
        "title": "x",
        "name": "y",
        "location": {
            "places": [{"city": "Remote"}, {"city": "Poznań"}],
            "fullyRemote": True,
        },
    }

    result = map_nofluffjobs_offer(1, raw)

    assert result["location"] == "Remote, Poznań"


def test_map_nofluffjobs_offer_joins_multiple_seniority_levels() -> None:
    # real listing items were observed with exactly one seniority entry, but the field
    # is a list on the wire -- handled defensively the same way multi-location joins are.
    raw = {"title": "x", "name": "y", "seniority": ["Mid", "Senior"]}

    result = map_nofluffjobs_offer(1, raw)

    assert result["seniority"] == "mid, senior"


def test_map_nofluffjobs_offer_uses_location_duplicate_slug_as_external_id_not_reference() -> None:
    # NoFluffJobs emits one posting entry per office location for the same underlying ad,
    # all sharing one "reference" code but each with its own unique "id"/"url" slug -- using
    # "reference" as external_id would collide across those duplicates, so "id" is used.
    raw = {
        "id": "senior-delivery-manager-spyrosoft-Wrocław",
        "url": "senior-delivery-manager-spyrosoft-wroclaw",
        "reference": "P4Y5SG0Q",
        "title": "Senior Delivery Manager",
        "name": "Spyrosoft",
    }

    result = map_nofluffjobs_offer(1, raw)

    assert result["external_id"] == "senior-delivery-manager-spyrosoft-Wrocław"
    assert result["canonical_url"] == (
        "https://nofluffjobs.com/job/senior-delivery-manager-spyrosoft-wroclaw"
    )


def test_map_nofluffjobs_offer_calls_shared_normalize_functions(
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

    monkeypatch.setattr(nofluffjobs, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(nofluffjobs, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(nofluffjobs, "normalize_salary", _record("normalize_salary"))

    raw = {
        "title": "Backend Engineer",
        "name": "Acme",
        "location": {"fullyRemote": True},
        "seniority": ["Senior"],
        "salary": {"from": 18000, "to": 24000, "currency": "PLN"},
    }
    map_nofluffjobs_offer(1, raw)

    assert calls["normalize_remote"][0] == NOFLUFFJOBS
    assert calls["normalize_seniority"][0] == NOFLUFFJOBS
    assert calls["normalize_salary"][0] == NOFLUFFJOBS
