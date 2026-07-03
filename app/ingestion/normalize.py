import logging
from typing import Any

logger = logging.getLogger(__name__)

SOLID_JOBS = "solid_jobs"
JUSTJOINIT = "justjoinit"
NOFLUFFJOBS = "nofluffjobs"

CANONICAL_SENIORITY_LEVELS: tuple[str, ...] = ("junior", "mid", "senior", "lead", "expert")

_SENIORITY_VOCAB: dict[str, dict[str, str]] = {
    SOLID_JOBS: {
        "junior": "junior",
        "regular": "mid",
        "mid": "mid",
        "senior": "senior",
        "expert": "expert",
    },
    JUSTJOINIT: {
        "junior": "junior",
        "mid": "mid",
        "senior": "senior",
        "c_level": "lead",
        "manager": "lead",
    },
    NOFLUFFJOBS: {
        "trainee": "junior",
        "junior": "junior",
        "mid": "mid",
        "senior": "senior",
        "expert": "expert",
        "c-level": "lead",
    },
}

_REMOTE_STRING_VOCAB: dict[str, dict[str, bool]] = {
    JUSTJOINIT: {"remote": True, "hybrid": False, "office": False},
}


def to_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def normalize_remote(source_name: str, raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value

    if isinstance(raw_value, str):
        label = raw_value.strip().lower()
        vocab = _REMOTE_STRING_VOCAB.get(source_name, {})
        if label in vocab:
            return vocab[label]
        logger.warning("unmapped remote label: source=%r raw_value=%r", source_name, raw_value)
        return False

    return False


def normalize_seniority(source_name: str, raw_value: Any) -> str | None:
    if raw_value is None:
        return None

    items = raw_value if isinstance(raw_value, list) else [raw_value]
    vocab = _SENIORITY_VOCAB.get(source_name, {})

    canonical_levels: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            continue
        label = item.strip().lower()
        canonical = vocab.get(label)
        if canonical is None:
            logger.warning("unmapped seniority label: source=%r raw_value=%r", source_name, item)
            continue
        if canonical not in canonical_levels:
            canonical_levels.append(canonical)

    return ", ".join(canonical_levels) if canonical_levels else None


def normalize_salary(
    source_name: str,
    salary_min: int | None,
    salary_max: int | None,
    raw_currency: Any,
    *,
    raw_gross: bool | None = None,
) -> tuple[int | None, int | None, str]:
    currency = str(raw_currency).strip().upper() if raw_currency else "PLN"

    if currency != "PLN":
        logger.warning(
            "non-PLN currency observed, no FX conversion performed: "
            "source=%r currency=%r salary_min=%r salary_max=%r",
            source_name,
            currency,
            salary_min,
            salary_max,
        )

    if raw_gross is False:
        logger.warning(
            "net (non-gross) salary figure observed, no net-to-gross conversion performed: "
            "source=%r salary_min=%r salary_max=%r",
            source_name,
            salary_min,
            salary_max,
        )

    return salary_min, salary_max, currency
