from datetime import UTC, datetime
from typing import Any

import pytest
from app.connectors import nofluffjobs
from app.connectors.nofluffjobs import _extract_offer_list, map_nofluffjobs_offer
from app.ingestion.normalize import NOFLUFFJOBS


def test_extract_offer_list_delegates_to_shared_envelope_extractor_with_postings_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # shared envelope-shape behaviour (dict-with-key, None, wrong type, non-dict items)
    # is covered once in tests/test_ingestion_normalize.py
    calls: dict[str, Any] = {}

    def _fake_extract_envelope_list(payload: Any, key: str, **kwargs: Any) -> Any:
        calls["args"] = (payload, key, kwargs)
        return [{"title": "a"}]

    monkeypatch.setattr(nofluffjobs, "extract_envelope_list", _fake_extract_envelope_list)

    result = _extract_offer_list({"postings": [{"title": "a"}]})

    assert result == [{"title": "a"}]
    assert calls["args"][1] == "postings"
    assert calls["args"][2] == {"allow_bare_list": False}


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
