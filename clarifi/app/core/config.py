from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    base_url: str = Field("https://apisandbox.openbankproject.com", alias="BASE_URL")
    consumer_key: str = Field("", alias="CONSUMER_KEY")
    consumer_secret: str = Field("", alias="CONSUMER_SECRET")
    consumer_id: str = Field("", alias="CONSUMER_ID")
    obp_username: str = Field("", alias="OBP_USERNAME")
    obp_password: str = Field("", alias="OBP_PASSWORD")
    obp_bank_id: str = Field("", alias="OBP_BANK_ID")
    obp_account_id: str = Field("", alias="OBP_ACCOUNT_ID")
    obp_view_id: str = Field("owner", alias="OBP_VIEW_ID")
    obp_api_version: str = Field("v5.1.0", alias="OBP_API_VERSION")
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field("openrouter/free", alias="OPENROUTER_MODEL")
    openrouter_fallback_models: str = Field("", alias="OPENROUTER_FALLBACK_MODELS")
    mongo_uri: str = Field("", alias="MONGO_URI")
    mongo_db: str = Field("clarifi", alias="MONGO_DB")
    jwt_secret: str = Field("", alias="JWT_SECRET")
    jwt_expires_minutes: int = Field(60, alias="JWT_EXPIRES_MINUTES", gt=0)
    encryption_key: str = Field("", alias="ENCRYPTION_KEY")
    cors_origins: str = Field("*", alias="CORS_ORIGINS")
    tavily_api_key: str = Field("", alias="TAVILY_API_KEY")
    per_txn_limit: float = Field(50000, alias="PER_TXN_LIMIT", gt=0)
    display_currency: str = Field("", alias="DISPLAY_CURRENCY")
    environment: str = Field("development", alias="ENVIRONMENT")
    request_body_limit: int = 1_048_576

    @field_validator("base_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def fallback_models(self) -> list[str]:
        return [x.strip() for x in self.openrouter_fallback_models.split(",") if x.strip()]

    def missing_required(self) -> list[str]:
        required = {
            "CONSUMER_KEY": self.consumer_key,
            "OBP_USERNAME": self.obp_username,
            "OBP_PASSWORD": self.obp_password,
            "OBP_BANK_ID": self.obp_bank_id,
            "OBP_ACCOUNT_ID": self.obp_account_id,
            "OPENROUTER_API_KEY": self.openrouter_api_key,
            "MONGO_URI": self.mongo_uri,
            "JWT_SECRET": self.jwt_secret,
            "ENCRYPTION_KEY": self.encryption_key,
        }
        return [key for key, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()

