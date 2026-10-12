"""
Account management endpoints:
  GET  /api/account/sessions      – active login sessions
  DELETE /api/account/sessions/{id} – revoke a session
  GET  /api/account/notifications – notification preferences
  PUT  /api/account/notifications – update preferences
  GET  /api/account/devices       – connected devices
  PATCH  /api/account/profile     – update display name
  PUT    /api/account/avatar      – set profile photo
  DELETE /api/account/avatar      – remove profile photo
"""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..schemas import UserOut

router = APIRouter(prefix="/api/account", tags=["account"])


# ── Profile ────────────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    # Accepted so the language page's call succeeds; not stored (no column yet).
    locale: str | None = None


@router.patch("/profile", response_model=UserOut)
def update_profile(body: ProfileUpdate, current_user: CurrentUser, db: Session = Depends(get_db)):
    if body.name is not None:
        current_user.name = body.name.strip()
        db.commit()
        db.refresh(current_user)
    return UserOut.from_orm_with_extras(current_user)


# The web app center-crops and resizes to 256px before upload, so real avatars are
# ~20 KB. The cap only has to stop someone storing arbitrary blobs in the users table.
MAX_AVATAR_BYTES = 200 * 1024
# data: URL prefix -> leading bytes the decoded image must start with
_AVATAR_FORMATS = {
    "data:image/jpeg;base64,": b"\xff\xd8\xff",
    "data:image/png;base64,": b"\x89PNG\r\n\x1a\n",
    "data:image/webp;base64,": b"RIFF",
}


class AvatarUpdate(BaseModel):
    dataUrl: str = Field(max_length=MAX_AVATAR_BYTES * 2)


@router.put("/avatar", response_model=UserOut)
def set_avatar(body: AvatarUpdate, current_user: CurrentUser, db: Session = Depends(get_db)):
    prefix = next((p for p in _AVATAR_FORMATS if body.dataUrl.startswith(p)), None)
    if prefix is None:
        raise HTTPException(status_code=400, detail="Avatar must be a JPEG, PNG or WebP image")
    try:
        raw = base64.b64decode(body.dataUrl[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Avatar image is not valid base64")
    if not raw.startswith(_AVATAR_FORMATS[prefix]):
        raise HTTPException(status_code=400, detail="Avatar content does not match its image type")
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="Avatar image is too large (max 200 KB)")
    current_user.avatar = body.dataUrl
    db.commit()
    db.refresh(current_user)
    return UserOut.from_orm_with_extras(current_user)


@router.delete("/avatar", response_model=UserOut)
def remove_avatar(current_user: CurrentUser, db: Session = Depends(get_db)):
    current_user.avatar = None
    db.commit()
    db.refresh(current_user)
    return UserOut.from_orm_with_extras(current_user)


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
