"""
Audio clip storage: validation, encryption at rest, retention and deletion.

What this module guarantees (see docs/COUGH_DATA.md):
  - only short clips: a WAV longer than settings.clip_max_seconds is rejected, so a
    full-night recording cannot be uploaded through this path;
  - encrypted on disk, named by a random id, indexed in a database with no user ids;
  - deleted after settings.clip_retention_days, or when the user deletes them.
Clips are on by default; a user who switches audioClips off gets no new uploads.

Every stored clip is also measured right away (services/acoustic_features.py).
"""
import io
import os
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..clips_db import AudioClip
from ..config import get_settings
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import CoughEvent, CoughEventFeatures, CoughSession
from . import acoustic_features

settings = get_settings()

MAX_UPLOAD_BYTES = 1_000_000  # a 5 s, 48 kHz, 16-bit mono WAV is ~480 KB


class ClipRejected(ValueError):
    pass


@dataclass
class WavInfo:
    sample_rate: int
    duration_ms: int


def inspect_wav(data: bytes) -> WavInfo:
    """Accept only short mono 16-bit PCM WAV. Parsing the header (rather than trusting
    the content type) is what makes the length limit real."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ClipRejected("clip too large")
    try:
        with wave.open(io.BytesIO(data)) as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError) as e:
        raise ClipRejected(f"not a PCM WAV file: {e}")
    if channels != 1 or width != 2:
        raise ClipRejected("clip must be mono 16-bit PCM")
    if not 8_000 <= rate <= 48_000:
        raise ClipRejected("unsupported sample rate")
    duration_ms = frames * 1000 // rate
    if duration_ms <= 0 or duration_ms > settings.clip_max_seconds * 1000:
        raise ClipRejected(f"clip must be at most {settings.clip_max_seconds:g} s")
    return WavInfo(sample_rate=rate, duration_ms=duration_ms)


def _fernet() -> Fernet:
    return Fernet(settings.clips_key().encode())


def _path_for(anon_id: str) -> str:
    # Two-level fan-out keeps any one directory small at scale.
    return os.path.join(settings.clips_dir, anon_id[:2], anon_id[2:4], f"{anon_id}.bin")


def save_features(db: Session, event: CoughEvent, wav: bytes) -> bool:
    """Measure the clip and upsert this method's row. False if nothing to measure.
    Does not commit."""
    if event.clip_started_at is None:
        return False
    f = acoustic_features.compute(wav, event.clip_started_at, event.timestamp, event.ended_at)
    if f is None:
        return False
    stmt = pg_insert(CoughEventFeatures).values(
        event_id=event.id, method=acoustic_features.METHOD, **f.as_columns())
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_cough_event_features_event_method",
        set_={**{k: stmt.excluded[k] for k in f.as_columns()}, "computed_at": func.now()},
    ))
    return True


def store_clip(db: Session, clips_db: Session, event: CoughEvent, data: bytes, info: WavInfo,
               clip_started_at: datetime | None = None) -> str:
    anon_id = uuid.uuid4().hex
    path = _path_for(anon_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(_fernet().encrypt(data))
    os.replace(tmp, path)

    try:
        clips_db.add(AudioClip(
            anon_id=anon_id,
            event_type=event.event_type,
            duration_ms=info.duration_ms,
            sample_rate=info.sample_rate,
            size_bytes=len(data),
            confidence=event.confidence,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.clip_retention_days),
        ))
        clips_db.commit()
        event.clip_anon_id = anon_id
        event.clip_started_at = clip_started_at
        save_features(db, event, data)
        db.commit()
    except Exception:
        # Two databases can't share a transaction; undo what we can. Anything left
        # behind has no link from the main DB and is removed by purge_orphans().
        clips_db.rollback()
        _remove_file(anon_id)
        raise
    return anon_id


def read_clip(clips_db: Session, anon_id: str) -> bytes | None:
    clip = clips_db.get(AudioClip, anon_id)
    if clip is None or clip.expires_at <= datetime.now(timezone.utc):
        return None
    try:
        with open(_path_for(anon_id), "rb") as f:
            return _fernet().decrypt(f.read())
    except FileNotFoundError:
        return None


def delete_clips(db: Session, clips_db: Session | None, anon_ids: list[str]) -> int:
    """Delete clips everywhere: file, clip index, and the link on the event."""
    if not anon_ids:
        return 0
    for anon_id in anon_ids:
        _remove_file(anon_id)
    if clips_db is not None:
        for clip in clips_db.scalars(select(AudioClip).where(AudioClip.anon_id.in_(anon_ids))):
            clips_db.delete(clip)
        clips_db.commit()
    db.execute(update(CoughEvent).where(CoughEvent.clip_anon_id.in_(anon_ids)).values(clip_anon_id=None))
    db.commit()
    return len(anon_ids)


def clip_ids_for_user(db: Session, user_id: int) -> list[str]:
    return list(db.scalars(
        select(CoughEvent.clip_anon_id)
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.user_id == user_id, CoughEvent.clip_anon_id.is_not(None))
    ))


def delete_user_clips(db: Session, clips_db: Session | None, user_id: int) -> int:
    """For consent withdrawal and account deletion. Must run BEFORE the user's rows
    are deleted from the main DB — afterwards nothing links the clips to them."""
    return delete_clips(db, clips_db, clip_ids_for_user(db, user_id))


def purge_expired(db: Session, clips_db: Session) -> int:
    now = datetime.now(timezone.utc)
    ids = list(clips_db.scalars(select(AudioClip.anon_id).where(AudioClip.expires_at <= now)))
    return delete_clips(db, clips_db, ids)


def purge_orphans(db: Session, clips_db: Session, older_than: timedelta = timedelta(days=1)) -> int:
    """Clips no event points to — left by a failed upload or a deleted account."""
    cutoff = datetime.now(timezone.utc) - older_than
    candidates = list(clips_db.scalars(select(AudioClip.anon_id).where(AudioClip.created_at <= cutoff)))
    if not candidates:
        return 0
    linked = set(db.scalars(select(CoughEvent.clip_anon_id).where(CoughEvent.clip_anon_id.in_(candidates))))
    return delete_clips(db, clips_db, [a for a in candidates if a not in linked])


def _remove_file(anon_id: str) -> None:
    try:
        os.remove(_path_for(anon_id))
    except FileNotFoundError:
        pass
