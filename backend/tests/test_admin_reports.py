import csv
import io
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import update

from app.database import SessionLocal
from app.models import User
from tests.test_admin import make_admin, register
from tests.test_cough_sync import night


def _user_with_activity(client):
    email, user = register(client, "Reporter")
    assert client.post("/api/sessions/sync", json=night(), headers=user).status_code == 201
    assert client.post("/api/observations", headers=user, json={"readings": [
        {"measured_at": "2026-10-10T07:12:00+02:00", "values": [{"metric": "body.weight", "value": 80.0}]}]}).status_code in (200, 201)
    return email, user


def test_signups_fill_every_period_and_keep_a_running_total(client):
    admin = make_admin(client)
    register(client)
    rows = client.get("/api/admin/reports/signups", headers=admin, params={"days": 10}).json()
    assert len(rows) == 11                                    # 10 days back plus today
    assert rows[-1]["period"] == str(datetime.now(timezone.utc).date())
    assert rows[-1]["new_users"] >= 2                         # the admin and the user just registered
    totals = [r["total_users"] for r in rows]
    assert totals == sorted(totals) and totals[-1] == client.get("/api/admin/stats", headers=admin).json()["total_users"]

    weekly = client.get("/api/admin/reports/signups", headers=admin, params={"days": 60, "bucket": "month"}).json()
    assert all(date.fromisoformat(r["period"]).day == 1 for r in weekly)
    assert client.get("/api/admin/reports/signups", headers=admin, params={"bucket": "year"}).status_code == 422


def test_activity_counts_people_who_did_something(client):
    admin = make_admin(client)
    before = client.get("/api/admin/reports/activity", headers=admin).json()
    _user_with_activity(client)
    after = client.get("/api/admin/reports/activity", headers=admin, params={"days": 7}).json()
    assert after["active_24h"] >= before["active_24h"] + 1
    assert after["active_30d"] >= after["active_7d"] >= after["active_24h"]
    assert len(after["daily"]) == 7 and after["daily"][-1]["active_users"] >= 1
    assert after["stickiness_pct"] is not None


def test_retention_only_reports_weeks_that_are_over(client):
    admin = make_admin(client)
    email, _ = _user_with_activity(client)
    # Move this user's sign-up three weeks back so weeks +1 and +2 are measurable.
    with SessionLocal() as db:
        db.execute(update(User).where(User.email == email).values(
            created_at=datetime.now(timezone.utc) - timedelta(weeks=3)))
        db.commit()
    rows = client.get("/api/admin/reports/retention", headers=admin, params={"weeks": 6}).json()
    assert len(rows) == 6
    old = next(r for r in rows if r["cohort_week"] == str(
        (datetime.now(timezone.utc) - timedelta(weeks=3)).date() - timedelta(
            days=(datetime.now(timezone.utc) - timedelta(weeks=3)).weekday())))
    assert old["users"] >= 1
    assert old["week_1_pct"] is not None and old["week_3_pct"] is None   # +3 weeks is the current week
    newest = rows[-1]
    assert newest["week_1_pct"] is None                                   # nothing has elapsed yet


def test_usage_lists_each_feature_with_its_share_of_active_users(client):
    admin = make_admin(client)
    _user_with_activity(client)
    r = client.get("/api/admin/reports/usage", headers=admin, params={"days": 365}).json()
    by = {f["feature"]: f for f in r["features"]}
    assert by["night_recording"]["users"] >= 1 and by["reading:body.weight"]["users"] >= 1
    assert "record_upload" in by
    assert 0 < by["night_recording"]["share_of_active_pct"] <= 100
    assert r["active_users"] <= r["total_users"]


def test_nights_report_is_aggregate_only(client):
    admin = make_admin(client)
    _user_with_activity(client)
    r = client.get("/api/admin/reports/nights", headers=admin, params={"days": 365}).json()
    assert r["nights"] >= 1 and r["recording_users"] >= 1
    assert r["median_night_hours"] == 8.0
    assert sum(b["count"] for b in r["nights_per_user"]) == r["recording_users"]
    assert sum(b["count"] for b in r["coughs_per_night"]) >= 1
    assert "user_id" not in str(r) and "email" not in str(r)


def test_csv_export_is_valid_audited_and_admin_only(client):
    admin = make_admin(client)
    _user_with_activity(client)
    r = client.get("/api/admin/reports/export/usage.csv", headers=admin, params={"days": 365})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="haman-usage-' in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")                           # BOM so Excel reads UTF-8
    rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert rows[0] == ["feature", "users", "share_of_active_pct", "records"]
    assert any(row[0] == "night_recording" for row in rows[1:])

    for name in ("signups", "activity", "retention", "nights"):
        assert client.get(f"/api/admin/reports/export/{name}.csv", headers=admin).status_code == 200, name
    assert client.get("/api/admin/reports/export/everything.csv", headers=admin).status_code == 404

    log = client.get("/api/admin/audit", headers=admin, params={"action": "report.export"}).json()
    assert log["total"] >= 5 and {i["target_id"] for i in log["items"]} >= {"usage", "signups"}

    _, user = register(client)
    assert client.get("/api/admin/reports/export/usage.csv", headers=user).status_code == 403
    assert client.get("/api/admin/reports/usage").status_code == 401
