from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./recallops.db"
    trusted_proxy_token: str = "dev-proxy-token"
    draft_ttl_hours: int = 24
    rrf_k: int = 60
    extraction_mode: str = "model"
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = ""
    model_wire_api: str = "chat_completions"
    model_timeout_seconds: int = 90
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/%2F"
    redis_url: str = "redis://localhost:6379/0"
    model_quota_rate: float = 1.0
    model_quota_capacity: int = 5
    service_load_mode: str = "batch"
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECALLOPS_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

