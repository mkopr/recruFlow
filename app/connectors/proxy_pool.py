import logging
import random
import threading
from functools import lru_cache

from fp.errors import FreeProxyException
from fp.fp import FreeProxy

from app.config import get_settings


class ProxyPool:
    """Hands out a proxy from a small warm pool of already-verified-good addresses, instead
    of scraping and verifying a fresh candidate on every call.

    Before this class existed in this shape, `get_proxy` called `FreeProxy(...).get()`
    directly on every single invocation -- despite the "pool" name, there was no caching or
    reuse at all, so every proxy-rotated fetch (up to 3 attempts per URL, up to ~1,000 URLs
    per Rocket Jobs/Pracuj.pl run) paid a fresh ~5-40s scrape-and-verify cost (BUG49). This
    class turns that into "near-zero on the common case, drawn from a pool that's already
    paid the cost" -- the same "persist expensive state, don't restart from scratch" shape
    BUG41 established for the sitemap cursor, just with process-lifetime in-memory state
    here rather than a DB-persisted one, since a scraped proxy's freshness doesn't survive a
    process restart anyway.

    A single sticky proxy was considered and rejected: hammering one IP against the target
    site isn't desirable, and losing that one proxy would fully reset back to cold-scrape
    latency. A pool of several (`target_size`) spreads load across multiple IPs and only
    needs a background top-up, not a full reset, when one member goes bad.

    Per BUG49, this is also now a *shared* pool: the three connector modules that used to
    each construct their own independent `ProxyPool()` (`http.py`, `sitemap_detail.py`,
    `pracuj.py`) never benefited from each other's verified proxies. `get_shared_proxy_pool`
    below gives every module the same process-lifetime instance so a proxy verified by one
    connector's traffic is immediately available to the others too.

    Every call into this pool happens via `asyncio.to_thread` from an arbitrary worker
    thread (BUG42's finding: connectors' blocking HTTP/Playwright calls run off the main
    event loop), and once the background top-up job (see `run_proxy_pool_topup_job`) is
    added, potentially from a second worker thread concurrently with a live connector run.
    Per BUG47's precedent (an `asyncio.Lock` binds to whichever event loop first touches it
    and raises if a different loop/thread touches it again), any state shared across real OS
    threads like this must use `threading.Lock`, not an asyncio-native primitive.
    """

    def __init__(
        self,
        *,
        https: bool = True,
        timeout: float = 2.0,
        request_timeout: float = 10.0,
        target_size: int = 5,
        rand: random.Random | None = None,
    ) -> None:
        # `FreeProxy` defaults to `https=False`, which builds a proxy dict keyed "http"
        # while checking it against an https:// URL. `requests` matches proxy keys by the
        # target's scheme, so that key is never used, the check silently runs unproxied,
        # and every candidate "passes" without a proxy ever being tested. `https=True`
        # keeps the check's URL scheme and the proxy key aligned so verification is real.
        self._https = https
        self._timeout = timeout
        self._request_timeout = request_timeout
        self.target_size = target_size
        self._rand = rand if rand is not None else random.Random()
        self._lock = threading.Lock()
        self._good: list[str] = []

    def get_proxy(self, logger: logging.Logger) -> str | None:
        """Return a random proxy from the good pool, never the same one every time -- spreads
        request load across several IPs instead of hammering one. If the pool is empty (cold
        start, e.g. right after process boot, or every member has since been evicted), this
        pays a one-time synchronous top-up before returning -- unavoidable once, but never a
        per-request cost once the pool is warm. Returns `None`, never raises, exactly like the
        pre-BUG49 implementation, so no call site's exception handling changes.
        """
        with self._lock:
            if self._good:
                return self._rand.choice(self._good)
        self.top_up(logger)
        with self._lock:
            if self._good:
                return self._rand.choice(self._good)
        return None

    def report_failure(self, proxy: str, logger: logging.Logger) -> None:
        """Evict `proxy` from the good pool because a caller's actual request against the
        target site failed through it. A no-op if `proxy` isn't currently in the pool --
        handles the race where two callers were handed the same proxy and one already evicted
        it, and keeps this call safe to make against a differently-seeded or fresh pool
        instance in tests.
        """
        with self._lock:
            if proxy in self._good:
                self._good.remove(proxy)
                logger.info(
                    "evicted failed proxy from pool: proxy=%r pool_size=%d",
                    proxy,
                    len(self._good),
                )

    def size(self) -> int:
        """Thread-safe read of the current good-pool size."""
        with self._lock:
            return len(self._good)

    def top_up(self, logger: logging.Logger, *, max_attempts: int | None = None) -> int:
        """Scrape and verify fresh candidates until the pool is back at `target_size`, admitting
        each one that passes. Bounded by `max_attempts` (defaults to `target_size * 4`, giving
        room for the ~15% real-world hit rate found by the earlier free-proxy spike) so a fully
        down scrape source can't hang this forever. Cheap and network-free when the pool is
        already at `target_size` -- returns 0 immediately. Never raises: `_scrape_one` already
        swallows `FreeProxyException`. Called both from `get_proxy`'s cold-start path and from
        the periodic `proxy_pool:topup` scheduler job (`run_proxy_pool_topup_job`), so the pool
        self-heals as proxies get evicted without paying the full scrape cost on the request
        path in the common case.
        """
        attempts_budget = max_attempts if max_attempts is not None else self.target_size * 4
        admitted = 0
        attempts = 0
        while attempts < attempts_budget:
            with self._lock:
                if len(self._good) >= self.target_size:
                    break
            attempts += 1
            candidate = self._scrape_one(logger)
            if candidate is None:
                continue
            with self._lock:
                if candidate not in self._good and len(self._good) < self.target_size:
                    self._good.append(candidate)
                    admitted += 1
        if admitted:
            logger.info("proxy pool topped up: admitted=%d pool_size=%d", admitted, self.size())
        return admitted

    def _scrape_one(self, logger: logging.Logger) -> str | None:
        """Scrape a fresh proxy list and return one verified-working entry, or `None` if the
        source has nothing usable right now. `FreeProxy(...).get()` already applies the "fast"
        bar (a real request completing within `request_timeout`) internally, so a candidate it
        returns is admission-ready as-is -- no separate speed check needed here.
        """
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


@lru_cache
def get_shared_proxy_pool() -> ProxyPool:
    """Process-lifetime singleton, memoized exactly like `get_settings()`. Replaces the three
    independent `_proxy_pool = ProxyPool()` module-level singletons that used to live in
    `http.py`, `sitemap_detail.py`, and `pracuj.py` -- every module that calls this now shares
    one pool, so a proxy verified by one connector's traffic is immediately usable by the
    others too, instead of each rediscovering its own set from scratch.
    """
    return ProxyPool(target_size=get_settings().proxy_pool_target_size)
