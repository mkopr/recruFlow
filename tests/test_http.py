import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx
import pytest
from app.connectors.http import fetch_json, fetch_xml

from tests.conftest import TEST_USER_AGENT

_LOGGER = logging.getLogger("app.connectors.http")


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
    logging.getLogger("app.connectors.http").disabled = False


def test_fetch_json_returns_none_and_logs_on_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_json("https://example.com/offers", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_json_returns_none_and_logs_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    request = httpx.Request("GET", "https://example.com/offers")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_json("https://example.com/offers", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_json_returns_none_and_logs_on_malformed_json(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    json_error = json.JSONDecodeError("Expecting value", "not json{{{", 0)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(text="not json{{{", json_error=json_error),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_json("https://example.com/offers", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_json_returns_parsed_payload_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"jobs": [{"title": "a"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(json_data=payload))

    result = fetch_json("https://example.com/offers", source_name="Example", logger=_LOGGER)

    assert result == payload


def test_fetch_json_forwards_params_and_merges_default_user_agent_with_extra_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse(json_data={})

    monkeypatch.setattr(httpx, "get", _fake_get)

    fetch_json(
        "https://example.com/offers",
        source_name="Example",
        logger=_LOGGER,
        params={"page": 1},
        headers={"X-Api-Version": "1.0"},
    )

    assert captured["params"] == {"page": 1}
    assert captured["headers"]["User-Agent"] == TEST_USER_AGENT
    assert captured["headers"]["X-Api-Version"] == "1.0"


def test_fetch_xml_returns_none_and_logs_on_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()

    def _raise(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(httpx, "get", _raise)

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_xml("https://example.com/feed.rss", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_xml_returns_none_and_logs_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    request = httpx.Request("GET", "https://example.com/feed.rss")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(status_error=status_error))

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_xml("https://example.com/feed.rss", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_fetch_xml_returns_none_and_logs_on_malformed_xml(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable_logger()
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _FakeResponse(text="<rss><channel><item><title>unterminated"),
    )

    with caplog.at_level(logging.ERROR, logger="app.connectors.http"):
        result = fetch_xml("https://example.com/feed.rss", source_name="Example", logger=_LOGGER)

    assert result is None
    assert any("malformed XML" in r.message for r in caplog.records)


def test_fetch_xml_returns_parsed_element_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    xml_text = "<rss><channel><item><title>a</title></item></channel></rss>"
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse(text=xml_text))

    result = fetch_xml("https://example.com/feed.rss", source_name="Example", logger=_LOGGER)

    assert isinstance(result, ET.Element)
    assert result.find("channel") is not None


def test_fetch_xml_forwards_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse(text="<rss></rss>")

    monkeypatch.setattr(httpx, "get", _fake_get)

    fetch_xml(
        "https://example.com/feed.rss",
        source_name="Example",
        logger=_LOGGER,
        params={"page": 1},
        headers={"X-Api-Version": "1.0"},
    )

    assert captured["params"] == {"page": 1}
    assert captured["headers"]["User-Agent"] == TEST_USER_AGENT
    assert captured["headers"]["X-Api-Version"] == "1.0"
