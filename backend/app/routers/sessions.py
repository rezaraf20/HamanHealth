from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, cast, Date, text
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..models import CoughSession, CoughEvent
from ..schemas import (
    SessionUploadRequest, SessionOut,
    DashboardSummary, DailyCount,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("/sync", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def sync_session(body: SessionUploadRequest, current_user: CurrentUser, db: Session = Depends(get_db)):
    """
    Called by the app (or background sync) when a session ends.
    Idempotent: if the device_session_id already exists for this user, skip duplicate.
    """
    existing = (
        db.query(CoughSession)
        .filter(
            CoughSession.user_id == current_user.id,
            CoughSession.device_session_id == body.device_session_id,
        )
        .first()
    )
    if existing:
        return existing

    session = CoughSession(
        user_id=current_user.id,
        device_session_id=body.device_session_id,
        started_at=body.started_at,
        ended_at=body.ended_at,
        sensitivity=body.sensitivity,
        event_count=len(body.events),
        note=body.note,
    )
    db.add(session)
    db.flush()  # get session.id

    for ev in body.events:
        db.add(CoughEvent(
            session_id=session.id,
            timestamp=ev.timestamp,
            confidence=ev.confidence,
            clip_anon_id=ev.clip_anon_id,
        ))

    db.commit()
    db.refresh(session)
    return session


@router.get("/", response_model=list[SessionOut])
def list_sessions(
    limit: int = 20,
    offset: int = 0,
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    return (
        db.query(CoughSession)
        .filter(CoughSession.user_id == current_user.id)
        .order_by(CoughSession.started_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(current_user: CurrentUser, db: Session = Depends(get_db)):
    total_sessions = (
        db.query(func.count(CoughSession.id))
        .filter(CoughSession.user_id == current_user.id)
        .scalar()
    ) or 0

    total_events = (
        db.query(func.sum(CoughSession.event_count))
        .filter(CoughSession.user_id == current_user.id)
        .scalar()
    ) or 0

    # Last 7 days daily counts
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        db.query(
            cast(CoughEvent.timestamp, Date).label("day"),
            func.count(CoughEvent.id).label("cnt"),
        )
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .filter(
            CoughSession.user_id == current_user.id,
            CoughEvent.timestamp >= seven_days_ago,
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    last_7_days = [DailyCount(date=str(r.day), count=r.cnt) for r in rows]

    last_session = (
        db.query(CoughSession)
        .filter(CoughSession.user_id == current_user.id)
        .order_by(CoughSession.started_at.desc())
        .first()
    )

    return DashboardSummary(
        total_sessions=total_sessions,
        total_events=total_events,
        last_7_days=last_7_days,
        last_session=last_session,
    )


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, current_user: CurrentUser, db: Session = Depends(get_db)):
    session = db.get(CoughSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
