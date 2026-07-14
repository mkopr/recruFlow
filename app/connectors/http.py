import gzip
import json
import logging
from typing import Any

import httpx


def fetch_json(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> Any | None:
    try:
        response = httpx.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "recruFlow/0.1", **(headers or {})},
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.error(
            "failed to fetch %s offers: url=%r params=%r",
            source_name,
            url,
            params,
            exc_info=True,
        )
        return None

    try:
        return response.json()
    except json.JSONDecodeError:
        logger.error(
            "%s returned malformed JSON: url=%r body=%r", source_name, url, response.text[:500]
        )
        return None


def fetch_gzip_xml(
    url: str,
    *,
    source_name: str,
    logger: logging.Logger,
    timeout: float = 10.0,
) -> str | None:
    try:
        response = httpx.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "recruFlow/0.1"},
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.error("failed to fetch %s sitemap: url=%r", source_name, url, exc_info=True)
        return None

    try:
        return gzip.decompress(response.content).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        logger.error("%s returned malformed gzip sitemap: url=%r", source_name, url)
        return None
