"""
Audio clips of detected events — short, encrypted, pseudonymised, auto-expiring.

  POST   /api/sessions/{session_id}/events/{device_event_id}/clip  – upload a WAV clip
  GET    /api/clips/{anon_id}                                      – play it back (owner only)
  GET    /api/clips/{anon_id}/features                             – measurements from the clip
  DELETE /api/clips/{anon_id}                                      – delete one (owner only)
  DELETE /api/clips                                                – delete all of the user's clips

On by default. Refused when the user switched audioClips off in /api/consent, or when
the server has no clips database configured.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import AwareDatetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..clips_db import get_clips_db
from ..config import get_settings
from ..database import get_db
from ..models import CoughEvent, CoughEventFeatures, CoughSession, UserConsent
from ..services import clip_store

# The phone cuts each clip starting this long before the event's strongest frame
# (PlatformContract.CLIP_PRE_ROLL_MS in the Android module).
DEVICE_CLIP_PRE_ROLL = timedelta(milliseconds=750)

router = APIRouter(prefix="/api", tags=["clips"])
settings = get_settings()


def _require_clips(clips_db: Session | None) -> Session:
    if not settings.clips_enabled or clips_db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Audio clips are not enabled")
    return clips_db


def _owned_event_for_clip(db: Session, user_id: int, anon_id: str) -> CoughEvent:
    ev = db.scalar(
        select(CoughEvent)
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughEvent.clip_anon_id == anon_id, CoughSession.user_id == user_id)
    )
    if ev is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return ev


@router.post("/sessions/{session_id}/events/{device_event_id}/clip", status_code=status.HTTP_201_CREATED)
async def upload_clip(
    session_id: int,
    device_event_id: str,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    # Absolute time of the clip's first sample. If omitted, derived from the event's
    # peak_at and the phone's fixed pre-roll.
    clip_started_at: AwareDatetime | None = Form(None),
    db: Session = Depends(get_db),
    clips_db: Session | None = Depends(get_clips_db),
):
    clips_db = _require_clips(clips_db)

    consent = db.get(UserConsent, current_user.id)
    if consent is not None and not consent.audio_clips:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Audio clips are switched off for this user")

    session = db.get(CoughSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    event = db.scalar(select(CoughEvent).where(
        CoughEvent.session_id == session_id, CoughEvent.device_event_id == device_event_id))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found — sync the session first")
    if event.clip_anon_id:
        return {"clip_anon_id": event.clip_anon_id}  # already uploaded; safe to retry

    stored = db.scalar(select(func.count(CoughEvent.id)).where(
        CoughEvent.session_id == session_id, CoughEvent.clip_anon_id.is_not(None))) or 0
    if stored >= settings.clip_max_per_session:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Clip limit for this session reached")

    data = await file.read(clip_store.MAX_UPLOAD_BYTES + 1)
    try:
        info = clip_store.inspect_wav(data)
    except clip_store.ClipRejected as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    if clip_started_at is None and event.peak_at is not None:
        clip_started_at = event.peak_at - DEVICE_CLIP_PRE_ROLL
    anon_id = clip_store.store_clip(db, clips_db, event, data, info, clip_started_at)
    return {"clip_anon_id": anon_id}


@router.get("/clips/{anon_id}")
def get_clip(
    anon_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    clips_db: Session | None = Depends(get_clips_db),
):
    clips_db = _require_clips(clips_db)
    _owned_event_for_clip(db, current_user.id, anon_id)
    audio = clip_store.read_clip(clips_db, anon_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Clip not found or expired")
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/clips/{anon_id}/features")
def get_clip_features(anon_id: str, current_user: CurrentUser, db: Session = Depends(get_db)):
    ev = _owned_event_for_clip(db, current_user.id, anon_id)
    rows = db.scalars(select(CoughEventFeatures).where(CoughEventFeatures.event_id == ev.id))
    return [
        {c.name: getattr(r, c.name) for c in CoughEventFeatures.__table__.columns if c.name not in ("id", "event_id")}
        for r in rows
    ]


@router.delete("/clips", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_clips(
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    clips_db: Session | None = Depends(get_clips_db),
):
    clip_store.delete_user_clips(db, clips_db, current_user.id)
    return None


@router.delete("/clips/{anon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_clip(
    anon_id: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    clips_db: Session | None = Depends(get_clips_db),
):
    _owned_event_for_clip(db, current_user.id, anon_id)
    clip_store.delete_clips(db, clips_db, [anon_id])
    return None
