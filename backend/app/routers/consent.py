"""
Consent API — stores per-user data-processing consent flags.
GET is public (returns defaults for unauthenticated users).
PUT requires a valid JWT.

Endpoints:
  GET  /api/consent   — get current user's consent state (or defaults)
  PUT  /api/consent   — update current user's consent state (auth required)
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from ..auth import CurrentUser
from ..config import get_settings

router = APIRouter(prefix="/api/consent", tags=["consent"])
_settings = get_settings()
_bearer = HTTPBearer(auto_error=False)

# In-memory store: {user_id: ConsentState dict}
_consent_store: dict[int, dict] = {}


class ConsentState(BaseModel):
    coughTracking: bool = False
    healthTrends: bool = False
    recordsProcessing: bool = False
    productAnalytics: bool = False
    acceptedAt: str | None = None


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


@router.get("", response_model=ConsentState)
def get_consent(user_id: int | None = Depends(_optional_user_id)):
    if user_id is None:
        return ConsentState()
    data = _consent_store.get(user_id)
    return ConsentState(**(data or {}))


@router.put("", response_model=ConsentState)
def update_consent(body: ConsentState, current_user: CurrentUser):
    existing = _consent_store.get(current_user.id, {})
    updated = {**existing, **body.model_dump(exclude_none=True)}
    if not updated.get("acceptedAt"):
        updated["acceptedAt"] = datetime.now(timezone.utc).isoformat()
    _consent_store[current_user.id] = updated
    return ConsentState(**updated)
