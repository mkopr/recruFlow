from pathlib import Path

import pytest
from app.config import Settings, get_settings
from pydantic import ValidationError

FULL_ENV = """\
DATABASE_URL=postgresql+asyncpg://sentinel:sentinel@sentinel-host:5432/sentinel
OLLAMA_BASE_URL=http://sentinel-ollama:11434
OLLAMA_MODEL=sentinel-model
SMTP_HOST=smtp.sentinel.test
SMTP_PORT=2525
SMTP_USERNAME=sentinel-user
SMTP_PASSWORD=sentinel-pass
SMTP_FROM_EMAIL=sentinel@sentinel.test
SJCTL_CAMPAIGN=sentinel-campaign
APP_ENV=sentinel-env
LOG_LEVEL=DEBUG
API_HOST=127.0.0.1
API_PORT=9000
CORS_ALLOW_ORIGIN=http://sentinel-frontend.test
"""

MINIMAL_ENV = """\
DATABASE_URL=postgresql+asyncpg://x:x@localhost:5432/x
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.3:70b
"""


ENV_KEYS = [
    "DATABASE_URL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    "SJCTL_CAMPAIGN",
    "APP_ENV",
    "LOG_LEVEL",
    "API_HOST",
    "API_PORT",
    "CORS_ALLOW_ORIGIN",
]


def _write_env(tmp_path: Path, content: str) -> str:
    env_file = tmp_path / ".env"
    env_file.write_text(content)
    return str(env_file)


def _clear_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_loads_fields_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_ambient_env(monkeypatch)
    env_file = _write_env(tmp_path, FULL_ENV)

    settings = Settings(_env_file=env_file)

    assert (
        settings.database_url
        == "postgresql+asyncpg://sentinel:sentinel@sentinel-host:5432/sentinel"
    )
    assert settings.ollama_base_url == "http://sentinel-ollama:11434"
    assert settings.ollama_model == "sentinel-model"
    assert settings.smtp_host == "smtp.sentinel.test"
    assert settings.smtp_port == 2525
    assert settings.smtp_username == "sentinel-user"
    assert settings.smtp_password == "sentinel-pass"
    assert settings.smtp_from_email == "sentinel@sentinel.test"
    assert settings.sjctl_campaign == "sentinel-campaign"
    assert settings.app_env == "sentinel-env"
    assert settings.log_level == "DEBUG"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 9000
    assert settings.cors_allow_origin == "http://sentinel-frontend.test"


def test_settings_applies_defaults_when_optional_fields_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_ambient_env(monkeypatch)
    env_file = _write_env(tmp_path, MINIMAL_ENV)

    settings = Settings(_env_file=env_file)

    assert settings.smtp_port == 587
    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.api_host == "0.0.0.0"
    assert settings.api_port == 8000
    assert settings.sjctl_campaign == "recruflow"
    assert settings.cors_allow_origin == "http://localhost:5173"


def test_settings_raises_when_required_field_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_ambient_env(monkeypatch)
    env_file = _write_env(
        tmp_path, "OLLAMA_BASE_URL=http://localhost:11434\nOLLAMA_MODEL=llama3.3:70b\n"
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/x")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.3:70b")
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()
