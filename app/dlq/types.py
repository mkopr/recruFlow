from enum import StrEnum


class FailureType(StrEnum):
    """The DLQ's dispatch vocabulary (BUG38).

    Every writer (`record_failure` call site) and reader (`app.dlq.retry.RETRY_HANDLERS`)
    must agree on these keys. Typing both ends against this enum turns a typo into a mypy
    error at the write site instead of a `KeyError` three hops later at retry time.
    """

    VALIDATION_FAILED = "validation_failed"
    PAGE_FETCH_FAILED = "page_fetch_failed"
    RUN_FETCH_FAILED = "run_fetch_failed"
    SCORING_FAILED = "scoring_failed"
