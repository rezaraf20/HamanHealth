import uuid

from sqlalchemy import update

from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from tests.test_cough_sync import night


def register(client, name="Test User"):
    email = f"{uuid.uuid4().hex[:10]}@test.dev"
    r = client.post("/api/auth/register", json={"email": email, "password": "pw-123456", "name": name})
    assert r.status_code == 201, r.text
    return email, {"Authorization": f"Bearer {r.json()['access']}"}


def make_admin(client):
    email, headers = register(client, "Admin")
    with SessionLocal() as db:
        db.execute(update(User).where(User.email == email).values(is_admin=True))
        db.commit()
    return {**headers, "X-Admin-Secret": get_settings().admin_secret}


def test_user_list_shows_who_registered_and_what_is_stored(client):
    admin = make_admin(client)
    email, user = register(client, "Night Owl")

    # Two nights: the list used to fail (500) as soon as any user had more than one session.
    first = client.post("/api/sessions/sync", json=night(), headers=user)
    second = client.post("/api/sessions/sync", headers=user, json=night(
        device_session_id="18", started_at="2026-10-10T21:00:00.000Z", ended_at="2026-10-11T05:00:00.000Z", events=[]))
    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    client.post("/api/observations", headers=user, json={"readings": [
        {"measured_at": "2026-10-10T07:12:00+02:00", "values": [{"metric": "body.weight", "value": 82.4}]}]})

    r = client.get("/api/admin/users", headers=admin)
    assert r.status_code == 200, r.text
    row = next(u for u in r.json() if u["email"] == email)
    assert row["name"] == "Night Owl"
    assert row["total_sessions"] == 2
    assert row["total_coughs"] == first.json()["event_count"]
    assert row["last_session_at"].startswith("2026-10-10T21:00")  # the most recent night
    assert row["total_readings"] >= 1
    assert row["total_records"] == 0

    one = client.get(f"/api/admin/users/{row['id']}", headers=admin)
    assert one.status_code == 200 and one.json() == row


def test_user_list_includes_users_with_no_data_yet(client):
    admin = make_admin(client)
    email, _ = register(client)
    row = next(u for u in client.get("/api/admin/users", headers=admin).json() if u["email"] == email)
    assert (row["total_sessions"], row["total_coughs"], row["last_session_at"]) == (0, 0, None)
    assert row["consent_accepted_at"] is None


def test_user_list_is_admin_only(client):
    _, user = register(client)
    secret = {"X-Admin-Secret": get_settings().admin_secret}
    assert client.get("/api/admin/users", headers={**user, **secret}).status_code == 403  # not an admin
    admin = make_admin(client)
    assert client.get("/api/admin/users", headers={**admin, "X-Admin-Secret": "wrong"}).status_code == 403
    assert client.get("/api/admin/users").status_code == 401
