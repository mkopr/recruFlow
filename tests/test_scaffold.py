from app import __version__


def test_app_package_exposes_version() -> None:
    assert __version__ == "0.1.0"
