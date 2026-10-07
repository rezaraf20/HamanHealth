"""
Consent API — stores per-user data-processing consent flags.
Consent is stored in-memory keyed by user_id (resets on container restart).
For production, persist to the DB users table or a separate consent table.

Endpoints:
  GET  /api/consent   — get current user's consent state
  PUT  /api/consent   — update current user's consent state
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import CurrentUser

router = APIRouter(prefix="/api/consent", tags=["consent"])

# In-memory store: {user_id: ConsentState}
_consent_store: dict[int, dict] = {}


class ConsentState(BaseModel):
    coughTracking: bool = False
    healthTrends: bool = False
    recordsProcessing: bool = False
    productAnalytics: bool = False
    acceptedAt: str | None = None


@router.get("", response_model=ConsentState)
def get_consent(current_user: CurrentUser):
    data = _consent_store.get(current_user.id)
    if data is None:
        return ConsentState()
    return ConsentState(**data)


@router.put("", response_model=ConsentState)
def update_consent(body: ConsentState, current_user: CurrentUser):
    existing = _consent_store.get(current_user.id, {})
    updated = {**existing, **body.model_dump(exclude_none=True)}
    if updated.get("acceptedAt") is None:
        updated["acceptedAt"] = datetime.now(timezone.utc).isoformat()
    _consent_store[current_user.id] = updated
    return ConsentState(**updated)
