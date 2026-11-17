"""Admin security helpers: TOTP (RFC 6238), the short-lived "2FA verified" token, and the
audit-log writer. Standard library plus python-jose and cryptography, which are already
dependencies, so nothing new to install."""
import base64
import hashlib
import hmac
import os
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AdminAuditLog, AdminTotp, User

settings = get_settings()

STEP_SECONDS = 30
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15


# ── TOTP ─────────────────────────────────────────────────────────────────────

def new_secret() -> str:
    """160-bit secret, base32 (32 characters, no padding needed)."""
    return base64.b32encode(os.urandom(20)).decode()


def _code_for(secret: str, step: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def match_step(secret: str, code: str, last_used_step: int = 0, now: float | None = None) -> int | None:
    """The 30-second step `code` belongs to (current step, or one either side to allow for
    clock drift), or None. A step at or below last_used_step is refused: a code works once."""
    code = "".join(code.split())
    if len(code) != 6 or not code.isdigit():
        return None
    current = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in (current - 1, current, current + 1):
        if step > last_used_step and hmac.compare_digest(_code_for(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, email: str) -> str:
    issuer = settings.admin_2fa_issuer
    return (f"otpauth://totp/{quote(issuer)}:{quote(email)}"
            f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period={STEP_SECONDS}")


def _fernet() -> Fernet:
    digest = hashlib.sha256(("admin-totp:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # SECRET_KEY changed since enrolment: the admin has to enrol again


def is_enrolled(db: Session, user_id: int) -> AdminTotp | None:
    row = db.get(AdminTotp, user_id)
    return row if row is not None and row.enabled_at is not None else None


def is_locked(row: AdminTotp) -> bool:
    return row.locked_until is not None and row.locked_until > datetime.now(timezone.utc)


def register_failure(row: AdminTotp) -> bool:
    """Count a wrong code; returns True if this one locked the account."""
    row.failed_attempts += 1
    if row.failed_attempts >= MAX_FAILED_ATTEMPTS:
        row.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)
        row.failed_attempts = 0
        return True
    return False


# ── "2FA verified" token ─────────────────────────────────────────────────────
# Signed with a key derived from SECRET_KEY, not SECRET_KEY itself: the normal login JWT
# only checks `sub`, so a token signed with the plain key would double as a login token.

def _token_key() -> str:
    return settings.secret_key + ":admin-2fa"


def issue_2fa_token(user_id: int, enabled_at: datetime) -> tuple[str, int]:
    seconds = settings.admin_2fa_session_minutes * 60
    exp = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    # `ver` ties the token to this enrolment: disabling and re-enrolling invalidates it.
    token = jwt.encode({"sub": str(user_id), "typ": "admin2fa", "ver": int(enabled_at.timestamp()),
                        "exp": exp}, _token_key(), algorithm=settings.algorithm)
    return token, seconds


def token_is_valid(token: str | None, user_id: int, enabled_at: datetime) -> bool:
    if not token:
        return False
    try:
        claims = jwt.decode(token, _token_key(), algorithms=[settings.algorithm])
    except JWTError:
        return False
    return (claims.get("typ") == "admin2fa" and claims.get("sub") == str(user_id)
            and claims.get("ver") == int(enabled_at.timestamp()))


# ── Audit log ────────────────────────────────────────────────────────────────

def client_ip(request: Request | None) -> str | None:
    """The address the request came from. Behind the DirectAdmin proxy the socket address
    is the proxy, so the first X-Forwarded-For entry is used when present."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)
    return ip[:64] if ip else None


def audit(db: Session, admin: User | None, action: str, request: Request | None = None,
          target_type: str | None = None, target_id: object = None, detail: dict | None = None) -> None:
    """Add an audit row to the caller's transaction (the caller commits), so a change and
    its log entry succeed or fail together. For a read, call db.commit() afterwards."""
    db.add(AdminAuditLog(
        admin_id=admin.id if admin else None,
        admin_email=admin.email if admin else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail,
        ip=client_ip(request),
    ))
