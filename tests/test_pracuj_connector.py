import ast
import asyncio
import inspect
import json
from typing import Any

import pytest
from app.connectors import pracuj
from app.connectors.pracuj import (
    DEFAULT_RATE_LIMIT_DELAY_SECONDS,
    PRACUJ_HOMEPAGE_URL,
    PracujConnector,
    _collect_offers,
    _dehydrated_query_data,
    extract_next_data,
)
from app.ingestion.normalize import PRACUJ

# A real Pracuj.pl offer detail record's shape (`attributes.employment.typesOfContracts[]`
# etc.), sampled live 2026-07-14 from a Java Developer posting -- its only contract type is an
# hourly B2B rate (`timeUnit.id == 1`), which `_pick_monthly_salary` must exclude from
# salary_min/max (see `_MONTHLY_TIME_UNIT_ID`'s comment in pracuj.py) while still reporting the
# contract type name itself.
_HOURLY_ONLY_DETAIL_RECORD: dict[str, Any] = {
    "jobOfferWebId": 1004966514,
    "publicationDetails": {"dateOfInitialPublicationUtc": "2026-07-14T13:49:55.61Z"},
    "attributes": {
        "jobTitle": "Java Developer",
        "description": "Twoj zakres obowiazkow, rozwoj nowych funkcjonalnosci...",
        "offerAbsoluteUrl": (
            "https://www.pracuj.pl/praca/java-developer-warszawa-chmielna-71,oferta,1004966514"
        ),
        "displayEmployerName": "Connectis_",
        "workplaces": [{"displayAddress": "Chmielna 71, Wola, Warszawa"}],
        "employment": {
            "positionLevels": [
                {
                    "id": 4,
                    "name": "specjalista / specjalistka (mid / regular)",
                    "pracujPlName": "specjalista / specjalistka (mid / regular)",
                }
            ],
            "entirelyRemoteWork": False,
            "typesOfContracts": [
                {
                    "id": 3,
                    "name": "kontrakt B2B",
                    "pracujPlName": "kontrakt B2B",
                    "salary": {
                        "from": 140,
                        "to": 155,
                        "currency": {"code": "PLN", "symbol": "zl"},
                        "timeUnit": {"id": 1, "shortForm": {"name": "godz."}},
                        "salaryKind": {"code": "net-plus-vat", "name": "netto (+ VAT)"},
                    },
                }
            ],
            "workModes": [{"code": "hybrid", "name": "praca hybrydowa"}],
        },
    },
}

# Same shape, sampled live from a "Specjalista ds. Wsparcia IT" posting whose only contract
# type is a monthly UoP salary (`timeUnit.id == 0`) -- the case where salary_min/max should
# actually be populated.
_MONTHLY_UOP_DETAIL_RECORD: dict[str, Any] = {
    "jobOfferWebId": 1004945011,
    "publicationDetails": {"dateOfInitialPublicationUtc": "2026-07-10T09:00:00Z"},
    "attributes": {
        "jobTitle": "Specjalista / Specjalistka ds. Wsparcia IT",
        "description": "Pelen opis oferty...",
        "offerAbsoluteUrl": (
            "https://www.pracuj.pl/praca/specjalista-ds-wsparcia-it-lodz,oferta,1004945011"
        ),
        "displayEmployerName": "Acme Sp. z o.o.",
        "workplaces": [{"displayAddress": "Gdanska 54, Lodz"}],
        "employment": {
            "positionLevels": [
                {
                    "id": 17,
                    "name": "mlodszy specjalista / mlodsza specjalistka (junior)",
                    "pracujPlName": "młodszy specjalista / młodsza specjalistka (junior)",
                },
                {
                    "id": 4,
                    "name": "specjalista / specjalistka (mid / regular)",
                    "pracujPlName": "specjalista / specjalistka (mid / regular)",
                },
            ],
            "entirelyRemoteWork": True,
            "typesOfContracts": [
                {
                    "id": 0,
                    "name": "umowa o pracę",
                    "pracujPlName": "umowa o pracę",
                    "salary": {
                        "from": 6000,
                        "to": 8500,
                        "currency": {"code": "PLN", "symbol": "zl"},
                        "timeUnit": {"id": 0, "shortForm": {"name": "mies."}},
                        "salaryKind": {"code": "gross", "name": "brutto"},
                    },
                }
            ],
            "workModes": [{"code": "home-office", "name": "praca zdalna"}],
        },
    },
}


def _next_data_html(query_key: list[Any], data: Any) -> str:
    next_data = {
        "props": {
            "pageProps": {
                "dehydratedState": {"queries": [{"queryKey": query_key, "state": {"data": data}}]}
            }
        }
    }
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(next_data)}</script></body></html>"
    )


def _listing_html(grouped_offers: list[dict[str, Any]]) -> str:
    return _next_data_html(
        ["jobOffers", {"pn": 1, "rop": 10}, "Default", True, "pl"],
        {"groupedOffers": grouped_offers, "offersTotalCount": len(grouped_offers)},
    )


def _detail_html(record: dict[str, Any]) -> str:
    return _next_data_html(["jobOffer", str(record["jobOfferWebId"]), "pl"], record)


def _group(*, offer_url: str) -> dict[str, Any]:
    return {"groupId": "g1", "jobTitle": "placeholder", "offers": [{"offerAbsoluteUri": offer_url}]}


def test_default_url_is_the_pracuj_homepage() -> None:
    assert PracujConnector().default_url() == PRACUJ_HOMEPAGE_URL


def test_next_cursor_always_none() -> None:
    assert PracujConnector().next_cursor({}, [{"title": "a"}], cursor=0, page_size=10) is None


def test_build_params_returns_empty_dict() -> None:
    assert PracujConnector().build_params({}, cursor=0, page_size=10) == {}


def test_extract_next_data_returns_parsed_dict_for_wellformed_fixture() -> None:
    html = _detail_html(_HOURLY_ONLY_DETAIL_RECORD)

    result = extract_next_data(html)

    assert result is not None
    assert _dehydrated_query_data(result, "jobOffer") == _HOURLY_ONLY_DETAIL_RECORD


def test_extract_next_data_returns_none_and_logs_when_no_script_tag_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("ERROR", logger="app.connectors.pracuj"):
        result = extract_next_data("<html><body>no next data here</body></html>", url="https://x")

    assert result is None
    assert any("Pracuj.pl returned unexpected page shape" in r.getMessage() for r in caplog.records)


def test_extract_next_data_returns_none_on_malformed_json_inside_script_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    html = '<script id="__NEXT_DATA__">{not valid json</script>'

    with caplog.at_level("ERROR", logger="app.connectors.pracuj"):
        result = extract_next_data(html, url="https://x")

    assert result is None


def test_dehydrated_query_data_returns_none_when_query_key_absent() -> None:
    next_data: dict[str, Any] = {"props": {"pageProps": {"dehydratedState": {"queries": []}}}}

    assert _dehydrated_query_data(next_data, "jobOffers") is None


def test_dehydrated_query_data_disambiguates_joboffer_from_joboffers() -> None:
    html = _listing_html([_group(offer_url="https://www.pracuj.pl/praca/x,oferta,1")])
    next_data = extract_next_data(html)
    assert next_data is not None

    assert _dehydrated_query_data(next_data, "jobOffer") is None
    assert _dehydrated_query_data(next_data, "jobOffers") is not None


def test_map_pracuj_offer_maps_all_known_fields_with_monthly_salary() -> None:
    result = PracujConnector().map_offer(1, _MONTHLY_UOP_DETAIL_RECORD)

    assert result == {
        "source_id": 1,
        "external_id": "1004945011",
        "canonical_url": (
            "https://www.pracuj.pl/praca/specjalista-ds-wsparcia-it-lodz,oferta,1004945011"
        ),
        "title": "Specjalista / Specjalistka ds. Wsparcia IT",
        "company": "Acme Sp. z o.o.",
        "location": "Gdanska 54, Lodz",
        "remote": True,
        "seniority": "junior, mid",
        "salary_min": 6000,
        "salary_max": 8500,
        "salary_currency": "PLN",
        "contract_type": "umowa o pracę",
        "posted_at": "2026-07-10T09:00:00Z",
        "description": "Pelen opis oferty...",
    }


def test_map_pracuj_offer_excludes_hourly_rate_from_salary_min_max() -> None:
    result = PracujConnector().map_offer(1, _HOURLY_ONLY_DETAIL_RECORD)

    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["contract_type"] == "kontrakt B2B"
    assert result["remote"] is False
    assert result["seniority"] == "mid"


def test_map_pracuj_offer_calls_shared_normalize_functions(monkeypatch: pytest.MonkeyPatch) -> None:
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

    monkeypatch.setattr(pracuj, "normalize_remote", _record("normalize_remote"))
    monkeypatch.setattr(pracuj, "normalize_seniority", _record("normalize_seniority"))
    monkeypatch.setattr(pracuj, "normalize_salary", _record("normalize_salary"))

    PracujConnector().map_offer(1, _MONTHLY_UOP_DETAIL_RECORD)

    assert calls["normalize_remote"] == (PRACUJ, True)
    assert calls["normalize_seniority"][0] == PRACUJ
    assert calls["normalize_salary"][0] == PRACUJ


def test_map_pracuj_offer_leaves_missing_fields_none_not_guessed() -> None:
    raw = {"jobOfferWebId": None, "attributes": {"jobTitle": "Untitled"}}

    result = PracujConnector().map_offer(1, raw)

    assert result["external_id"] is None
    assert result["canonical_url"] is None
    assert result["location"] is None
    assert result["seniority"] is None
    assert result["salary_min"] is None
    assert result["salary_max"] is None
    assert result["contract_type"] is None
    assert result["posted_at"] is None
    assert result["description"] is None
    assert result["company"] == ""
    assert result["salary_currency"] == "PLN"
    assert result["remote"] is False


def test_map_pracuj_offer_handles_completely_unexpected_shape() -> None:
    result = PracujConnector().map_offer(1, {})

    assert result["title"] == ""
    assert result["company"] == ""
    assert result["canonical_url"] is None


@pytest.mark.asyncio
async def test_collect_offers_applies_category_filter_to_listing_url() -> None:
    requested_urls: list[str] = []

    async def fake_fetch_html(url: str) -> str | None:
        requested_urls.append(url)
        return _listing_html([])

    offers, enumeration_ok, mid_run_failure, next_start_page = await _collect_offers(
        fake_fetch_html,
        category_filter="python developer",
        start_page=1,
        page_size=10,
        max_pages=1,
        rate_limit_delay_seconds=0,
    )

    assert offers == []
    assert enumeration_ok is True
    assert mid_run_failure is False
    assert next_start_page == 1
    assert requested_urls == ["https://www.pracuj.pl/praca/python%20developer;kw?pn=1&rop=10"]


@pytest.mark.asyncio
async def test_collect_offers_fetches_detail_page_per_enumerated_candidate() -> None:
    listing_url = "https://www.pracuj.pl/praca/it;kw?pn=1&rop=10"
    detail_url = _MONTHLY_UOP_DETAIL_RECORD["attributes"]["offerAbsoluteUrl"]

    async def fake_fetch_html(url: str) -> str | None:
        if url == listing_url:
            return _listing_html([_group(offer_url=detail_url)])
        if url == detail_url:
            return _detail_html(_MONTHLY_UOP_DETAIL_RECORD)
        raise AssertionError(f"unexpected url: {url}")

    offers, enumeration_ok, mid_run_failure, next_start_page = await _collect_offers(
        fake_fetch_html,
        category_filter="it",
        start_page=1,
        page_size=10,
        max_pages=1,
        rate_limit_delay_seconds=0,
    )

    assert enumeration_ok is True
    assert mid_run_failure is False
    assert offers == [_MONTHLY_UOP_DETAIL_RECORD]
    # Only 1 group on a page_size=10 page -- a short page proves the listing is exhausted, so
    # the next run should wrap back to page 1 rather than resume forward.
    assert next_start_page == 1


@pytest.mark.asyncio
async def test_collect_offers_returns_not_ok_when_first_listing_fetch_fails() -> None:
    async def fake_fetch_html(url: str) -> str | None:
        return None

    offers, enumeration_ok, mid_run_failure, next_start_page = await _collect_offers(
        fake_fetch_html,
        category_filter="it",
        start_page=1,
        page_size=10,
        max_pages=1,
        rate_limit_delay_seconds=0,
    )

    assert offers == []
    assert enumeration_ok is False
    assert mid_run_failure is False
    assert next_start_page == 1


@pytest.mark.asyncio
async def test_collect_offers_flags_mid_run_failure_when_a_detail_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep := _fake_sleep())
    listing_url = "https://www.pracuj.pl/praca/it;kw?pn=1&rop=10"
    ok_url = "https://www.pracuj.pl/praca/ok,oferta,1"
    failing_url = "https://www.pracuj.pl/praca/challenge,oferta,2"

    async def fake_fetch_html(url: str) -> str | None:
        if url == listing_url:
            return _listing_html([_group(offer_url=ok_url), _group(offer_url=failing_url)])
        if url == ok_url:
            return _detail_html(_HOURLY_ONLY_DETAIL_RECORD)
        if url == failing_url:
            return None
        raise AssertionError(f"unexpected url: {url}")

    offers, enumeration_ok, mid_run_failure, next_start_page = await _collect_offers(
        fake_fetch_html,
        category_filter="it",
        start_page=1,
        page_size=10,
        max_pages=1,
        rate_limit_delay_seconds=0,
    )

    assert enumeration_ok is True
    assert mid_run_failure is True
    assert offers == [_HOURLY_ONLY_DETAIL_RECORD]
    # A mid-run failure means page 1 itself was never fully processed -- retry it, don't skip.
    assert next_start_page == 1


@pytest.mark.asyncio
async def test_collect_offers_resumes_enumeration_from_start_page() -> None:
    # BUG42 regression: enumeration must resume from a persisted `start_page`, not always
    # restart at page 1 -- mirrors BUG41's Rocket Jobs/Bulldogjob sitemap cursor.
    detail_url = _HOURLY_ONLY_DETAIL_RECORD["attributes"]["offerAbsoluteUrl"]
    requested_urls: list[str] = []

    async def fake_fetch_html(url: str) -> str | None:
        requested_urls.append(url)
        if "pn=3" in url:
            return _listing_html([_group(offer_url=detail_url)])
        if url == detail_url:
            return _detail_html(_HOURLY_ONLY_DETAIL_RECORD)
        raise AssertionError(f"unexpected url: {url}")

    offers, enumeration_ok, mid_run_failure, next_start_page = await _collect_offers(
        fake_fetch_html,
        category_filter="it",
        start_page=3,
        page_size=1,
        max_pages=1,
        rate_limit_delay_seconds=0,
    )

    assert enumeration_ok is True
    assert mid_run_failure is False
    assert offers == [_HOURLY_ONLY_DETAIL_RECORD]
    assert any("pn=3" in u for u in requested_urls)
    assert not any("pn=1&" in u for u in requested_urls)
    # A full (not short) page with max_pages exhausted -- more listings likely remain past this
    # run's window, so the next run should resume forward, not wrap back to page 1.
    assert next_start_page == 4


def _fake_sleep() -> Any:
    calls: list[float] = []

    async def _sleep(delay: float) -> None:
        calls.append(delay)

    _sleep.calls = calls  # type: ignore[attr-defined]
    return _sleep


@pytest.mark.asyncio
async def test_rate_limit_delay_is_honoured_between_detail_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sleep = _fake_sleep()
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    listing_url = "https://www.pracuj.pl/praca/it;kw?pn=1&rop=10"
    detail_url = _HOURLY_ONLY_DETAIL_RECORD["attributes"]["offerAbsoluteUrl"]

    async def fake_fetch_html(url: str) -> str | None:
        if url == listing_url:
            return _listing_html([_group(offer_url=detail_url)])
        if url == detail_url:
            return _detail_html(_HOURLY_ONLY_DETAIL_RECORD)
        raise AssertionError(f"unexpected url: {url}")

    configured_delay = 7.5
    await _collect_offers(
        fake_fetch_html,
        category_filter="it",
        start_page=1,
        page_size=10,
        max_pages=1,
        rate_limit_delay_seconds=configured_delay,
    )

    assert fake_sleep.calls
    assert all(delay == configured_delay for delay in fake_sleep.calls)
    assert configured_delay > 1.0, "expected higher than other connectors' 1.0s default"
    assert DEFAULT_RATE_LIMIT_DELAY_SECONDS > 1.0


@pytest.mark.asyncio
async def test_pracuj_run_returns_not_ok_on_enumeration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    async def _fake_collect_offers(
        fetch_html: Any, **kwargs: Any
    ) -> tuple[list[Any], bool, bool, int]:
        return [], False, False, 1

    monkeypatch.setattr(pracuj, "_collect_offers", _fake_collect_offers)
    monkeypatch.setattr(pracuj, "async_playwright", _fake_async_playwright)

    connector = PracujConnector()
    source = Source(id=1, connector="pracuj", config_json={})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(
        ok=False, fetched=0, created=0, error_message="failed to fetch Pracuj.pl offers"
    )


@pytest.mark.asyncio
async def test_pracuj_run_delegates_to_run_paginated_ingestion_with_collected_offers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    async def _fake_collect_offers(
        fetch_html: Any, **kwargs: Any
    ) -> tuple[list[Any], bool, bool, int]:
        return [_HOURLY_ONLY_DETAIL_RECORD], True, False, 3

    monkeypatch.setattr(pracuj, "_collect_offers", _fake_collect_offers)
    monkeypatch.setattr(pracuj, "async_playwright", _fake_async_playwright)

    captured: dict[str, Any] = {}

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        captured.update(kwargs)
        return IngestionResult(ok=True, fetched=1, created=1)

    monkeypatch.setattr(pracuj, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = PracujConnector()
    source = Source(id=1, connector="pracuj", config_json={"page_size": 3, "max_pages": 2})

    result = await connector.run(None, source)  # type: ignore[arg-type]

    assert result == IngestionResult(ok=True, fetched=1, created=1)
    assert captured["page_size"] == 3
    assert captured["max_pages"] == 2
    assert callable(captured["fetch_page"])
    assert captured["fetch_page"](0, 3) == ([_HOURLY_ONLY_DETAIL_RECORD], None)
    assert source.config_json["listing_page_cursor"] == 3


@pytest.mark.asyncio
async def test_pracuj_run_reads_listing_page_cursor_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    captured_collect_kwargs: dict[str, Any] = {}

    async def _fake_collect_offers(
        fetch_html: Any, **kwargs: Any
    ) -> tuple[list[Any], bool, bool, int]:
        captured_collect_kwargs.update(kwargs)
        return [], True, False, 6

    monkeypatch.setattr(pracuj, "_collect_offers", _fake_collect_offers)
    monkeypatch.setattr(pracuj, "async_playwright", _fake_async_playwright)

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(pracuj, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = PracujConnector()
    source = Source(id=1, connector="pracuj", config_json={"listing_page_cursor": 5})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert captured_collect_kwargs["start_page"] == 5
    assert source.config_json["listing_page_cursor"] == 6


@pytest.mark.asyncio
async def test_pracuj_run_records_failure_on_mid_run_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db.models import Source
    from app.ingestion.types import IngestionResult

    async def _fake_collect_offers(
        fetch_html: Any, **kwargs: Any
    ) -> tuple[list[Any], bool, bool, int]:
        return [], True, True, 1

    monkeypatch.setattr(pracuj, "_collect_offers", _fake_collect_offers)
    monkeypatch.setattr(pracuj, "async_playwright", _fake_async_playwright)

    recorded: dict[str, Any] = {}

    async def _fake_record_failure(session: Any, model_cls: Any, **fields: Any) -> None:
        recorded.update(fields)

    monkeypatch.setattr(pracuj, "record_failure", _fake_record_failure)

    async def _fake_run_paginated_ingestion(
        session: Any, source_id: int, **kwargs: Any
    ) -> IngestionResult:
        return IngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(pracuj, "run_paginated_ingestion", _fake_run_paginated_ingestion)

    connector = PracujConnector()
    source = Source(id=7, connector="pracuj", config_json={})

    await connector.run(None, source)  # type: ignore[arg-type]

    assert recorded["source_id"] == 7
    assert recorded["dedup_key"] == "source:7"


class _FakePage:
    async def goto(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("real Playwright navigation should not happen in this unit test")


class _FakeContext:
    async def new_page(self) -> _FakePage:
        return _FakePage()


class _FakeBrowser:
    async def new_context(self, **kwargs: Any) -> _FakeContext:
        return _FakeContext()

    async def close(self) -> None:
        return None


class _FakeChromium:
    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()


class _FakePlaywrightContextManager:
    async def __aenter__(self) -> _FakePlaywright:
        return _FakePlaywright()

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def _fake_async_playwright() -> _FakePlaywrightContextManager:
    return _FakePlaywrightContextManager()


def test_httpx_never_referenced_in_pracuj_connector_module() -> None:
    tree = ast.parse(inspect.getsource(pracuj))
    import_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            import_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_names.add(node.module)

    assert "httpx" not in import_names
