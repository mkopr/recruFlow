from typing import Any

import pytest
from app.connectors.justjoinit import JustJoinItConnector
from app.ingestion.normalize import JUSTJOINIT


def test_default_url_is_the_justjoinit_offers_endpoint() -> None:
    connector = JustJoinItConnector()

    assert connector.build_url({}) == "https://justjoin.it/api/candidate-api/offers"


def test_build_url_honors_endpoint_url_override_from_config() -> None:
    connector = JustJoinItConnector()

    assert connector.build_url({"endpoint_url": "https://example.test/offers"}) == (
        "https://example.test/offers"
    )


def test_build_params_uses_cursor_as_from_offset() -> None:
    connector = JustJoinItConnector()

    assert connector.build_params({}, cursor=20, page_size=10) == {"from": 20, "itemsCount": 10}


def test_next_cursor_reads_meta_next_cursor_defensively() -> None:
    connector = JustJoinItConnector()

    assert connector.next_cursor({"meta": {"next": {"cursor": 5}}}, [], cursor=0, page_size=10) == 5
    assert connector.next_cursor({}, [], cursor=0, page_size=10) is None
    assert connector.next_cursor({"meta": "not-a-dict"}, [], cursor=0, page_size=10) is None
    assert (
        connector.next_cursor({"meta": {"next": "not-a-dict"}}, [], cursor=0, page_size=10) is None
    )
    assert (
        connector.next_cursor(
            {"meta": {"next": {"cursor": "not-an-int"}}}, [], cursor=0, page_size=10
        )
        is None
    )


def test_justjoinit_runner_kwargs_forwards_rate_limit_delay() -> None:
    connector = JustJoinItConnector()

    assert connector.runner_kwargs({"rate_limit_delay_seconds": 2.5}) == {"rate_limit_delay": 2.5}
    assert connector.runner_kwargs({}) == {"rate_limit_delay": 1.0}


def test_extract_offers_uses_data_envelope_key() -> None:
    # shared envelope-shape behaviour (bare list, dict-with-key, None, wrong type,
    # non-dict items) is covered once in tests/test_ingestion_normalize.py
    connector = JustJoinItConnector()

    assert connector.envelope_key == "data"
    assert connector.extract_offers({"data": [{"title": "a"}]}) == [{"title": "a"}]


def test_map_justjoinit_offer_maps_all_known_fields(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    # see tests/test_ingestion_validate.py: alembic's fileConfig (triggered by
    # integration tests in the same session) can disable this logger.
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
        result = JustJoinItConnector().map_offer(1, raw)

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

    result = JustJoinItConnector().map_offer(1, raw)

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

    connector = JustJoinItConnector()
    assert connector.map_offer(1, remote_raw)["remote"] is True
    assert connector.map_offer(1, hybrid_raw)["remote"] is False
    assert connector.map_offer(1, office_raw)["remote"] is False


def test_map_justjoinit_offer_joins_multiple_locations() -> None:
    raw = {
        "title": "x",
        "companyName": "y",
        "locations": [{"city": "Warszawa"}, {"city": "Kraków"}],
    }

    result = JustJoinItConnector().map_offer(1, raw)

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

    result = JustJoinItConnector().map_offer(1, raw)

    assert result["salary_min"] == 100
    assert result["salary_max"] == 200
    assert result["contract_type"] == "b2b"


def test_map_justjoinit_offer_calls_shared_normalize_functions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.connectors import justjoinit

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
    JustJoinItConnector().map_offer(1, raw)

    assert calls["normalize_remote"][0] == JUSTJOINIT
    assert calls["normalize_seniority"][0] == JUSTJOINIT
    assert calls["normalize_salary"][0] == JUSTJOINIT
