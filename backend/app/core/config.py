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
    # Gemini (server-side only; the key is never sent to the browser)
    gemini_api_key: str = ""
    gemini_model: str = ""  # set to a Flash model ID available to your key; gemini-3.1-flash-lite is the tested default
    gemini_timeout_seconds: int = 25
    gemini_max_retries: int = 2  # only for transient upstream failures (5xx / unavailable), never for quota or auth errors
    ai_max_message_chars: int = 800
    rate_limit_ai_per_minute: int = 12
    # Onboarding / account security
    first_admin_setup_token: str = ""  # if set, a create-organisation request presenting it is activated immediately; otherwise it waits for platform approval
    demo_login_enabled: bool = True  # honoured only outside production
    invitation_expiry_days: int = 7
    app_url: str = "http://localhost:3000"  # used to build invitation links
    rate_limit_register_per_minute: int = 5
    max_failed_logins: int = 8  # per email within the window below -> temporary lock
    failed_login_window_minutes: int = 15

    @property
    def demo_enabled(self) -> bool:
        return self.demo_login_enabled and self.environment != "production"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def assert_production_safe(self) -> None:
        if self.environment == "production":
            for name in ("jwt_secret", "jwt_refresh_secret"):
                value = getattr(self, name)
                if _DEV_SECRET_MARKER in value or len(value) < 32:
                    raise RuntimeError(f"{name} must be set to a strong, unique secret in production")
            if self.first_admin_setup_token and len(self.first_admin_setup_token) < 24:
                raise RuntimeError("first_admin_setup_token must be at least 24 characters in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
