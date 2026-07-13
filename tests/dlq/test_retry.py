from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.dlq.retry import RETRY_HANDLERS, UnknownFailureTypeError, perform_retry
from app.dlq.types import FailureType


def test_retry_handlers_covers_every_failure_type() -> None:
    assert set(RETRY_HANDLERS) == set(FailureType)


@pytest.mark.asyncio
async def test_perform_retry_raises_named_error_for_unrecognized_failure_type() -> None:
    session = AsyncMock()
    row = SimpleNamespace(failure_type="not_a_real_failure_type")

    with pytest.raises(UnknownFailureTypeError) as exc_info:
        await perform_retry(session, row)

    assert exc_info.value.failure_type == "not_a_real_failure_type"
    session.commit.assert_not_called()
