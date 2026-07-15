from pathlib import Path

CONNECTORS_DIR = Path(__file__).resolve().parent.parent / "app" / "connectors"


def test_parse_sitemap_locs_is_public() -> None:
    from app.connectors.sitemap import parse_sitemap_locs  # noqa: F401


def test_no_underscore_prefixed_sitemap_import_across_connectors() -> None:
    for path in CONNECTORS_DIR.glob("*.py"):
        assert "_parse_sitemap_locs" not in path.read_text(), path
