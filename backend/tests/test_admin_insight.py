"""
Tests for the admin insight endpoints.

These read data the platform already stores but never surfaced, so each test checks
that the numbers come back shaped the way the dashboard needs, and that the whole
module stays behind the admin gate.
"""
import io
import struct
import uuid

from tests.test_admin import make_admin, register
from tests.test_cough_sync import night


def wav(seconds: float = 2.5, rate: int = 16000) -> bytes:
    """A silent mono 16-bit WAV, the shape clip_store accepts."""
    frames = int(seconds * rate)
    data = b"\x00\x00" * frames
    buf = io.BytesIO()
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
    buf.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
    buf.write(b"data" + struct.pack("<I", len(data)) + data)
    return buf.getvalue()


def a_night(client, user, **overrides):
    r = client.post("/api/sessions/sync", json=night(**overrides), headers=user)
    assert r.status_code == 201, r.text
    return r.json()


# ── The gate ─────────────────────────────────────────────────────────────────

def test_every_insight_endpoint_is_admin_only(client):
    _, user = register(client)
    paths = ["/api/admin/insight/health", "/api/admin/insight/detector",
             "/api/admin/insight/devices", "/api/admin/insight/clips",
             "/api/admin/insight/consent", "/api/admin/insight/users/1/sessions",
             "/api/admin/insight/sessions/1"]
    for p in paths:
        assert client.get(p).status_code == 401, p            # no token at all
        assert client.get(p, headers=user).status_code == 403, p  # token, but not an admin


def test_admin_without_the_secret_header_is_refused(client):
    admin = make_admin(client)
    del admin["X-Admin-Secret"]
    assert client.get("/api/admin/insight/health", headers=admin).status_code == 403


# ── Health ───────────────────────────────────────────────────────────────────

def test_health_counts_nights_by_status_and_flags_the_unfinished_ones(client):
    admin = make_admin(client)
    _, user = register(client)
    a_night(client, user)
    a_night(client, user, device_session_id="18", status="interrupted",
            started_at="2026-10-10T21:00:00.000Z", ended_at=None, events=[])

    r = client.get("/api/admin/insight/health?windows=3650", headers=admin)
    assert r.status_code == 200, r.text
    nights = r.json()["nights"][0]
    assert nights["window_days"] == 3650
    assert nights["by_status"]["complete"] >= 1
    assert nights["by_status"]["interrupted"] >= 1
    # The interrupted night never got an ended_at.
    assert nights["unfinished"] >= 1
    assert 0 < nights["unfinished_pct"] <= 100
    # night() loses an hour of microphone to a phone call.
    assert nights["with_mic_gaps"] >= 1
    assert nights["median_mic_gap_ms"] is not None
    # frames_inferred / frames_seen = 21000 / 60000 = 0.35
    assert nights["median_frame_coverage"] == 0.35


def test_health_reports_one_block_per_requested_window(client):
    admin = make_admin(client)
    r = client.get("/api/admin/insight/health?windows=7,30,3650", headers=admin)
    assert [n["window_days"] for n in r.json()["nights"]] == [7, 30, 3650]
    assert [c["window_days"] for c in r.json()["clips"]] == [7, 30, 3650]


def test_health_shows_clips_the_phone_kept_but_never_delivered(client):
    admin = make_admin(client)
    _, user = register(client)
    a_night(client, user)  # event 1 has has_device_clip=True, and nothing is uploaded

    clips = client.get("/api/admin/insight/health?windows=3650", headers=admin).json()["clips"][0]
    assert clips["events_with_device_clip"] >= 1
    assert clips["events_with_stored_clip"] == 0
    assert clips["delivered_pct"] == 0.0


def test_health_counts_a_delivered_clip_and_its_feature_backlog(client):
    admin = make_admin(client)
    _, user = register(client)
    sid = a_night(client, user)["id"]

    up = client.post(f"/api/sessions/{sid}/events/1/clip", headers=user,
                     files={"file": ("c.wav", wav(), "audio/wav")})
    assert up.status_code == 201, up.text

    clips = client.get("/api/admin/insight/health?windows=3650", headers=admin).json()["clips"][0]
    assert clips["events_with_stored_clip"] >= 1
    assert clips["delivered_pct"] is not None
    # Features are computed at upload, so nothing should be waiting.
    assert clips["awaiting_features"] == 0


def test_health_on_an_empty_platform_does_not_divide_by_zero(client):
    admin = make_admin(client)
    r = client.get("/api/admin/insight/health?windows=1", headers=admin)
    assert r.status_code == 200
    n = r.json()["nights"][0]
    assert n["sessions"] == 0 and n["unfinished_pct"] is None
    assert r.json()["clips"][0]["delivered_pct"] is None


# ── Detector ─────────────────────────────────────────────────────────────────

def test_detector_separates_coughs_from_sneezes_and_buckets_the_scores(client):
    admin = make_admin(client)
    _, user = register(client)
    a_night(client, user)

    r = client.get("/api/admin/insight/detector?days=3650", headers=admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["by_type"]["cough"] >= 3 and d["by_type"]["sneeze"] >= 1
    assert sum(d["confidence_buckets"].values()) == d["events"]
    # night() scores: 0.91, 0.85, 0.6, 0.7
    assert d["confidence_buckets"][">=0.9"] >= 1
    assert d["confidence_buckets"]["0.7-0.9"] >= 1
    assert d["median_confidence"] is not None
    assert d["median_events_per_night"] is not None


def test_detector_reports_what_users_rejected_as_the_field_false_positive_rate(client):
    admin = make_admin(client)
    _, user = register(client)
    a_night(client, user)

    # The app applies a user's verdicts by re-syncing the night with the labels set.
    labelled = night()
    labelled["events"][0]["user_label"] = "not_an_event"
    labelled["events"][1]["user_label"] = "subject"
    assert client.post("/api/sessions/sync", json=labelled, headers=user).status_code in (200, 201)

    d = client.get("/api/admin/insight/detector?days=3650", headers=admin).json()
    assert d["by_user_label"]["not_an_event"] == 1
    assert d["by_user_label"]["subject"] == 1
    assert d["by_user_label"]["unlabelled"] >= 1
    assert d["labelled"] == 2
    assert d["rejected_pct_of_labelled"] == 50.0


def test_detector_on_no_data_returns_zeroes_not_an_error(client):
    admin = make_admin(client)
    d = client.get("/api/admin/insight/detector?days=1", headers=admin).json()
    assert d["events"] == 0
    assert d["labelled_pct"] is None and d["rejected_pct_of_labelled"] is None


# ── Devices ──────────────────────────────────────────────────────────────────

def test_devices_groups_by_phone_version_and_microphone_route(client):
    admin = make_admin(client)
    _, user = register(client)
    a_night(client, user)
    a_night(client, user, device_session_id="19", device_model="Pixel 8",
            app_version="0.3.1", audio_source="MIC@44k",
            started_at="2026-10-11T21:00:00.000Z", ended_at="2026-10-12T05:00:00.000Z")

    rows = client.get("/api/admin/insight/devices?days=3650", headers=admin).json()
    by_model = {r["device_model"]: r for r in rows}
    assert "samsung SM-S911B" in by_model and "Pixel 8" in by_model
    samsung = by_model["samsung SM-S911B"]
    assert samsung["app_version"] == "0.2.0"
    assert samsung["audio_source"] == "CAMCORDER@48k"
    assert samsung["sessions"] >= 1 and samsung["users"] >= 1
    assert samsung["median_noise_floor_db"] == -62.5
    assert samsung["median_frame_coverage"] == 0.35
    assert samsung["last_seen_at"] is not None


# ── Clips ────────────────────────────────────────────────────────────────────

def test_clip_storage_reports_size_age_and_expiry(client):
    admin = make_admin(client)
    _, user = register(client)
    sid = a_night(client, user)["id"]
    client.post(f"/api/sessions/{sid}/events/1/clip", headers=user,
                files={"file": ("c.wav", wav(), "audio/wav")})

    s = client.get("/api/admin/insight/clips", headers=admin).json()
    assert s["clips_enabled"] is True
    assert s["stored_clips"] >= 1
    assert s["total_bytes"] > 0 and s["total_mb"] >= 0
    assert s["median_duration_ms"] is not None
    assert s["oldest_at"] is not None and s["newest_at"] is not None
    # 90-day retention: nothing is expiring this week and nothing is overdue.
    assert s["expiring_within_7_days"] == 0
    assert s["already_expired_awaiting_purge"] == 0


def test_clip_storage_counts_users_who_switched_clips_off(client):
    admin = make_admin(client)
    _, user = register(client)
    before = client.get("/api/admin/insight/clips", headers=admin).json()["users_with_clips_off"]
    r = client.put("/api/consent", headers=user, json={"audioClips": False})
    assert r.status_code == 200, r.text
    after = client.get("/api/admin/insight/clips", headers=admin).json()
    assert after["users_with_clips_off"] == before + 1


# ── Consent ──────────────────────────────────────────────────────────────────

def test_consent_breaks_out_every_flag_not_just_the_accepted_date(client):
    admin = make_admin(client)
    _, user = register(client)
    client.put("/api/consent", headers=user,
               json={"coughTracking": True, "healthTrends": True, "productAnalytics": False})

    c = client.get("/api/admin/insight/consent", headers=admin).json()
    assert c["total_users"] >= 2
    assert c["users_with_consent_row"] >= 1
    assert c["users_without_consent_row"] == c["total_users"] - c["users_with_consent_row"]
    assert c["cough_tracking"] >= 1 and c["health_trends"] >= 1
    assert "audio_clips" in c and "audio_clips_changed_by_user" in c


# ── Drill-down ───────────────────────────────────────────────────────────────

def test_user_sessions_expose_the_recording_context_the_admin_ui_cannot_reach(client):
    admin = make_admin(client)
    email, user = register(client)
    a_night(client, user)
    uid = next(u for u in client.get("/api/admin/users", headers=admin).json()
               if u["email"] == email)["id"]

    rows = client.get(f"/api/admin/insight/users/{uid}/sessions", headers=admin).json()
    assert len(rows) == 1
    s = rows[0]
    assert s["device_model"] == "samsung SM-S911B"
    assert s["app_version"] == "0.2.0"
    assert s["audio_source"] == "CAMCORDER@48k"
    assert s["noise_floor_db"] == -62.5
    assert s["mic_gap_ms"] == 3_600_000
    assert (s["frames_seen"], s["frames_inferred"]) == (60000, 21000)
    assert s["frame_coverage"] == 0.35
    assert s["detector_config"] == {"cough": {"onThreshold": 0.1}}
    assert s["timezone"] == "Europe/Amsterdam"


def test_user_sessions_404_for_an_unknown_user(client):
    admin = make_admin(client)
    assert client.get("/api/admin/insight/users/99999999/sessions",
                      headers=admin).status_code == 404


def test_session_detail_lists_events_in_time_order_with_their_scores(client):
    admin = make_admin(client)
    _, user = register(client)
    sid = a_night(client, user)["id"]
    client.post(f"/api/sessions/{sid}/events/1/clip", headers=user,
                files={"file": ("c.wav", wav(), "audio/wav")})

    d = client.get(f"/api/admin/insight/sessions/{sid}", headers=admin).json()
    assert d["session"]["id"] == sid
    assert d["user_id"] is not None
    ats = [e["timestamp"] for e in d["events"]]
    assert ats == sorted(ats)
    first = d["events"][0]
    assert (first["confidence"], first["peak_db"], first["snr_db"]) == (0.91, -21.5, 38.0)
    assert first["bout_id"] == 1
    assert first["subject_label"] == "subject"
    assert first["has_device_clip"] is True
    assert first["clip_stored"] is True
    assert "acoustic-v1" in first["feature_methods"]
    # The second event had no clip kept on the phone.
    assert d["events"][1]["clip_stored"] is False
    assert any(e["event_type"] == "sneeze" for e in d["events"])


def test_session_detail_404_for_an_unknown_session(client):
    admin = make_admin(client)
    assert client.get("/api/admin/insight/sessions/99999999",
                      headers=admin).status_code == 404
