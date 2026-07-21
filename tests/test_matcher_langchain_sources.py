from app.ingestion.normalize import BULLDOGJOB
from app.ingestion.registry import CONNECTOR_REGISTRY
from app.llm import matcher


def test_langchain_sources_equals_registry_keys() -> None:
    # "Always true by construction" per the connector registry's own design (see
    # docs/adr/0022-connector-registry-is-the-single-source-of-truth.md) -- a regression guard
    # against someone re-hardcoding this set later instead of deriving it from the registry.
    assert matcher.LANGCHAIN_SOURCES == frozenset(CONNECTOR_REGISTRY.keys())


def test_bulldogjob_is_scoring_eligible_purely_via_registry_entry() -> None:
    # No matcher.py edit was needed to add Bulldogjob -- its presence here is entirely a side
    # effect of its CONNECTOR_REGISTRY entry.
    assert BULLDOGJOB in matcher.LANGCHAIN_SOURCES
