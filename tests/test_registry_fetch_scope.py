from app.ingestion.registry import CONNECTOR_REGISTRY


def test_only_three_connectors_support_fetch_scope() -> None:
    # Pins US47's scope decision -- only the 3 connectors with a confirmed live keyword-filter
    # mechanism support Fetch Scope's "filtered" mode. A future connector addition flipping this
    # on/off must update this assertion deliberately, not silently.
    supported = {name for name, spec in CONNECTOR_REGISTRY.items() if spec.supports_fetch_scope}

    assert supported == {"solid_jobs", "bulldogjob", "pracuj"}
