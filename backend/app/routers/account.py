"""
Account management endpoints:
  GET  /api/account/sessions      – active login sessions
  DELETE /api/account/sessions/{id} – revoke a session
  GET  /api/account/notifications – notification preferences
  PUT  /api/account/notifications – update preferences
  GET  /api/account/devices       – connected devices
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db

router = APIRouter(prefix="/api/account", tags=["account"])


# ── Login sessions ─────────────────────────────────────────────────────────────

class ActiveLoginSession(BaseModel):
    id: str
    device: str
    location: str
    lastActive: str
    current: bool


@router.get("/sessions", response_model=list[ActiveLoginSession])
def list_login_sessions(current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """
    Returns the user's active login sessions.
    Currently returns a single entry representing the current session.
    A proper implementation would store token metadata (device, IP, created_at) in the DB.
    """
    return [
        ActiveLoginSession(
            id="current",
            device="Web browser",
            location="—",
            lastActive=current_user.created_at.isoformat(),
            current=True,
        )
    ]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_login_session(session_id: str, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Revoke a login session. Stub — no-op until token table exists."""
    return None


# ── Notification preferences ───────────────────────────────────────────────────

class NotificationPrefs(BaseModel):
    morningSummary: bool = True
    sessionReminder: bool = True
    medicationReminder: bool = False
    weeklyTrends: bool = True
    productUpdates: bool = False


@router.get("/notifications", response_model=NotificationPrefs)
def get_notifications(current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Return notification preferences. Returns defaults until a prefs table is added."""
    return NotificationPrefs()


@router.put("/notifications", response_model=NotificationPrefs)
def update_notifications(prefs: NotificationPrefs, current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Update notification preferences. Stub — accepts and echoes back until prefs table exists."""
    return prefs


# ── Devices ────────────────────────────────────────────────────────────────────

class Device(BaseModel):
    id: str
    name: str
    kind: str
    status: str  # "connected" | "available"


@router.get("/devices", response_model=list[Device])
def list_devices(current_user: CurrentUser = ..., db: Session = Depends(get_db)):
    """Return connected / available devices. Stub until device pairing is implemented."""
    return [
        Device(id="d1", name="Android app", kind="On-device cough detection", status="connected"),
        Device(id="d2", name="Smart scale", kind="Weight", status="available"),
        Device(id="d3", name="Activity tracker", kind="Steps & sleep", status="available"),
    ]
