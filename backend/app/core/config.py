from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    app_name: str = "Recall"
    environment: str = "development"  # development | production
    # PostgreSQL in production/Docker. SQLite is supported for quick local dev and tests.
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'recall.db').as_posix()}"

    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 60
    refresh_token_days: int = 30
    allow_registration: bool = True
    auto_migrate: bool = True  # run `alembic upgrade head` on startup (disable when migrating in the entrypoint)

    cors_origins: str = "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173"

    upload_dir: str = str(BACKEND_DIR / "uploads")
    max_upload_mb: int = 10
    max_video_mb: int = 1024  # uploaded lecture videos (stored via the storage module; use an external host for scale)

    # AI (server-side only; never sent to the browser)
    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    ai_max_tokens: int = 4096

    rate_limit_auth_per_min: int = 10
    rate_limit_ai_per_min: int = 20
    rate_limit_public_per_min: int = 120
    # OpenAI / ChatGPT (or any OpenAI-compatible API). Select with AI_PROVIDER=openai
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = "https://api.openai.com/v1"

    @field_validator("secret_key")
    @classmethod
    def _min_len(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.secret_key.startswith("dev-only"):
        raise RuntimeError("Refusing to start in production with the default SECRET_KEY")
    return s
