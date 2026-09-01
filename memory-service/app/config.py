from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./recallops.db"
    trusted_proxy_token: str = "dev-proxy-token"
    draft_ttl_hours: int = 24
    rrf_k: int = 60
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RECALLOPS_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

