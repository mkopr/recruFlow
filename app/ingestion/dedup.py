import hashlib
from urllib.parse import urlsplit, urlunsplit

from app.schemas.offer import Offer


def normalize_canonical_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "")
    )


def _is_comparable(normalized_url: str) -> bool:
    return bool(urlsplit(normalized_url).path)


def compute_dedup_hash(offer: Offer) -> str:
    if offer.canonical_url:
        normalized = normalize_canonical_url(offer.canonical_url)
        if _is_comparable(normalized):
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    fallback_key = "|".join(
        [
            offer.title.strip().lower(),
            offer.company.strip().lower(),
            (offer.location or "").strip().lower(),
        ]
    )
    return hashlib.sha256(fallback_key.encode("utf-8")).hexdigest()
