import logging

import pytest
from app.ingestion.normalize import (
    JUSTJOINIT,
    NOFLUFFJOBS,
    SOLID_JOBS,
    normalize_remote,
    normalize_salary,
    normalize_seniority,
    to_int,
)


def _enable_logger() -> None:
    # see tests/test_ingestion_validate.py: alembic's fileConfig (triggered by
    # integration tests in the same session) can disable this logger.
    logging.getLogger("app.ingestion.normalize").disabled = False


def test_to_int_coerces_int_and_float() -> None:
    assert to_int(18000) == 18000
    assert to_int(18000.0) == 18000


def test_to_int_returns_none_for_non_numeric_or_missing() -> None:
    assert to_int(None) is None
    assert to_int("18000") is None
    assert to_int([1, 2]) is None


def test_normalize_remote_passes_through_bool_for_solid_jobs_and_nofluffjobs() -> None:
    assert normalize_remote(SOLID_JOBS, True) is True
    assert normalize_remote(SOLID_JOBS, False) is False
    assert normalize_remote(NOFLUFFJOBS, True) is True


def test_normalize_remote_maps_justjoinit_string_enum() -> None:
    assert normalize_remote(JUSTJOINIT, "remote") is True
    assert normalize_remote(JUSTJOINIT, "hybrid") is False
    assert normalize_remote(JUSTJOINIT, "office") is False


def test_normalize_remote_defaults_false_and_logs_for_unmapped_string_label(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_remote(JUSTJOINIT, "some-new-enum-value")

    assert result is False
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_normalize_remote_defaults_false_for_missing_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_remote(SOLID_JOBS, None)

    assert result is False
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_normalize_seniority_maps_native_senior_label_to_same_canonical_value() -> None:
    assert normalize_seniority(SOLID_JOBS, "Senior") == "senior"
    assert normalize_seniority(JUSTJOINIT, "senior") == "senior"
    assert normalize_seniority(NOFLUFFJOBS, "Senior") == "senior"


def test_normalize_seniority_maps_solid_jobs_regular_to_canonical_mid() -> None:
    assert normalize_seniority(SOLID_JOBS, "Regular") == "mid"


def test_normalize_seniority_maps_justjoinit_manager_and_c_level_to_canonical_lead() -> None:
    assert normalize_seniority(JUSTJOINIT, "manager") == "lead"
    assert normalize_seniority(JUSTJOINIT, "c_level") == "lead"


def test_normalize_seniority_joins_multiple_canonical_values_for_list_input() -> None:
    assert normalize_seniority(NOFLUFFJOBS, ["Mid", "Senior"]) == "mid, senior"


def test_normalize_seniority_returns_none_for_missing_field() -> None:
    assert normalize_seniority(SOLID_JOBS, None) is None


def test_normalize_seniority_drops_unmapped_label_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_seniority(JUSTJOINIT, "some-new-level")

    assert result is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_normalize_salary_defaults_currency_to_pln_when_absent() -> None:
    assert normalize_salary(SOLID_JOBS, 18000, 24000, None) == (18000, 24000, "PLN")


def test_normalize_salary_passes_through_pln_currency_without_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_salary(NOFLUFFJOBS, 13000, 22000, "PLN")

    assert result == (13000, 22000, "PLN")
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_normalize_salary_logs_warning_for_non_pln_currency(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_salary(JUSTJOINIT, 4500, 5625, "EUR")

    assert result == (4500, 5625, "EUR")
    assert any("EUR" in r.getMessage() for r in caplog.records)


def test_normalize_salary_logs_warning_when_raw_gross_is_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        result = normalize_salary(JUSTJOINIT, 20000, 25000, "PLN", raw_gross=False)

    assert result == (20000, 25000, "PLN")
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_normalize_salary_does_not_warn_when_raw_gross_is_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.ingestion.normalize"):
        normalize_salary(SOLID_JOBS, 18000, 24000, "PLN", raw_gross=None)

    assert not any(r.levelno == logging.WARNING for r in caplog.records)
