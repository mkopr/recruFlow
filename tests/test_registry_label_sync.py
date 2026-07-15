from app.connectors import we_work_remotely
from app.connectors.base import JobBoardConnector
from app.ingestion.normalize import PRACUJ, REMOTEOK, REMOTIVE, SOLID_JOBS, WE_WORK_REMOTELY
from app.ingestion.registry import CONNECTOR_REGISTRY


def test_label_matches_connector_name_for_every_class_backed_entry() -> None:
    # Guards against `label` and `dispatch.__self__.name` drifting apart -- mirrors
    # `test_langchain_sources_equals_registry_keys`'s "would fail loudly if a future edit
    # desyncs them" framing (US46).
    for connector, spec in CONNECTOR_REGISTRY.items():
        instance = getattr(spec.dispatch, "__self__", None)
        if isinstance(instance, JobBoardConnector):
            assert spec.label == instance.name, connector


def test_we_work_remotely_label_matches_module_name_constant() -> None:
    assert CONNECTOR_REGISTRY[WE_WORK_REMOTELY].label == we_work_remotely.NAME


def test_seed_config_overrides_present_for_pracuj_remoteok_remotive() -> None:
    assert CONNECTOR_REGISTRY[PRACUJ].seed_config_overrides == {
        "schedule": {"type": "interval", "seconds": 3600},
        "category_filter": "it",
    }
    assert CONNECTOR_REGISTRY[REMOTEOK].seed_config_overrides == {
        "schedule": {"type": "interval", "seconds": 120}
    }
    assert CONNECTOR_REGISTRY[REMOTIVE].seed_config_overrides == {
        "categories": ["software-development", "devops", "qa", "data"]
    }


def test_seed_config_overrides_defaults_empty_for_connector_without_override() -> None:
    assert CONNECTOR_REGISTRY[SOLID_JOBS].seed_config_overrides == {}
