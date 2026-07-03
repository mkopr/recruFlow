import json
import logging
import subprocess
from typing import Any

import pytest
from app.connectors import solid_jobs
from app.connectors.solid_jobs import (
    _extract_offers,
    _run_sjctl,
    build_search_args,
    build_sync_args,
    map_sjctl_offer,
)
from app.ingestion.normalize import SOLID_JOBS


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _enable_logger() -> None:
    # see tests/test_ingestion_validate.py: alembic's fileConfig (triggered by
    # integration tests in the same session) can disable this logger.
    logging.getLogger("app.connectors.solid_jobs").disabled = False


def test_build_search_args_applies_division_city_salary_experience_terms_from_config() -> None:
    result = build_search_args(
        {
            "division": "IT",
            "cities": ["Warsaw", "Krakow"],
            "min_salary": 18000,
            "experience_levels": ["Senior", "Regular"],
            "terms": ["python"],
        },
        campaign="recruflow",
    )

    assert result == [
        "search",
        "-d",
        "IT",
        "--city",
        "Warsaw",
        "--city",
        "Krakow",
        "--min-salary",
        "18000",
        "--experience",
        "Senior",
        "--experience",
        "Regular",
        "--term",
        "python",
        "--campaign",
        "recruflow",
        "--json",
    ]


def test_build_search_args_defaults_division_to_it_when_absent() -> None:
    result = build_search_args({}, campaign="recruflow")

    idx = result.index("-d")
    assert result[idx + 1] == "IT"
    assert "--city" not in result
    assert "--min-salary" not in result
    assert "--experience" not in result
    assert "--term" not in result


def test_build_search_args_always_sets_campaign() -> None:
    result = build_search_args({}, campaign="recruflow")

    idx = result.index("--campaign")
    assert result[idx + 1] == "recruflow"
    assert result[-1] == "--json"


def test_build_sync_args_sets_campaign_and_no_filters() -> None:
    result = build_sync_args(campaign="recruflow")

    assert result == ["sync", "--campaign", "recruflow", "--json"]


def test_run_sjctl_returns_none_and_logs_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("sjctl not found")

    monkeypatch.setattr(subprocess, "run", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _run_sjctl(["search", "--json"])

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_run_sjctl_returns_none_and_logs_when_exit_code_nonzero(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(returncode=1, stderr="boom"),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _run_sjctl(["sync", "--json"])

    assert result is None
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_run_sjctl_returns_none_and_logs_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(returncode=0, stdout="not json{{{"),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.solid_jobs"):
        result = _run_sjctl(["sync", "--json"])

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_run_sjctl_returns_parsed_json_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: _FakeCompletedProcess(
            returncode=0, stdout=json.dumps({"watchesRun": 1, "totalSeen": 0, "new": None})
        ),
    )

    result = _run_sjctl(["sync", "--json"])

    assert result == {"watchesRun": 1, "totalSeen": 0, "new": None}


def test_extract_offers_reads_named_key_from_dict_payload() -> None:
    result = _extract_offers({"jobs": [{"title": "a"}, {"title": "b"}]}, "jobs")

    assert result == [{"title": "a"}, {"title": "b"}]


def test_extract_offers_reads_bare_list_payload() -> None:
    result = _extract_offers([{"title": "a"}], "jobs")

    assert result == [{"title": "a"}]


def test_extract_offers_returns_none_for_unexpected_shape() -> None:
    result = _extract_offers({"unexpected": "shape"}, "new")

    assert result is None


def test_extract_offers_treats_null_value_as_empty_list() -> None:
    # real sjctl sync --json emits {"new": null} when there are no new offers --
    # this is a valid "zero results" response, not a malformed one.
    result = _extract_offers({"watchesRun": 1, "totalSeen": 0, "new": None}, "new")

    assert result == []


def test_extract_offers_unwraps_item_key_for_sync_envelopes() -> None:
    # real sjctl sync --json wraps each new offer as {"watch": ..., "offer": {...}},
    # not a bare offer object.
    payload = {
        "new": [
            {"watch": "my-watch", "offer": {"jobOfferKey": "k1"}},
            {"watch": "my-watch", "offer": {"jobOfferKey": "k2"}},
        ]
    }

    result = _extract_offers(payload, "new", item_key="offer")

    assert result == [{"jobOfferKey": "k1"}, {"jobOfferKey": "k2"}]


def test_extract_offers_skips_envelopes_missing_item_key() -> None:
    payload = {"new": [{"watch": "my-watch"}, {"watch": "my-watch", "offer": {"jobOfferKey": "k"}}]}

    result = _extract_offers(payload, "new", item_key="offer")

    assert result == [{"jobOfferKey": "k"}]


def test_map_sjctl_offer_maps_all_known_fields() -> None:
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

    result = map_sjctl_offer(1, raw)

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


def test_map_sjctl_offer_does_not_treat_hybrid_as_remote() -> None:
    raw = {"title": "Backend Engineer", "company": "Acme", "isRemote": False, "isHybrid": True}

    result = map_sjctl_offer(1, raw)

    assert result["remote"] is False


def test_map_sjctl_offer_handles_missing_optional_fields() -> None:
    raw = {"title": "Backend Engineer", "company": "Acme"}

    result = map_sjctl_offer(1, raw)

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


def test_map_sjctl_offer_calls_shared_normalize_functions(monkeypatch: pytest.MonkeyPatch) -> None:
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
    map_sjctl_offer(1, raw)

    assert calls["normalize_remote"][0] == SOLID_JOBS
    assert calls["normalize_seniority"][0] == SOLID_JOBS
    assert calls["normalize_salary"][0] == SOLID_JOBS
