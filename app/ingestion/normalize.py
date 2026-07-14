import logging
from typing import Any

logger = logging.getLogger(__name__)

SOLID_JOBS = "solid_jobs"
JUSTJOINIT = "justjoinit"
NOFLUFFJOBS = "nofluffjobs"
BULLDOGJOB = "bulldogjob"
ROCKET_JOBS = "rocket_jobs"
PRACUJ = "pracuj"
REMOTEOK = "remoteok"

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
    BULLDOGJOB: {
        "junior": "junior",
        "medium": "mid",
        "senior": "senior",
        "lead": "lead",
    },
    # The full `positionLevels` dictionary Pracuj.pl's own search page embeds in
    # `__NEXT_DATA__` (confirmed live 2026-07-14, 11 entries) -- every raw label this
    # connector can ever see, not a guessed subset. "pracownik fizyczny / pracowniczka
    # fizyczna" (manual/physical labor) is intentionally omitted: it doesn't map onto
    # engineering seniority, and the connector's own `category_filter` keyword search makes
    # it unlikely to appear in ingested offers anyway -- an unmapped label just logs a
    # warning and contributes nothing, per `normalize_seniority`'s existing "don't guess"
    # contract, rather than being force-fit onto one of the five canonical levels here.
    PRACUJ: {
        "praktykant / praktykantka - stażysta / stażystka": "junior",
        "asystent / asystentka": "junior",
        "młodszy specjalista / młodsza specjalistka (junior)": "junior",
        "specjalista / specjalistka (mid / regular)": "mid",
        "starszy specjalista / starsza specjalistka (senior)": "senior",
        "ekspert / ekspertka": "expert",
        "kierownik / kierowniczka - koordynator / koordynatorka": "lead",
        "menedżer / menedżerka": "lead",
        "dyrektor / dyrektorka": "lead",
        "prezes / prezeska": "lead",
        # English-language equivalents of the three lowest levels above -- observed live
        # 2026-07-14 during manual end-to-end verification against the real Pracuj.pl site:
        # some individual job postings are authored in English (`jobOfferLanguage.isoCode`),
        # and Pracuj.pl renders that posting's own positionLevels labels in English to match,
        # regardless of the browser session's `pl-PL` locale. Only the three levels actually
        # observed are mapped -- the remaining eight Polish-only entries above have no
        # confirmed English counterpart yet, so they are left unmapped rather than guessed.
        "junior specialist (junior)": "junior",
        "specialist (mid / regular)": "mid",
        "senior specialist (senior)": "senior",
        "manager / supervisor": "lead",
    },
}

_REMOTE_STRING_VOCAB: dict[str, dict[str, bool]] = {
    JUSTJOINIT: {"remote": True, "hybrid": False, "office": False},
    # schema.org JobPosting's standard `jobLocationType` value for a remote posting -- observed
    # live 2026-07-14 on a real automatic Rocket Jobs ingestion run (not present on every
    # posting, only remote ones, matching schema.org's own spec for this field).
    ROCKET_JOBS: {"telecommute": True},
    # No PRACUJ entry: `attributes.employment.entirelyRemoteWork` (confirmed live 2026-07-14)
    # is already a native boolean, not a string label -- `normalize_remote` returns it as-is
    # via its `isinstance(raw_value, bool)` branch without ever consulting this vocab, so
    # there is no raw string value to seed here.
}


def to_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def extract_envelope_list(
    payload: Any, key: str, *, allow_bare_list: bool = True
) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        if not allow_bare_list:
            return None
        items: list[Any] = payload
    elif isinstance(payload, dict):
        if key not in payload:
            return None
        raw_items = payload[key]
        if raw_items is None:
            items = []
        elif isinstance(raw_items, list):
            items = raw_items
        else:
            return None
    else:
        return None

    return [item for item in items if isinstance(item, dict)]


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
