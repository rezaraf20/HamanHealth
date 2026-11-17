"""Admin security API: two-factor enrolment/login and the audit log.

  GET  /api/admin/2fa/status    — enrolled? required? is the token I hold still valid?
  POST /api/admin/2fa/setup     — start enrolment: returns the secret and an otpauth:// URI
  POST /api/admin/2fa/enable    — finish enrolment with a first code; returns a 2FA token
  POST /api/admin/2fa/verify    — exchange a code for a 2FA token (send as X-Admin-2FA)
  POST /api/admin/2fa/disable   — turn 2FA off (needs a current code)
  GET  /api/admin/audit         — the audit log, newest first

The enrolment endpoints use require_admin_basic (login + admin flag + shared secret): an
admin who has no 2FA yet must be able to reach them even when ADMIN_REQUIRE_2FA is on.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import AdminAuditLog, AdminTotp, User
from ..services import admin_security as sec
from .admin import AdminUser, require_admin_basic

settings = get_settings()
router = APIRouter(prefix="/api/admin", tags=["admin-security"])


class CodeBody(BaseModel):
    code: str


class TwoFactorStatus(BaseModel):
    enrolled: bool
    enrolment_pending: bool
    required: bool
    token_valid: bool


class SetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TokenResponse(BaseModel):
    token: str
    expires_in: int


def _check_code(db: Session, request: Request, admin: User, row: AdminTotp, code: str) -> None:
    """Validate a code against the row, with lockout and single use. Commits its own
    bookkeeping (failure counts, last used step) and raises on any problem."""
    if sec.is_locked(row):
        raise HTTPException(status_code=429, detail="Too many wrong codes. Try again later.")
    secret = sec.decrypt_secret(row.secret_enc)
    step = sec.match_step(secret, code, row.last_used_step) if secret else None
    if step is None:
        locked = sec.register_failure(row)
        sec.audit(db, admin, "2fa.locked" if locked else "2fa.failed", request)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid code")
    row.last_used_step = step
    row.failed_attempts = 0
    row.locked_until = None


@router.get("/2fa/status", response_model=TwoFactorStatus)
def status(admin: User = Depends(require_admin_basic), db: Session = Depends(get_db),
           x_admin_2fa: str | None = Header(default=None)):
    row = db.get(AdminTotp, admin.id)
    enrolled = row is not None and row.enabled_at is not None
    return TwoFactorStatus(
        enrolled=enrolled,
        enrolment_pending=row is not None and not enrolled,
        required=enrolled or settings.admin_require_2fa,
        token_valid=enrolled and sec.token_is_valid(x_admin_2fa, admin.id, row.enabled_at),
    )


@router.post("/2fa/setup", response_model=SetupResponse)
def setup(request: Request, admin: User = Depends(require_admin_basic), db: Session = Depends(get_db)):
    """Start (or restart) enrolment. Nothing is enforced until /enable succeeds, so an
    abandoned setup never locks the admin out."""
    row = db.get(AdminTotp, admin.id)
    if row is not None and row.enabled_at is not None:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    secret = sec.new_secret()
    if row is None:
        db.add(AdminTotp(user_id=admin.id, secret_enc=sec.encrypt_secret(secret)))
    else:
        row.secret_enc = sec.encrypt_secret(secret)
    sec.audit(db, admin, "2fa.setup_started", request)
    db.commit()
    return SetupResponse(secret=secret, otpauth_uri=sec.provisioning_uri(secret, admin.email))


@router.post("/2fa/enable", response_model=TokenResponse)
def enable(body: CodeBody, request: Request, admin: User = Depends(require_admin_basic),
           db: Session = Depends(get_db)):
    row = db.get(AdminTotp, admin.id)
    if row is None:
        raise HTTPException(status_code=409, detail="Start setup first")
    if row.enabled_at is not None:
        raise HTTPException(status_code=409, detail="2FA is already enabled")
    _check_code(db, request, admin, row, body.code)
    row.enabled_at = datetime.now(timezone.utc)
    sec.audit(db, admin, "2fa.enabled", request)
    db.commit()
    db.refresh(row)
    token, expires = sec.issue_2fa_token(admin.id, row.enabled_at)
    return TokenResponse(token=token, expires_in=expires)


@router.post("/2fa/verify", response_model=TokenResponse)
def verify(body: CodeBody, request: Request, admin: User = Depends(require_admin_basic),
           db: Session = Depends(get_db)):
    row = sec.is_enrolled(db, admin.id)
    if row is None:
        raise HTTPException(status_code=409, detail="2FA is not enabled for this admin")
    _check_code(db, request, admin, row, body.code)
    sec.audit(db, admin, "2fa.verified", request)
    db.commit()
    token, expires = sec.issue_2fa_token(admin.id, row.enabled_at)
    return TokenResponse(token=token, expires_in=expires)


@router.post("/2fa/disable")
def disable(body: CodeBody, request: Request, admin: User = AdminUser,
            db: Session = Depends(get_db)):
    """Needs the full gate (a valid token) and a fresh code on top, so a stolen laptop with
    an open panel cannot switch the protection off."""
    if settings.admin_require_2fa:
        raise HTTPException(status_code=409, detail="2FA is mandatory on this deployment")
    row = sec.is_enrolled(db, admin.id)
    if row is None:
        raise HTTPException(status_code=409, detail="2FA is not enabled")
    _check_code(db, request, admin, row, body.code)
    db.delete(row)
    sec.audit(db, admin, "2fa.disabled", request)
    db.commit()
    return {"ok": True}


# ── Audit log ────────────────────────────────────────────────────────────────

class AuditRow(BaseModel):
    id: int
    at: datetime
    admin_id: int | None
    admin_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict | None
    ip: str | None

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    total: int
    items: list[AuditRow]


@router.get("/audit", response_model=AuditPage)
def audit_log(
    _admin=AdminUser,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: str | None = Query(None, description="Exact action, e.g. user.update"),
    admin_id: int | None = None,
    target_id: str | None = None,
    days: int | None = Query(None, ge=1, le=3650),
):
    """Newest first. Reading the log is not itself logged (it would drown the log)."""
    q = select(AdminAuditLog)
    if action:
        q = q.where(AdminAuditLog.action == action)
    if admin_id is not None:
        q = q.where(AdminAuditLog.admin_id == admin_id)
    if target_id:
        q = q.where(AdminAuditLog.target_id == target_id)
    if days:
        q = q.where(AdminAuditLog.at >= datetime.now(timezone.utc) - timedelta(days=days))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(AdminAuditLog.at.desc(), AdminAuditLog.id.desc())
                      .offset(offset).limit(limit)).all()
    return AuditPage(total=total, items=[AuditRow.model_validate(r) for r in rows])
