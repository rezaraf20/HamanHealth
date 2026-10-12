from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import AwareDatetime, BaseModel, EmailStr, Field, field_validator, model_validator


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
    avatarUrl: str | None = None
    createdAt: datetime | None = None

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
            createdAt=user.created_at,
            avatarInitials=initials,
            avatarUrl=user.avatar,
        )


# ── Cough events (batch upload from device) ───────────────────────────────────

EventType = Literal["cough", "sneeze", "snore"]
SubjectLabel = Literal["subject", "other", "unknown"]
UserLabel = Literal["subject", "other", "not_an_event"]


class CoughEventIn(BaseModel):
    """One detected event. All timestamps are absolute, timezone-aware ISO 8601
    (e.g. "2026-10-10T01:23:45.678Z"); millisecond precision is kept."""
    timestamp: AwareDatetime                       # event start
    confidence: float | None = Field(None, ge=0, le=1)   # peak model score
    clip_anon_id: str | None = None           # ignored; set by the clip upload endpoint

    # Everything below is optional so older clients keep working.
    device_event_id: str | None = Field(None, max_length=64)
    event_type: EventType = "cough"
    ended_at: AwareDatetime | None = None
    peak_at: AwareDatetime | None = None
    mean_score: float | None = Field(None, ge=0, le=1)
    peak_db: float | None = None              # magnitude, dBFS
    snr_db: float | None = None
    bout_id: int | None = None
    subject_label: SubjectLabel | None = None
    subject_confidence: float | None = Field(None, ge=0, le=1)
    user_label: UserLabel | None = None
    has_device_clip: bool | None = None

    @model_validator(mode="after")
    def _times_in_order(self):
        if self.ended_at and self.ended_at < self.timestamp:
            raise ValueError("ended_at is before timestamp")
        return self


class SnoreEpisodeIn(BaseModel):
    started_at: AwareDatetime
    ended_at: AwareDatetime
    snore_count: int = Field(ge=0)
    mean_intensity_db: float | None = None


class SessionUploadRequest(BaseModel):
    """Sent by the app when a session ends (or on periodic sync).

    Safe to send repeatedly for the same device_session_id: events are matched on
    device_event_id, new ones are added and labels on known ones are updated.
    """
    device_session_id: str = Field(max_length=64)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    sensitivity: str | None = None
    events: list[CoughEventIn] = Field(default=[], max_length=5000)
    note: str | None = None

    # Recording context from the on-device module (all optional).
    status: Literal["running", "complete", "interrupted"] | None = None
    timezone: str | None = Field(None, max_length=64)   # IANA, e.g. "Europe/Amsterdam"
    device_model: str | None = Field(None, max_length=128)
    app_version: str | None = Field(None, max_length=32)
    audio_source: str | None = Field(None, max_length=64)
    noise_floor_db: float | None = None
    mic_gap_ms: int | None = Field(None, ge=0)
    frames_seen: int | None = Field(None, ge=0)
    frames_inferred: int | None = Field(None, ge=0)
    detector_config: dict[str, Any] | None = None
    snore_episodes: list[SnoreEpisodeIn] = Field(default=[], max_length=500)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {v!r}")
        return v


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
