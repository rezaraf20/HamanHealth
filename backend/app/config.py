import logging
import os

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
    # Separate database holding the clip index (no user ids). Clips are on whenever
    # this is set; docker-compose sets it by default.
    clips_database_url: str | None = None
    # Fernet key that encrypts every clip file at rest. If unset, a key is generated
    # once and kept in clips_key_file (a different volume from the clips themselves).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    clips_encryption_key: str | None = None
    clips_key_file: str = "/var/haman/keys/clips.key"
    # Upper bounds that keep a clip a snippet, not a recording.
    clip_max_seconds: float = 5.0
    clip_max_per_session: int = 500

    @property
    def clips_enabled(self) -> bool:
        return bool(self.clips_database_url)

    def clips_key(self) -> str:
        if self.clips_encryption_key:
            return self.clips_encryption_key
        try:
            with open(self.clips_key_file) as f:
                return f.read().strip()
        except FileNotFoundError:
            pass
        from cryptography.fernet import Fernet
        os.makedirs(os.path.dirname(self.clips_key_file), exist_ok=True)
        key = Fernet.generate_key().decode()
        # O_EXCL: if two workers race, exactly one key wins and both read it back.
        try:
            fd = os.open(self.clips_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
            logging.getLogger(__name__).warning(
                "Generated a new clip encryption key at %s. Back it up: without it the "
                "stored clips cannot be decrypted.", self.clips_key_file)
        except FileExistsError:
            pass
        with open(self.clips_key_file) as f:
            return f.read().strip()

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
