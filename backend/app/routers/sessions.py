from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, cast, Date, text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..auth import CurrentUser
from ..database import get_db
from ..models import CoughSession, CoughEvent
from ..schemas import (
    SessionUploadRequest, SessionOut,
    DashboardSummary, DailyCount,
    NightSummary, HourlyPoint,
    WebDashboardData, DailyPoint, ChangeCard, DashboardAverages,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ---- Web app session models ----

class QuietHours(BaseModel):
    from_: str = "23:00"
    to: str = "07:00"

    class Config:
        populate_by_name = True
        fields = {"from_": "from"}


class StartSessionRequest(BaseModel):
    sensitivity: str = "medium"
    quietHours: QuietHours = QuietHours()


class NightSessionOut(BaseModel):
    id: str
    startedAt: str
    endedAt: Optional[str]
    status: str
    sensitivity: str
    quietHours: dict
    coughCount: int

    @classmethod
    def from_orm(cls, s: CoughSession):
        return cls(
            id=str(s.id),
            startedAt=s.started_at.isoformat(),
            endedAt=s.ended_at.isoformat() if s.ended_at else None,
            status="active" if s.is_active else "completed",
            sensitivity=s.sensitivity or "medium",
            quietHours={"from": "23:00", "to": "07:00"},
            coughCount=s.event_count,
        )


class CoughEventIn(BaseModel):
    session_id: str
    timestamp: str
    count: int


class PushEventsRequest(BaseModel):
    events: List[CoughEventIn]


# ---- Web app endpoints ----

@router.get("/current", response_model=Optional[NightSessionOut])
def get_current_session(current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Returns the active session for this user, or null."""
    s = (
        db.query(CoughSession)
        .filter(CoughSession.user_id == current_user.id, CoughSession.is_active == True)
        .order_by(CoughSession.started_at.desc())
        .first()
    )
    if not s:
        return None
    return NightSessionOut.from_orm(s)


@router.post("", response_model=NightSessionOut, status_code=status.HTTP_201_CREATED)
def start_session(body: StartSessionRequest, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Start a new night session. Ends any previously active session first."""
    # End any lingering active session
    db.query(CoughSession).filter(
        CoughSession.user_id == current_user.id,
        CoughSession.is_active == True,
    ).update({"is_active": False, "ended_at": datetime.now(timezone.utc)})

    s = CoughSession(
        user_id=current_user.id,
        device_session_id=f"web-{int(datetime.now().timestamp()*1000)}",
        started_at=datetime.now(timezone.utc),
        sensitivity=body.sensitivity,
        is_active=True,
        event_count=0,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return NightSessionOut.from_orm(s)


@router.post("/events")
def push_events(body: PushEventsRequest, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Accept cough events from the web app."""
    for ev in body.events:
        try:
            session_id = int(ev.session_id)
        except (ValueError, TypeError):
            continue
        s = db.get(CoughSession, session_id)
        if not s or s.user_id != current_user.id:
            continue
        ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
        for _ in range(max(1, ev.count)):
            db.add(CoughEvent(session_id=s.id, timestamp=ts, confidence=1.0))
        s.event_count = (s.event_count or 0) + ev.count
    db.commit()
    return {"ok": True}


@router.post("/{session_id}/end", response_model=NightSessionOut)
def end_session(session_id: int, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    s = db.get(CoughSession, session_id)
    if not s or s.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    s.is_active = False
    s.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return NightSessionOut.from_orm(s)


# ---- Sync endpoint (mobile app) ----

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


@router.get("/last/summary", response_model=NightSummary)
def last_summary(current_user: CurrentUser, db: Session = Depends(get_db)):
    """
    Summary of the most recent completed session.
    Used by the home screen and dashboard widget.
    """
    last = (
        db.query(CoughSession)
        .filter(CoughSession.user_id == current_user.id)
        .order_by(CoughSession.started_at.desc())
        .first()
    )
    if not last:
        raise HTTPException(status_code=404, detail="No sessions found")

    # Build hourly breakdown from real events
    events = (
        db.query(CoughEvent)
        .filter(CoughEvent.session_id == last.id)
        .order_by(CoughEvent.timestamp)
        .all()
    )
    hourly_map: dict[str, int] = {}
    for ev in events:
        h = ev.timestamp.strftime("%H:00")
        hourly_map[h] = hourly_map.get(h, 0) + 1
    hourly = [HourlyPoint(hour=h, coughs=c) for h, c in sorted(hourly_map.items())]

    # 7-session rolling average for coughs
    recent = (
        db.query(CoughSession.event_count)
        .filter(CoughSession.user_id == current_user.id)
        .order_by(CoughSession.started_at.desc())
        .limit(8)
        .all()
    )
    prev = [r.event_count for r in recent[1:]] if len(recent) > 1 else []
    prev_avg = round(sum(prev) / len(prev), 1) if prev else float(last.event_count)

    # Sleep hours from session duration (fallback: 7.0)
    sleep_hours = 7.0
    if last.ended_at and last.started_at:
        diff = (last.ended_at - last.started_at).total_seconds() / 3600
        sleep_hours = round(min(diff, 12.0), 1)

    # Restfulness: simple heuristic — fewer coughs than average → higher score
    ratio = last.event_count / max(prev_avg, 1)
    restfulness = max(0, min(100, int(100 - (ratio - 1) * 40 + 10)))

    note = "Most cough events clustered in the early hours." if last.event_count > 0 else "No cough events recorded this session."

    return NightSummary(
        date=last.started_at.strftime("%Y-%m-%d"),
        coughs=last.event_count,
        coughsPrevAvg=prev_avg,
        sleepHours=sleep_hours,
        restfulness=restfulness,
        hourly=hourly,
        note=note,
    )


@router.get("/dashboard-summary", response_model=DashboardSummary)
def dashboard_summary(current_user: CurrentUser, db: Session = Depends(get_db)):
    """Internal dashboard summary (total counts + last 7 days)."""
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
