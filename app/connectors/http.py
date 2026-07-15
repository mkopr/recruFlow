import gzip
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx


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
    try:
        response = httpx.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "recruFlow/0.1", **(headers or {})},
            follow_redirects=follow_redirects,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        if log_params:
            logger.error(
                "failed to fetch %s %s: url=%r params=%r",
                source_name,
                error_noun,
                url,
                params,
                exc_info=True,
            )
        else:
            logger.error(
                "failed to fetch %s %s: url=%r", source_name, error_noun, url, exc_info=True
            )
        return None

    return response


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
