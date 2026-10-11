"""
Consent API — stores per-user data-processing consent flags.
GET is public (returns defaults for unauthenticated users).
PUT requires a valid JWT to persist; without one it echoes the values back unsaved
(the onboarding screen can render before the account exists).

Endpoints:
  GET  /api/consent   — get current user's consent state (or defaults)
  PUT  /api/consent   — update current user's consent state (partial updates)

Stored in the user_consents table. audioClips is on unless the user switches it off;
switching it off stops new clip uploads (DELETE /api/clips removes stored ones).
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User, UserConsent

router = APIRouter(prefix="/api/consent", tags=["consent"])
_settings = get_settings()
_bearer = HTTPBearer(auto_error=False)


class ConsentState(BaseModel):
    coughTracking: bool = False
    healthTrends: bool = False
    recordsProcessing: bool = False
    productAnalytics: bool = False
    # Upload short audio clips of detected events. On by default.
    audioClips: bool = True
    acceptedAt: str | None = None


# API field → table column
_FIELDS = {
    "coughTracking": "cough_tracking",
    "healthTrends": "health_trends",
    "recordsProcessing": "records_processing",
    "productAnalytics": "product_analytics",
    "audioClips": "audio_clips",
}


def _optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> int | None:
    """Returns user_id if a valid JWT is present, otherwise None."""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, _settings.secret_key, algorithms=["HS256"])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None


def _to_state(row: UserConsent | None) -> ConsentState:
    if row is None:
        return ConsentState()
    return ConsentState(
        **{api: getattr(row, col) for api, col in _FIELDS.items()},
        acceptedAt=row.accepted_at.isoformat() if row.accepted_at else None,
    )


@router.get("", response_model=ConsentState)
def get_consent(user_id: int | None = Depends(_optional_user_id), db: Session = Depends(get_db)):
    if user_id is None:
        return ConsentState()
    return _to_state(db.get(UserConsent, user_id))


@router.put("", response_model=ConsentState)
def update_consent(
    body: ConsentState,
    user_id: int | None = Depends(_optional_user_id),
    db: Session = Depends(get_db),
):
    # Only fields the client actually sent. A client that doesn't know about a flag
    # (e.g. audioClips) must not reset it to False by omission.
    sent = body.model_dump(exclude_unset=True)

    if user_id is None or db.get(User, user_id) is None:
        return ConsentState(**{**ConsentState().model_dump(), **sent})

    row = db.get(UserConsent, user_id)
    if row is None:
        row = UserConsent(user_id=user_id, **{col: getattr(ConsentState(), api) for api, col in _FIELDS.items()})
        db.add(row)

    now = datetime.now(timezone.utc)
    for api, col in _FIELDS.items():
        if api in sent and getattr(row, col) != sent[api]:
            setattr(row, col, sent[api])
            if col == "audio_clips":
                row.audio_clips_changed_at = now
    if row.accepted_at is None:
        row.accepted_at = now
    db.commit()
    db.refresh(row)
    return _to_state(row)
