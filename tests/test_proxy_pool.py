"""Unit tests for `ProxyPool`'s pool-management logic.

`tests/conftest.py`'s autouse fixture monkeypatches `ProxyPool.get_proxy` at the class level
for every test in the suite, so `pool.get_proxy(...)` attribute lookups always return the
stub `TEST_PROXY` regardless of pool state. To test the real pool-management logic, these
tests capture the unpatched function object at import time (before the autouse fixture has
run) and call it directly -- `_REAL_GET_PROXY(pool, logger)` is a direct call on the captured
function, not an attribute lookup on the class, so it bypasses the monkeypatch entirely.
"""

import logging

import pytest
from app.config import get_settings
from app.connectors.proxy_pool import ProxyPool, get_shared_proxy_pool

_REAL_GET_PROXY = ProxyPool.get_proxy
_LOGGER = logging.getLogger("test_proxy_pool")


def test_get_proxy_returns_from_pool_without_scraping_when_nonempty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool(target_size=2)
    pool._good = ["http://1.1.1.1:80"]

    def _should_not_scrape(self: ProxyPool, logger: logging.Logger) -> str | None:
        raise AssertionError("should not scrape")

    monkeypatch.setattr(ProxyPool, "_scrape_one", _should_not_scrape)

    result = _REAL_GET_PROXY(pool, _LOGGER)

    assert result == "http://1.1.1.1:80"


def test_get_proxy_picks_via_injected_random_source() -> None:
    sentinel = "http://picked:80"

    class _FakeRandom:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def choice(self, seq: list[str]) -> str:
            self.calls.append(list(seq))
            return sentinel

    fake_rand = _FakeRandom()
    pool = ProxyPool(rand=fake_rand)  # type: ignore[arg-type]
    pool._good = ["a", "b"]

    result = _REAL_GET_PROXY(pool, _LOGGER)

    assert result is sentinel
    assert fake_rand.calls == [["a", "b"]]


def test_get_proxy_triggers_cold_start_topup_when_pool_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool(target_size=1)

    def _scrape_once(self: ProxyPool, logger: logging.Logger) -> str | None:
        return "http://2.2.2.2:80"

    monkeypatch.setattr(ProxyPool, "_scrape_one", _scrape_once)

    result = _REAL_GET_PROXY(pool, _LOGGER)

    assert result == "http://2.2.2.2:80"
    assert pool.size() == 1


def test_get_proxy_returns_none_when_scrape_source_has_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool(target_size=1)

    monkeypatch.setattr(ProxyPool, "_scrape_one", lambda self, logger: None)

    result = _REAL_GET_PROXY(pool, _LOGGER)

    assert result is None
    assert pool.size() == 0


def test_report_failure_evicts_present_proxy() -> None:
    pool = ProxyPool()
    pool._good = ["a", "b"]

    pool.report_failure("a", _LOGGER)

    assert pool.size() == 1


def test_report_failure_is_noop_for_absent_proxy() -> None:
    pool = ProxyPool()
    pool._good = ["a"]

    pool.report_failure("z", _LOGGER)

    assert pool.size() == 1


def test_top_up_is_noop_once_target_size_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = ProxyPool(target_size=2)
    pool._good = ["a", "b"]

    def _should_not_scrape(self: ProxyPool, logger: logging.Logger) -> str | None:
        raise AssertionError("should not scrape")

    monkeypatch.setattr(ProxyPool, "_scrape_one", _should_not_scrape)

    assert pool.top_up(_LOGGER) == 0


def test_top_up_admits_candidates_until_target_size(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = ProxyPool(target_size=3)
    candidates = iter(["a", "b", "c"])

    monkeypatch.setattr(ProxyPool, "_scrape_one", lambda self, logger: next(candidates))

    assert pool.top_up(_LOGGER) == 3
    assert pool.size() == 3


def test_top_up_skips_none_results_and_respects_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = ProxyPool(target_size=5)
    call_count = [0]

    def _always_none(self: ProxyPool, logger: logging.Logger) -> str | None:
        call_count[0] += 1
        return None

    monkeypatch.setattr(ProxyPool, "_scrape_one", _always_none)

    assert pool.top_up(_LOGGER, max_attempts=4) == 0
    assert call_count[0] == 4
    assert pool.size() == 0


def test_top_up_deduplicates_repeated_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = ProxyPool(target_size=2)

    monkeypatch.setattr(ProxyPool, "_scrape_one", lambda self, logger: "http://dup:80")

    assert pool.top_up(_LOGGER, max_attempts=5) == 1
    assert pool.size() == 1


def test_get_shared_proxy_pool_returns_same_instance_across_calls() -> None:
    assert get_shared_proxy_pool() is get_shared_proxy_pool()


def test_get_shared_proxy_pool_uses_settings_target_size() -> None:
    assert get_shared_proxy_pool().target_size == get_settings().proxy_pool_target_size
