from app.ingestion.dedup import compute_dedup_hash, normalize_canonical_url
from app.schemas.offer import Offer


def test_normalize_canonical_url_strips_query_and_fragment() -> None:
    result = normalize_canonical_url("https://Example.com/Jobs/1?utm_source=x#section")

    assert result == "https://example.com/Jobs/1"


def test_normalize_canonical_url_strips_trailing_slash() -> None:
    result = normalize_canonical_url("https://example.com/jobs/1/")

    assert result == "https://example.com/jobs/1"


def test_compute_dedup_hash_same_for_urls_differing_only_by_query_string() -> None:
    offer_a = Offer(
        source_id=1,
        title="Backend Engineer",
        company="Acme",
        canonical_url="https://example.com/jobs/1?utm_source=newsletter",
    )
    offer_b = Offer(
        source_id=2,
        title="Data Engineer",
        company="Widgets Inc",
        canonical_url="https://example.com/jobs/1?utm_source=twitter",
    )

    assert compute_dedup_hash(offer_a) == compute_dedup_hash(offer_b)


def test_compute_dedup_hash_falls_back_when_canonical_url_is_none() -> None:
    offer_a = Offer(source_id=1, title="Backend Engineer", company="Acme", location="Warsaw")
    offer_b = Offer(source_id=2, title="Backend Engineer", company="Acme", location="Warsaw")

    assert compute_dedup_hash(offer_a) == compute_dedup_hash(offer_b)


def test_compute_dedup_hash_falls_back_when_canonical_url_is_bare_domain() -> None:
    offer_a = Offer(
        source_id=1,
        title="Backend Engineer",
        company="Acme",
        location="Warsaw",
        canonical_url="https://example.com",
    )
    offer_b = Offer(
        source_id=2,
        title="Backend Engineer",
        company="Acme",
        location="Warsaw",
        canonical_url="https://example.com/",
    )

    assert compute_dedup_hash(offer_a) == compute_dedup_hash(offer_b)


def test_compute_dedup_hash_fallback_is_case_and_whitespace_insensitive() -> None:
    offer_a = Offer(source_id=1, title="Backend Engineer", company="Acme", location="Warsaw")
    offer_b = Offer(source_id=2, title="  backend engineer  ", company="ACME", location="Warsaw")

    assert compute_dedup_hash(offer_a) == compute_dedup_hash(offer_b)


def test_compute_dedup_hash_differs_for_distinct_offers() -> None:
    offer_a = Offer(
        source_id=1,
        title="Backend Engineer",
        company="Acme",
        canonical_url="https://example.com/jobs/1",
    )
    offer_b = Offer(
        source_id=2,
        title="Data Engineer",
        company="Widgets Inc",
        canonical_url="https://example.com/jobs/2",
    )

    assert compute_dedup_hash(offer_a) != compute_dedup_hash(offer_b)
