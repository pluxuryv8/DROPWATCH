from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_token: str = Field(alias="TELEGRAM_TOKEN")
    database_url: str = Field(default="sqlite+aiosqlite:///./dropwatch.db", alias="DATABASE_URL")

    default_timezone: str = Field(default="Europe/Moscow", alias="DEFAULT_TIMEZONE")
    default_task_interval_sec: int = Field(default=60, alias="DEFAULT_TASK_INTERVAL_SEC")
    scheduler_tick_sec: int = Field(default=30, alias="SCHEDULER_TICK_SEC")
    global_poll_interval_sec: int = Field(default=120, alias="GLOBAL_POLL_INTERVAL_SEC")
    aggregate_threshold: int = Field(default=3, alias="AGGREGATE_THRESHOLD")

    fetcher: str = Field(default="avito_search", alias="FETCHER")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    avito_proxy: str | None = Field(default=None, alias="AVITO_PROXY")
    avito_proxy_change_url: str | None = Field(default=None, alias="AVITO_PROXY_CHANGE_URL")
    avito_use_webdriver: bool = Field(default=True, alias="AVITO_USE_WEBDRIVER")
    avito_cookies_path: str = Field(default="./avito_cookies.json", alias="AVITO_COOKIES_PATH")
    avito_max_pages: int = Field(default=1, alias="AVITO_MAX_PAGES")
    avito_pause_sec: float = Field(default=2.0, alias="AVITO_PAUSE_SEC")
    avito_max_retries: int = Field(default=5, alias="AVITO_MAX_RETRIES")
    avito_request_timeout_sec: int = Field(default=20, alias="AVITO_REQUEST_TIMEOUT_SEC")
    avito_impersonate: str = Field(default="chrome", alias="AVITO_IMPERSONATE")
    avito_parse_views: bool = Field(default=False, alias="AVITO_PARSE_VIEWS")
    avito_views_delay_sec: float = Field(default=0.5, alias="AVITO_VIEWS_DELAY_SEC")
    avito_ignore_reserved: bool = Field(default=False, alias="AVITO_IGNORE_RESERVED")
    avito_ignore_promotion: bool = Field(default=False, alias="AVITO_IGNORE_PROMOTION")
    avito_max_age_sec: int = Field(default=0, alias="AVITO_MAX_AGE_SEC")
    avito_seller_blacklist: str | None = Field(default=None, alias="AVITO_SELLER_BLACKLIST")
    avito_keywords_whitelist: str | None = Field(default=None, alias="AVITO_KEYWORDS_WHITELIST")
    avito_keywords_blacklist: str | None = Field(default=None, alias="AVITO_KEYWORDS_BLACKLIST")
    avito_geo_filter: str | None = Field(default=None, alias="AVITO_GEO_FILTER")

    mock_data_path: str = Field(default="./mock_listings.json", alias="MOCK_DATA_PATH")

    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_BASE_URL")
    llm_timeout_sec: int = Field(default=15, alias="LLM_TIMEOUT_SEC")


settings = Settings()
