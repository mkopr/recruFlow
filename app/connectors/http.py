import gzip
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.connectors.fingerprint import FingerprintPool
from app.connectors.proxy_pool import get_shared_proxy_pool

_MAX_PROXY_ATTEMPTS = 3

_proxy_pool = get_shared_proxy_pool()
_fingerprints = FingerprintPool()


class BlockedFetchError(Exception):
    """Raised when every proxy-rotated attempt's final failure was an HTTP 403 or 429 --
    the shape of a bot-block (Cloudflare Managed Challenge and similar), as distinct from a
    timeout, connection error, 5xx, or malformed response. Callers that want to collect and
    later retry blocked fetches (as opposed to today's "log and move on") catch this
    specifically; everything else about `_get`'s failure contract -- returning `None` on any
    other failure, never raising -- is unchanged.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"blocked: HTTP {status_code}")
        self.status_code = status_code


def _get(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    follow_redirects: bool = False,
    error_noun: str = "offers",
    log_params: bool = True,
) -> httpx.Response | None:
    last_status_code: int | None = None
    for attempt in range(1, _MAX_PROXY_ATTEMPTS + 1):
        proxy = _proxy_pool.get_proxy(logger)
        if proxy is None:
            continue

        try:
            response = httpx.get(
                url,
                params=params,
                timeout=timeout,
                headers={**_fingerprints.get_headers(), **(headers or {})},
                follow_redirects=follow_redirects,
                proxy=proxy,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            last_status_code = exc.response.status_code
            logger.error(
                "request failed via proxy %r (attempt %d/%d): url=%r",
                proxy,
                attempt,
                _MAX_PROXY_ATTEMPTS,
                url,
                exc_info=True,
            )
            _proxy_pool.report_failure(proxy, logger)
            continue
        except httpx.HTTPError:
            last_status_code = None
            logger.error(
                "request failed via proxy %r (attempt %d/%d): url=%r",
                proxy,
                attempt,
                _MAX_PROXY_ATTEMPTS,
                url,
                exc_info=True,
            )
            _proxy_pool.report_failure(proxy, logger)
            continue

        return response

    if log_params:
        logger.error(
            "failed to fetch %s %s after %d attempts: url=%r params=%r",
            source_name,
            error_noun,
            _MAX_PROXY_ATTEMPTS,
            url,
            params,
        )
    else:
        logger.error(
            "failed to fetch %s %s after %d attempts: url=%r",
            source_name,
            error_noun,
            _MAX_PROXY_ATTEMPTS,
            url,
        )

    if last_status_code is not None and last_status_code in (403, 429):
        raise BlockedFetchError(last_status_code)
    return None


def fetch_json(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> Any | None:
    response = _get(
        url,
        source_name=source_name,
        logger=logger,
        params=params,
        headers=headers,
        timeout=timeout,
        error_noun="offers",
    )
    if response is None:
        return None

    try:
        return response.json()
    except json.JSONDecodeError:
        logger.error(
            "%s returned malformed JSON: url=%r body=%r", source_name, url, response.text[:500]
        )
        return None


def fetch_xml(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> ET.Element | None:
    """Low-level XML fetch primitive, the RSS/XML sibling of `fetch_json`. Only fetches and
    parses well-formed-XML-or-not -- it knows nothing about RSS `<item>`/`<channel>` shape;
    that validation belongs one layer up in the connector module, same split as
    `extract_envelope_list` for `fetch_json`.
    """
    response = _get(
        url,
        source_name=source_name,
        logger=logger,
        params=params,
        headers=headers,
        timeout=timeout,
        error_noun="offers",
    )
    if response is None:
        return None

    try:
        return ET.fromstring(response.text)
    except ET.ParseError:
        logger.error(
            "%s returned malformed XML: url=%r body=%r", source_name, url, response.text[:500]
        )
        return None


def fetch_gzip_xml(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    timeout: float = 10.0,
) -> str | None:
    response = _get(
        url,
        source_name=source_name,
        logger=logger,
        timeout=timeout,
        error_noun="sitemap",
        log_params=False,
    )
    if response is None:
        return None

    try:
        return gzip.decompress(response.content).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        logger.error("%s returned malformed gzip sitemap: url=%r", source_name, url)
        return None


def fetch_text(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    timeout: float = 10.0,
) -> str | None:
    response = _get(
        url,
        source_name=source_name,
        logger=logger,
        timeout=timeout,
        follow_redirects=True,
        error_noun="sitemap",
        log_params=False,
    )
    if response is None:
        return None

    return response.text
