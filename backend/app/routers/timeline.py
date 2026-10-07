"""
Timeline API — GET /api/timeline
Returns a merged list of user events: sessions, records, medications, notes, devices.
Currently only sessions are stored; other kinds return empty unless added later.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..models import CoughSession

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("", response_model=list[dict])
def list_timeline(
    kinds: Optional[str] = Query(None, description="Comma-separated list of kinds to filter"),
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    """
    Returns timeline events for the current user.
    kinds param: session,record,medication,weight,note,device (comma-separated)
    """
    wanted = set(kinds.split(",")) if kinds else None

    events = []

    # Sessions
    if wanted is None or "session" in wanted:
        sessions = (
            db.query(CoughSession)
            .filter(CoughSession.user_id == current_user.id)
            .order_by(CoughSession.started_at.desc())
            .limit(50)
            .all()
        )
        for s in sessions:
            coughs = s.event_count or 0
            status = "active" if s.is_active else "completed"
            detail = f"{coughs} cough events · {status}"
            if s.ended_at and s.started_at:
                hrs = round((s.ended_at - s.started_at).total_seconds() / 3600, 1)
                detail += f" · {hrs}h"
            events.append({
                "id": f"session-{s.id}",
                "kind": "session",
                "at": s.started_at.isoformat(),
                "title": "Night session",
                "detail": detail,
            })

    # Other kinds (records, meds, weight, notes, devices) — not yet in DB
    # Return empty for those; frontend handles gracefully.

    # Sort by date desc
    events.sort(key=lambda e: e["at"], reverse=True)
    return events
