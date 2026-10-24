from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET_MARKER = "dev-only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "foodagent-api"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://foodagent:foodagent@db:5432/foodagent"
    jwt_secret: str = "dev-only-jwt-secret-change-me-0123456789"
    jwt_refresh_secret: str = "dev-only-refresh-secret-change-me-0123456789"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cors_origins: str = "http://localhost:3000"
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 10
    llm_api_key: str = ""
    rate_limit_login_per_minute: int = 10
    bcrypt_rounds: int = 12
    simulator_enabled: bool = False
    simulator_interval_seconds: int = 90
    worker_interval_seconds: int = 30

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_production_safe(self) -> None:
        if self.environment == "production":
            for name in ("jwt_secret", "jwt_refresh_secret"):
                value = getattr(self, name)
                if _DEV_SECRET_MARKER in value or len(value) < 32:
                    raise RuntimeError(f"{name} must be set to a strong, unique secret in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
