from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./resolveai.db"
    auth_provider: str = "local"
    ai_provider: str = "mock"
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = ""
    cors_origins: str = "http://localhost:3000"
    max_turn_attempts: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def validate_mode(self) -> None:
        if self.app_env in {"production", "cloud"} and self.auth_provider == "local":
            raise RuntimeError("AUTH_PROVIDER=local is forbidden outside development/test")
        if self.ai_provider not in {"mock", "bedrock"}:
            raise RuntimeError("AI_PROVIDER must be mock or bedrock")
        if self.ai_provider == "bedrock" and not self.bedrock_model_id:
            raise RuntimeError("BEDROCK_MODEL_ID is required when AI_PROVIDER=bedrock")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_mode()
    return settings
