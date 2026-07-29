from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/shortener.db"
    base_redirect_url: str = "http://localhost:8000"
    default_alias_length: int = 7
    default_expiry_days: int | None = None

    redis_url: str | None = None

    # 0 disables the check entirely. Defaults are deliberately asymmetric:
    # creating a link is a write with lasting effect (worth limiting
    # tightly against abuse/enumeration), following one is a read most
    # legitimate traffic depends on.
    rate_limit_shorten_per_minute: int = 20
    rate_limit_redirect_per_minute: int = 120

    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"

    auto_approve: bool = False

    audit_log_path: str = "./audit_log.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
