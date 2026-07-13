from app.ingestion.registry import CONNECTOR_REGISTRY
from app.llm import matcher


def test_langchain_sources_equals_registry_keys() -> None:
    # "Always true by construction" per P3US37's own design (see
    # docs/adr/0022-connector-registry-is-the-single-source-of-truth.md) -- a regression guard
    # against someone re-hardcoding this set later instead of deriving it from the registry.
    assert matcher.LANGCHAIN_SOURCES == frozenset(CONNECTOR_REGISTRY.keys())
