"""
Writing cough-module data into the platform database.

upsert_session stores a night uploaded by the phone, every event as its own row.
Repeatable: the phone can re-send the same night (retry, periodic sync, a label
changed) without creating duplicates.

Daily numbers (coughs per night, cough rate, ...) are not stored; the
daily_health_summary view calculates them from these rows, so they always reflect
the latest labels.
"""
from datetime import datetime, timezone as dt_timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CoughEvent, CoughSession, SnoreEpisode, User
from ..schemas import CoughEventIn, SessionUploadRequest

# Fields the phone may legitimately change after first upload (the user labels events
# the next morning; attribution is retrained). Everything else about an event is fixed.
_MUTABLE_EVENT_FIELDS = ("user_label", "subject_label", "subject_confidence", "has_device_clip")

_SESSION_CONTEXT_FIELDS = (
    "ended_at", "sensitivity", "note", "status", "timezone", "device_model", "app_version",
    "audio_source", "noise_floor_db", "mic_gap_ms", "frames_seen", "frames_inferred",
    "detector_config",
)


def upsert_session(db: Session, user: User, body: SessionUploadRequest) -> CoughSession:
    session = db.scalar(
        select(CoughSession).where(
            CoughSession.user_id == user.id,
            CoughSession.device_session_id == body.device_session_id,
        )
    )
    is_new = session is None
    if is_new:
        session = CoughSession(
            user_id=user.id,
            device_session_id=body.device_session_id,
            started_at=body.started_at,
            event_count=0,
        )
        db.add(session)

    # Only overwrite with values the phone actually sent; a partial re-sync must not
    # blank out what an earlier one stored.
    for field in _SESSION_CONTEXT_FIELDS:
        value = getattr(body, field)
        if value is not None:
            setattr(session, field, value)
    if body.status is not None:
        session.is_active = body.status == "running"
    session.synced_at = datetime.now(dt_timezone.utc)
    db.flush()

    _upsert_events(db, session, body.events, is_new)
    _upsert_episodes(db, session, body)
    db.flush()

    session.event_count = _counted_coughs(db, session.id)
    return session


def _upsert_events(db: Session, session: CoughSession, events: list[CoughEventIn], is_new: bool) -> None:
    keyed = [e for e in events if e.device_event_id]
    existing: dict[str, CoughEvent] = {}
    if keyed and not is_new:
        rows = db.scalars(
            select(CoughEvent).where(
                CoughEvent.session_id == session.id,
                CoughEvent.device_event_id.in_([e.device_event_id for e in keyed]),
            )
        )
        existing = {r.device_event_id: r for r in rows}

    seen: set[str] = set()
    for ev in events:
        if ev.device_event_id:
            if ev.device_event_id in seen:
                continue
            seen.add(ev.device_event_id)
            row = existing.get(ev.device_event_id)
            if row is not None:
                for field in _MUTABLE_EVENT_FIELDS:
                    value = getattr(ev, field)
                    if value is not None:
                        setattr(row, field, value)
                continue
        elif not is_new:
            # Legacy events carry no id, so a re-sync can't tell new from duplicate.
            # Same rule as before: they are accepted on first upload only.
            continue
        db.add(CoughEvent(
            session_id=session.id,
            timestamp=ev.timestamp,
            confidence=ev.confidence,
            device_event_id=ev.device_event_id,
            event_type=ev.event_type,
            ended_at=ev.ended_at,
            peak_at=ev.peak_at,
            mean_score=ev.mean_score,
            peak_db=ev.peak_db,
            snr_db=ev.snr_db,
            bout_id=ev.bout_id,
            subject_label=ev.subject_label,
            subject_confidence=ev.subject_confidence,
            user_label=ev.user_label,
            has_device_clip=ev.has_device_clip,
        ))


def _upsert_episodes(db: Session, session: CoughSession, body: SessionUploadRequest) -> None:
    if not body.snore_episodes:
        return
    known = set(db.scalars(
        select(SnoreEpisode.started_at).where(SnoreEpisode.session_id == session.id)
    ))
    for ep in body.snore_episodes:
        if ep.started_at in known:
            continue
        known.add(ep.started_at)
        db.add(SnoreEpisode(
            session_id=session.id,
            started_at=ep.started_at,
            ended_at=ep.ended_at,
            snore_count=ep.snore_count,
            mean_intensity_db=ep.mean_intensity_db,
        ))


def counts_for_user(event_type: str):
    """Events that count toward the user's own numbers: the right type, and not
    rejected by the user. The model's attribution guess is never used to drop one.
    The daily_health_summary view applies the same rule in SQL (migration 0002)."""
    return (
        (CoughEvent.event_type == event_type)
        & (CoughEvent.user_label.is_(None) | (CoughEvent.user_label == "subject"))
    )


def _counted_coughs(db: Session, session_id: int) -> int:
    return db.scalar(
        select(func.count(CoughEvent.id)).where(
            CoughEvent.session_id == session_id, counts_for_user("cough"))
    ) or 0
