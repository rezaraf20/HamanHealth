import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import get_settings
from app.database import SessionLocal
from app.routers.admin_reports import _safe
from app.services import admin_security as sec
from tests.test_admin import make_admin, register


def code(secret: str, offset: int = 0) -> str:
    """The code for the current 30-second step (+offset). A code works once, so tests that
    use several in a row walk forward: -1, 0, +1 are all inside the accepted window."""
    return sec._code_for(secret, int(time.time() // sec.STEP_SECONDS) + offset)


def enrol(client, admin):
    secret = client.post("/api/admin/2fa/setup", headers=admin).json()["secret"]
    r = client.post("/api/admin/2fa/enable", headers=admin, json={"code": code(secret, -1)})
    assert r.status_code == 200, r.text
    return secret, {**admin, "X-Admin-2FA": r.json()["token"]}


def test_without_enrolment_the_admin_api_works_as_before(client):
    admin = make_admin(client)
    assert client.get("/api/admin/users", headers=admin).status_code == 200
    st = client.get("/api/admin/2fa/status", headers=admin).json()
    assert st == {"enrolled": False, "enrolment_pending": False, "required": False, "token_valid": False}


def test_setup_alone_does_not_lock_the_admin_out(client):
    admin = make_admin(client)
    setup = client.post("/api/admin/2fa/setup", headers=admin)
    assert setup.status_code == 200 and setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert client.get("/api/admin/users", headers=admin).status_code == 200
    assert client.get("/api/admin/2fa/status", headers=admin).json()["enrolment_pending"] is True
    # Verify makes no sense before enrolment finished.
    assert client.post("/api/admin/2fa/verify", headers=admin, json={"code": "000000"}).status_code == 409


def test_enrolled_admin_needs_a_token_for_every_admin_endpoint(client):
    admin = make_admin(client)
    secret, with_token = enrol(client, admin)

    blocked = client.get("/api/admin/users", headers=admin)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "admin_2fa_required"
    for path in ("/api/admin/stats", "/api/admin/insight/health", "/api/admin/reports/usage", "/api/admin/audit"):
        assert client.get(path, headers=admin).status_code == 403, path
        assert client.get(path, headers=with_token).status_code == 200, path

    # Sign in again later: a fresh code (next step) buys a new token.
    again = client.post("/api/admin/2fa/verify", headers=admin, json={"code": code(secret, 0)})
    assert again.status_code == 200
    assert client.get("/api/admin/users", headers={**admin, "X-Admin-2FA": again.json()["token"]}).status_code == 200


def test_a_code_works_only_once(client):
    admin = make_admin(client)
    secret, _ = enrol(client, admin)                      # used step -1
    assert client.post("/api/admin/2fa/verify", headers=admin, json={"code": code(secret, -1)}).status_code == 401
    assert client.post("/api/admin/2fa/verify", headers=admin, json={"code": code(secret, 0)}).status_code == 200
    assert client.post("/api/admin/2fa/verify", headers=admin, json={"code": code(secret, 0)}).status_code == 401


def test_wrong_codes_lock_the_account_for_a_while(client):
    admin = make_admin(client)
    secret, _ = enrol(client, admin)
    for _ in range(sec.MAX_FAILED_ATTEMPTS):
        assert client.post("/api/admin/2fa/verify", headers=admin, json={"code": "123456"}).status_code == 401
    locked = client.post("/api/admin/2fa/verify", headers=admin, json={"code": code(secret, 0)})
    assert locked.status_code == 429          # even the right code is refused while locked


def test_tokens_are_bound_to_the_admin_and_are_not_login_tokens(client):
    a, b = make_admin(client), make_admin(client)
    _, a_tok = enrol(client, a)
    enrol(client, b)
    # A's 2FA token on B's session: refused.
    assert client.get("/api/admin/users", headers={**b, "X-Admin-2FA": a_tok["X-Admin-2FA"]}).status_code == 403
    # And it is useless as a bearer token for the normal API.
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {a_tok['X-Admin-2FA']}"})
    assert r.status_code == 401


def test_disable_needs_token_and_a_fresh_code_then_drops_the_requirement(client):
    admin = make_admin(client)
    secret, with_token = enrol(client, admin)
    assert client.post("/api/admin/2fa/disable", headers=admin, json={"code": code(secret, 0)}).status_code == 403
    assert client.post("/api/admin/2fa/disable", headers=with_token, json={"code": "000000"}).status_code == 401
    assert client.post("/api/admin/2fa/disable", headers=with_token, json={"code": code(secret, 0)}).status_code == 200
    assert client.get("/api/admin/users", headers=admin).status_code == 200


def test_require_2fa_setting_forces_enrolment_but_leaves_the_enrolment_page_reachable(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(get_settings(), "admin_require_2fa", True)
    r = client.get("/api/admin/users", headers=admin)
    assert r.status_code == 403 and r.json()["detail"] == "admin_2fa_enrolment_required"
    assert client.get("/api/admin/2fa/status", headers=admin).json()["required"] is True
    secret = client.post("/api/admin/2fa/setup", headers=admin).json()["secret"]
    tok = client.post("/api/admin/2fa/enable", headers=admin, json={"code": code(secret, -1)}).json()["token"]
    assert client.get("/api/admin/users", headers={**admin, "X-Admin-2FA": tok}).status_code == 200
    # Mandatory means the admin cannot switch it off.
    assert client.post("/api/admin/2fa/disable", headers={**admin, "X-Admin-2FA": tok},
                       json={"code": code(secret, 0)}).status_code == 409


# ── Audit log ────────────────────────────────────────────────────────────────

def test_changes_and_individual_data_views_are_audited(client):
    admin = make_admin(client)
    email, user = register(client, "Someone")
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json() if u["email"] == email)

    client.put(f"/api/admin/users/{uid}", headers=admin, json={"is_active": False, "name": "Renamed"})
    client.put(f"/api/admin/users/{uid}", headers=admin, json={"name": "Renamed"})   # no change: not logged
    client.get(f"/api/admin/insight/users/{uid}/sessions", headers=admin)

    log = client.get("/api/admin/audit", headers=admin, params={"target_id": str(uid)}).json()
    actions = [row["action"] for row in log["items"]]
    assert sorted(actions) == ["user.sessions.view", "user.update"]
    update = next(r for r in log["items"] if r["action"] == "user.update")
    assert update["detail"]["changes"] == {"is_active": {"from": True, "to": False},
                                           "name": {"from": "Someone", "to": "Renamed"}}
    assert update["admin_email"] and update["target_type"] == "user"


def test_audit_filters(client):
    admin = make_admin(client)
    client.put("/api/admin/config", headers=admin, json={
        "primary_color": "#123456", "secondary_color": "#e8f5f0", "logo_url": "/a.png",
        "logo_white_url": "/b.png", "app_name": "Haman Health", "tagline": "t", "support_email": "s@x.dev"})
    log = client.get("/api/admin/audit", headers=admin, params={"action": "config.update", "days": 1}).json()
    assert log["total"] >= 1
    assert log["items"][0]["detail"]["changes"]["primary_color"]["to"] == "#123456"


def test_audit_log_is_append_only_in_the_database(client):
    admin = make_admin(client)
    client.put("/api/admin/config", headers=admin, json={
        "primary_color": "#654321", "secondary_color": "#e8f5f0", "logo_url": "/a.png",
        "logo_white_url": "/b.png", "app_name": "Haman Health", "tagline": "t", "support_email": "s@x.dev"})
    with SessionLocal() as db:
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("UPDATE admin_audit_log SET action = 'x'"))
        db.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text("DELETE FROM admin_audit_log"))
        db.rollback()


def test_retention_job_can_delete_old_rows_and_nothing_else_can(client):
    from datetime import datetime, timedelta, timezone
    from app.jobs import purge_audit_log
    from app.models import AdminAuditLog
    with SessionLocal() as db:
        db.add(AdminAuditLog(action="test.old", at=datetime.now(timezone.utc) - timedelta(days=5000)))
        db.add(AdminAuditLog(action="test.recent"))
        db.commit()
    purge_audit_log.main()
    with SessionLocal() as db:
        left = {a for (a,) in db.execute(text("SELECT action FROM admin_audit_log WHERE action LIKE 'test.%'"))}
    assert left == {"test.recent"}


def test_csv_cells_cannot_run_as_formulas():
    assert _safe("=1+1") == "'=1+1" and _safe("@SUM(A1)") == "'@SUM(A1)" and _safe("ok") == "ok"
    assert _safe(None) == "" and _safe(5) == 5
