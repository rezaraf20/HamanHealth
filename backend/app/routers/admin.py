"""
Admin API — requires is_admin=True on the User row, plus the X-Admin-Secret header
matching settings.admin_secret for an extra layer of defense.

Endpoints:
  GET  /api/admin/users           — list all users with usage stats
  GET  /api/admin/users/{id}      — single user detail
  PUT  /api/admin/users/{id}      — update is_active / is_admin
  GET  /api/admin/stats           — platform-wide aggregates
  GET  /api/admin/config          — current app config (theme colors, logo URL)
  PUT  /api/admin/config          — update app config
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..auth import CurrentUser
from ..config import get_settings
from ..database import get_db
from ..models import User, CoughSession, CoughEvent, HealthObservation, UserConsent
from .records import HealthRecord

settings = get_settings()
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Auth helper ──────────────────────────────────────────────────────────────

def require_admin(
    current_user: CurrentUser,
    x_admin_secret: str | None = Header(default=None),
):
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid admin secret")
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


AdminUser = Depends(require_admin)


# ── Schemas ──────────────────────────────────────────────────────────────────

class UserSummary(BaseModel):
    id: int
    email: str
    name: str | None
    is_active: bool
    is_admin: bool
    created_at: datetime
    total_sessions: int
    total_coughs: int
    last_session_at: datetime | None
    # What else is stored for this user
    total_records: int = 0
    total_readings: int = 0
    consent_accepted_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    name: str | None = None


class PlatformStats(BaseModel):
    total_users: int
    active_users: int
    total_sessions: int
    total_coughs: int
    users_last_30_days: int
    sessions_last_30_days: int


class AppConfig(BaseModel):
    """Mutable app-wide settings stored in the DB config table (JSON blob)."""
    primary_color: str = "#1a7a5e"
    secondary_color: str = "#e8f5f0"
    logo_url: str = "/haman-logo.png"
    logo_white_url: str = "/haman-logo-white.png"
    app_name: str = "Haman Health"
    tagline: str = "Sleep smarter, breathe better."
    support_email: str = "support@hamanhealth.com"


# ── In-memory config store (persists across requests, resets on restart) ─────
# For production: store in a DB table or a JSON file on disk.
_app_config = AppConfig()


# ── Endpoints ────────────────────────────────────────────────────────────────

def _summarize(db: Session, u: User) -> UserSummary:
    def count(column) -> int:
        return db.query(func.count()).filter(column == u.id).scalar() or 0

    total_coughs, last_session = (
        db.query(func.sum(CoughSession.event_count), func.max(CoughSession.started_at))
        .filter(CoughSession.user_id == u.id)
        .one()
    )
    return UserSummary(
        id=u.id,
        email=u.email,
        name=u.name,
        is_active=u.is_active,
        is_admin=u.is_admin,
        created_at=u.created_at,
        total_sessions=count(CoughSession.user_id),
        total_coughs=total_coughs or 0,
        last_session_at=last_session,
        total_records=count(HealthRecord.user_id),
        total_readings=count(HealthObservation.user_id),
        consent_accepted_at=db.query(UserConsent.accepted_at).filter(UserConsent.user_id == u.id).scalar(),
    )


@router.get("/users", response_model=list[UserSummary])
def list_users(
    limit: int = 100,
    offset: int = 0,
    _admin=AdminUser,
    db: Session = Depends(get_db),
):
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_summarize(db, u) for u in users]


@router.get("/users/{user_id}", response_model=UserSummary)
def get_user(user_id: int, _admin=AdminUser, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return _summarize(db, u)


@router.put("/users/{user_id}", response_model=UserSummary)
def update_user(user_id: int, body: UserUpdateRequest, _admin=AdminUser, db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.is_admin is not None:
        u.is_admin = body.is_admin
    if body.name is not None:
        u.name = body.name
    db.commit()
    db.refresh(u)
    return get_user(user_id, _admin, db)


@router.get("/stats", response_model=PlatformStats)
def platform_stats(_admin=AdminUser, db: Session = Depends(get_db)):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    thirty_ago = now - timedelta(days=30)

    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
    total_sessions = db.query(func.count(CoughSession.id)).scalar() or 0
    total_coughs = db.query(func.sum(CoughSession.event_count)).scalar() or 0
    users_last_30 = db.query(func.count(User.id)).filter(User.created_at >= thirty_ago).scalar() or 0
    sessions_last_30 = db.query(func.count(CoughSession.id)).filter(CoughSession.started_at >= thirty_ago).scalar() or 0

    return PlatformStats(
        total_users=total_users,
        active_users=active_users,
        total_sessions=total_sessions,
        total_coughs=int(total_coughs or 0),
        users_last_30_days=users_last_30,
        sessions_last_30_days=sessions_last_30,
    )


@router.get("/config", response_model=AppConfig)
def get_config(_admin=AdminUser):
    return _app_config


@router.put("/config", response_model=AppConfig)
def update_config(body: AppConfig, _admin=AdminUser):
    global _app_config
    _app_config = body
    return _app_config
