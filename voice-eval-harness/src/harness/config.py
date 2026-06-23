"""
Centralised settings loaded from environment variables / .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Platform credentials
    vapi_api_key: str = ""
    retell_api_key: str = ""
    openai_api_key: str = ""

    # Harness runtime
    harness_public_url: str = ""
    database_url: str = "sqlite:///./results.db"
    trials: int = 10
    rate_limit_rpm: int = 10

    # Webhook receiver port (used when running the harness server standalone)
    port: int = 8000


settings = Settings()
