from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    ollama_base_url: str
    ollama_model: str
    matcher_ollama_model: str
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    solid_jobs_campaign: str = "recruflow"
    batch_scoring_limit: int = 50
    scoring_max_concurrency: int = 5
    scoring_job_interval_seconds: int = 60
    detail_retry_job_interval_seconds: int = 300
    detail_retry_min_age_seconds: int = 1800
    detail_retry_max_attempts: int = 5
    app_env: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allow_origin: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
