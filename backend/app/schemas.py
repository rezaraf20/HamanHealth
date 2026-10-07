from datetime import datetime
from pydantic import BaseModel, EmailStr


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Matches the web app's Tokens type: { access, refresh }"""
    access: str
    # No real refresh token yet — we return the same token so the frontend
    # doesn't break. Upgrade to a proper refresh flow later.
    refresh: str
    token_type: str = "bearer"

    # Also expose requires2fa for the login flow
    requires2fa: bool = False


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None
    created_at: datetime
    # Fields expected by the web app
    locale: str = "en"
    twoFactorEnabled: bool = False
    avatarInitials: str = ""

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_extras(cls, user: "User") -> "UserOut":  # type: ignore[name-defined]
        name = user.name or ""
        initials = "".join(p[0].upper() for p in name.split() if p)[:2] or user.email[0].upper()
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
            avatarInitials=initials,
        )


# ── Cough events (batch upload from device) ───────────────────────────────────

class CoughEventIn(BaseModel):
    timestamp: datetime
    confidence: float | None = None
    clip_anon_id: str | None = None


class SessionUploadRequest(BaseModel):
    """Sent by the app when a session ends (or on periodic sync)."""
    device_session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    sensitivity: str | None = None
    events: list[CoughEventIn] = []
    note: str | None = None


class SessionOut(BaseModel):
    id: int
    device_session_id: str
    started_at: datetime
    ended_at: datetime | None
    sensitivity: str | None
    event_count: int
    synced_at: datetime
    note: str | None

    model_config = {"from_attributes": True}


# ── Dashboard (legacy internal) ───────────────────────────────────────────────

class DailyCount(BaseModel):
    date: str       # "2026-10-07"
    count: int


class DashboardSummary(BaseModel):
    total_sessions: int
    total_events: int
    last_7_days: list[DailyCount]
    last_session: SessionOut | None


# ── Web app API shapes ────────────────────────────────────────────────────────
# These match the TypeScript types in the companion app (src/lib/api.ts).

class HourlyPoint(BaseModel):
    hour: str       # "02:00"
    coughs: int


class NightSummary(BaseModel):
    """Response for GET /api/sessions/last/summary"""
    date: str                       # "2026-10-07"
    coughs: int
    coughsPrevAvg: float
    sleepHours: float
    restfulness: int                # 0–100
    hourly: list[HourlyPoint]
    note: str


class DailyPoint(BaseModel):
    """One data point in the dashboard chart."""
    date: str
    coughs: int
    sleepHours: float
    weight: float
    steps: int
    medsTaken: int
    medsPlanned: int


class ChangeCard(BaseModel):
    id: str
    metric: str
    title: str
    description: str
    direction: str          # "up" | "down" | "steady"
    deltaLabel: str
    since: str


class DashboardAverages(BaseModel):
    coughs: float
    weight: float
    steps: float
    sleepHours: float
    adherence: float


class WebDashboardData(BaseModel):
    """Response for GET /api/dashboard?range=N"""
    range: int
    points: list[DailyPoint]
    changes: list[ChangeCard]
    medications: list        # empty list — medications not yet tracked
    averages: DashboardAverages
