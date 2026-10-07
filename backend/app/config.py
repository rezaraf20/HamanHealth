from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://haman:haman_pass@localhost:5432/hamanhealth"

    # JWT
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 30  # 30 days

    # CORS — web app origins
    cors_origins: list[str] = [
        "https://hamanhealth.com",
        "https://app.hamanhealth.com",
        "https://admin.hamanhealth.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "capacitor://localhost",
        "http://localhost",
    ]

    # Admin
    admin_secret: str = "CHANGE_ADMIN_SECRET"

    # Clip storage (pseudonymised audio, 90-day TTL)
    clips_dir: str = "/var/haman/clips"
    clip_retention_days: int = 90

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
