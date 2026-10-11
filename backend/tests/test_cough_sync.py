from datetime import timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import CoughEvent, CoughSession


def night(**overrides):
    """A night in Amsterdam (UTC+2 in October) that crosses midnight: 23:00 → 07:00
    local, i.e. 21:00Z → 05:00Z. Reported under the wake-up date, 2026-10-10."""
    body = {
        "device_session_id": "17",
        "started_at": "2026-10-09T21:00:00.000Z",
        "ended_at": "2026-10-10T05:00:00.000Z",
        "status": "complete",
        "timezone": "Europe/Amsterdam",
        "sensitivity": "medium",
        "device_model": "samsung SM-S911B",
        "app_version": "0.2.0",
        "audio_source": "CAMCORDER@48k",
        "noise_floor_db": -62.5,
        "mic_gap_ms": 3_600_000,   # one hour lost to a phone call → 7 monitored hours
        "frames_seen": 60000,
        "frames_inferred": 21000,
        "detector_config": {"cough": {"onThreshold": 0.1}},
        "events": [
            {"device_event_id": "1", "event_type": "cough",
             "timestamp": "2026-10-09T22:15:03.120Z", "ended_at": "2026-10-09T22:15:04.560Z",
             "peak_at": "2026-10-09T22:15:03.600Z", "confidence": 0.91, "mean_score": 0.7,
             "peak_db": -21.5, "snr_db": 38.0, "bout_id": 1,
             "subject_label": "subject", "subject_confidence": 0.8, "has_device_clip": True},
            {"device_event_id": "2", "event_type": "cough",
             "timestamp": "2026-10-09T22:15:06.000Z", "ended_at": "2026-10-09T22:15:07.440Z",
             "confidence": 0.85, "bout_id": 1},
            {"device_event_id": "3", "event_type": "cough",
             "timestamp": "2026-10-10T03:02:00.000Z", "ended_at": "2026-10-10T03:02:01.440Z",
             "confidence": 0.6, "bout_id": 2},
            {"device_event_id": "4", "event_type": "sneeze",
             "timestamp": "2026-10-10T04:00:00.000Z", "ended_at": "2026-10-10T04:00:00.960Z",
             "confidence": 0.7},
        ],
        "snore_episodes": [
            {"started_at": "2026-10-10T00:00:00Z", "ended_at": "2026-10-10T00:30:00Z",
             "snore_count": 400, "mean_intensity_db": -40.0},
        ],
    }
    body.update(overrides)
    return body


def utc(dt):
    """ISO string in UTC, whatever zone the DB connection reports in."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def daily(client, user):
    """The user's daily numbers (all days), via the report endpoint: {metric: row}.
    Every test uses a fresh user, so this is exactly the night(s) it uploaded."""
    r = client.get("/api/reports/daily?from=2000-01-01&to=2100-01-01", headers=user)
    assert r.status_code == 200, r.text
    return {row["metric"]: row for row in r.json()}


def test_full_night_is_stored_exactly(client, user):
    r = client.post("/api/sessions/sync", json=night(), headers=user)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["event_count"] == 3  # coughs only, not the sneeze

    with SessionLocal() as db:
        s = db.get(CoughSession, sid)
        assert (s.status, s.timezone, s.audio_source, s.mic_gap_ms) == (
            "complete", "Europe/Amsterdam", "CAMCORDER@48k", 3_600_000)
        assert s.detector_config == {"cough": {"onThreshold": 0.1}}
        assert len(s.snore_episodes) == 1
        ev = db.scalar(select(CoughEvent).where(CoughEvent.session_id == sid,
                                                CoughEvent.device_event_id == "1"))
        # Millisecond timeline survives the round trip.
        assert utc(ev.timestamp) == "2026-10-09T22:15:03.120+00:00"
        assert utc(ev.ended_at) == "2026-10-09T22:15:04.560+00:00"
        assert utc(ev.peak_at) == "2026-10-09T22:15:03.600+00:00"
        assert (ev.confidence, ev.mean_score, ev.peak_db, ev.snr_db, ev.bout_id) == (0.91, 0.7, -21.5, 38.0, 1)
        assert (ev.subject_label, ev.has_device_clip, ev.event_type) == ("subject", True, "cough")
        assert ev.duration_ms == 1440  # calculated by the database from start/end

    obs = daily(client, user)
    assert obs["cough.count"]["value"] == 3
    assert obs["cough.bouts"]["value"] == 2
    assert obs["sneeze.count"]["value"] == 1
    assert obs["snore.duration"]["value"] == 30.0
    assert obs["monitoring.duration"]["value"] == 7.0
    assert obs["cough.rate"]["value"] == round(3 / 7, 2)
    assert obs["cough.rate"]["unit"] == "{count}/h"
    # Crosses midnight in UTC and locally, but lands on one day: the wake-up date.
    assert {o["local_date"] for o in obs.values()} == {"2026-10-10"}


def test_resync_is_idempotent_and_applies_user_labels(client, user):
    sid = client.post("/api/sessions/sync", json=night(), headers=user).json()["id"]
    again = client.post("/api/sessions/sync", json=night(), headers=user)
    assert again.json()["id"] == sid
    with SessionLocal() as db:
        assert len(db.scalars(select(CoughEvent).where(CoughEvent.session_id == sid)).all()) == 4

    # Next morning the user marks one cough as "not a cough" and another as someone else's.
    labelled = night()
    labelled["events"][1]["user_label"] = "not_an_event"
    labelled["events"][2]["user_label"] = "other"
    r = client.post("/api/sessions/sync", json=labelled, headers=user)
    assert r.json()["event_count"] == 1
    obs = daily(client, user)
    assert obs["cough.count"]["value"] == 1
    assert obs["cough.bouts"]["value"] == 1
    with SessionLocal() as db:  # rejected events are kept, only excluded from counts
        assert len(db.scalars(select(CoughEvent).where(CoughEvent.session_id == sid)).all()) == 4


def test_running_night_is_not_reported_until_it_ends(client, user):
    body = night(status="running", ended_at=None, events=night()["events"][:1])
    sid = client.post("/api/sessions/sync", json=body, headers=user).json()["id"]
    assert daily(client, user) == {}
    client.post("/api/sessions/sync", json=night(), headers=user)
    assert daily(client, user)["cough.count"]["value"] == 3


def test_legacy_payload_still_accepted(client, user):
    r = client.post("/api/sessions/sync", headers=user, json={
        "device_session_id": "legacy-1",
        "started_at": "2026-10-09T21:00:00Z",
        "ended_at": "2026-10-10T05:00:00Z",
        "events": [{"timestamp": "2026-10-09T22:00:00Z", "confidence": 0.8}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["event_count"] == 1
    assert daily(client, user)["cough.count"]["value"] == 1


def test_timestamps_without_timezone_are_rejected(client, user):
    body = night()
    body["events"][0]["timestamp"] = "2026-10-09T22:15:03"
    assert client.post("/api/sessions/sync", json=body, headers=user).status_code == 422


def test_unknown_timezone_rejected(client, user):
    assert client.post("/api/sessions/sync", json=night(timezone="Mars/Olympus"),
                       headers=user).status_code == 422


def test_other_users_cannot_see_a_session(client, user):
    sid = client.post("/api/sessions/sync", json=night(), headers=user).json()["id"]
    other = client.post("/api/auth/register", json={"email": "x-other@test.dev", "password": "pw-123456"})
    hdr = {"Authorization": f"Bearer {other.json()['access']}"}
    assert client.get(f"/api/sessions/{sid}", headers=hdr).status_code == 404


def test_existing_reports_count_coughs_not_sneezes(client, user):
    client.post("/api/sessions/sync", json=night(), headers=user)
    summary = client.get("/api/sessions/last/summary", headers=user).json()
    assert summary["coughs"] == 3
    assert sum(h["coughs"] for h in summary["hourly"]) == 3
    # Amsterdam clock, in night order: two coughs at 00:15 local, one at 05:02.
    assert summary["hourly"] == [{"hour": "00:00", "coughs": 2}, {"hour": "05:00", "coughs": 1}]
    assert summary["date"] == "2026-10-10"


def test_web_session_end_appears_in_daily_report(client, user):
    s = client.post("/api/sessions", json={"sensitivity": "medium"}, headers=user).json()
    client.post("/api/sessions/events", headers=user,
                json={"events": [{"session_id": s["id"], "timestamp": "2026-10-10T01:00:00Z", "count": 2}]})
    client.post(f"/api/sessions/{s['id']}/end", headers=user)
    assert daily(client, user)["cough.count"]["value"] == 2
