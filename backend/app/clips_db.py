"""
Second database: the pseudonymised audio clip index.

Deliberately holds no user id, session id, email or event time. The only link back to
a person is cough_events.clip_anon_id in the main database, so someone with access to
the clips database alone (or a leaked copy of it) cannot tell whose clip is whose.
The audio itself is not in either database: it sits encrypted on disk under
settings.clips_dir, named by anon_id.
"""
from datetime import datetime
from sqlalchemy import DateTime, Float, Integer, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import get_settings

settings = get_settings()


class ClipsBase(DeclarativeBase):
    pass


class AudioClip(ClipsBase):
    __tablename__ = "audio_clips"

    # Random UUID, not derived from anything about the user or event.
    anon_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Model score, kept so clips can be sampled for review without touching the main DB.
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


clips_engine = (
    create_engine(settings.clips_database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    if settings.clips_database_url else None
)
ClipsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=clips_engine)


def get_clips_db():
    if clips_engine is None:
        yield None
        return
    db = ClipsSessionLocal()
    try:
        yield db
    finally:
        db.close()
