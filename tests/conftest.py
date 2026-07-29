"""Global stub for `app/connectors/http.py`'s proxy/fingerprint pools.

`http.py` instantiates `ProxyPool()`/`FingerprintPool()` once at import time and calls
`_proxy_pool.get_proxy(...)` on every `_get()` attempt. The real `ProxyPool.get_proxy`
(`app/connectors/proxy_pool.py`) scrapes and verifies proxies against live third-party
sites via the `free-proxy` package -- tests must never trigger that. `FingerprintPool`
is offline (stdlib `random`) but stubbed too so header assertions are deterministic.
An autouse fixture patches both classes' methods for every test in the suite, which
also covers the already-constructed module-level singletons since method lookup goes
through the class at call time.
"""

import pytest
from app.connectors.fingerprint import FingerprintPool
from app.connectors.proxy_pool import ProxyPool

TEST_USER_AGENT = "recruflow-test-agent/1.0"
TEST_PROXY = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def _stub_proxy_and_fingerprint_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ProxyPool, "get_proxy", lambda self, logger: TEST_PROXY)
    monkeypatch.setattr(
        FingerprintPool, "get_headers", lambda self: {"User-Agent": TEST_USER_AGENT}
    )
