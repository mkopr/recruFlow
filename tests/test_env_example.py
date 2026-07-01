from pathlib import Path

REQUIRED_KEYS = [
    "DATABASE_URL",
    "OLLAMA_BASE_URL",
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SJCTL_CAMPAIGN",
]


def test_env_example_documents_required_keys() -> None:
    env_example = Path(__file__).resolve().parents[1] / ".env.example"
    content = env_example.read_text()
    for key in REQUIRED_KEYS:
        assert f"{key}=" in content, f"{key} is missing from .env.example"
