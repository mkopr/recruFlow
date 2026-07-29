import logging

from fp.errors import FreeProxyException
from fp.fp import FreeProxy


class ProxyPool:
    """Hands out a fresh, verified proxy on each call via the `free-proxy` scraper.

    `FreeProxy` defaults to `https=False`, which builds a proxy dict keyed "http"
    while checking it against an https:// URL. `requests` matches proxy keys by the
    target's scheme, so that key is never used, the check silently runs unproxied,
    and every candidate "passes" without a proxy ever being tested. `https=True`
    keeps the check's URL scheme and the proxy key aligned so verification is real.
    """

    def __init__(
        self,
        *,
        https: bool = True,
        timeout: float = 2.0,
        request_timeout: float = 10.0,
    ) -> None:
        self._https = https
        self._timeout = timeout
        self._request_timeout = request_timeout

    def get_proxy(self, logger: logging.Logger) -> str | None:
        """Scrape a fresh proxy list and return the first verified-working entry."""
        try:
            proxy: str | None = FreeProxy(
                https=self._https,
                rand=True,
                timeout=self._timeout,
                request_timeout=self._request_timeout,
            ).get()
            return proxy
        except FreeProxyException:
            logger.error("no working proxy could be found", exc_info=True)
            return None
