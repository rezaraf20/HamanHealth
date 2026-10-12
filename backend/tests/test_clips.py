import io
import os
import wave
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import inspect, select, update

from app.clips_db import AudioClip, ClipsSessionLocal, clips_engine
from app.config import get_settings
from app.database import SessionLocal
from app.models import CoughEvent, CoughEventFeatures
from app.services import clip_store
from tests.test_cough_sync import night

RATE = 16_000


def wav(seconds: float = 2.5, burst: tuple[float, float] | None = None, seed: int = 0) -> bytes:
    """Quiet room noise, optionally with a loud noise burst between burst=(start_s, end_s)."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.001, int(seconds * RATE))
    if burst:
        a, b = int(burst[0] * RATE), int(burst[1] * RATE)
        x[a:b] += rng.normal(0, 0.3, b - a)
    pcm = np.clip(x * 32767, -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synced(client, user) -> int:
    return client.post("/api/sessions/sync", json=night(), headers=user).json()["id"]


def upload(client, user, sid, event_id="1", data=None, **form):
    return client.post(f"/api/sessions/{sid}/events/{event_id}/clip", headers=user,
                       files={"file": ("c.wav", data or wav(), "audio/wav")}, data=form)


def test_clips_are_on_by_default(client, user):
    assert client.get("/api/consent", headers=user).json()["audioClips"] is True
    sid = synced(client, user)
    assert upload(client, user, sid).status_code == 201


def test_switching_clips_off_stops_uploads_and_keeps_stored_ones(client, user):
    sid = synced(client, user)
    kept = upload(client, user, sid, event_id="1").json()["clip_anon_id"]
    client.put("/api/consent", json={"audioClips": False}, headers=user)
    assert upload(client, user, sid, event_id="2").status_code == 403
    assert client.get(f"/api/clips/{kept}", headers=user).status_code == 200
    # The current web app sends only the flags it knows; that must not switch clips on/off.
    client.put("/api/consent", json={"coughTracking": True}, headers=user)
    assert client.get("/api/consent", headers=user).json()["audioClips"] is False


def test_clip_round_trip_is_encrypted_and_pseudonymised(client, user):
    sid = synced(client, user)
    original = wav()
    r = upload(client, user, sid, data=original)
    assert r.status_code == 201, r.text
    anon_id = r.json()["clip_anon_id"]

    # Retrying the same upload is harmless.
    assert upload(client, user, sid).json()["clip_anon_id"] == anon_id

    # Encrypted on disk: not a readable WAV.
    path = clip_store._path_for(anon_id)
    with open(path, "rb") as f:
        assert not f.read().startswith(b"RIFF")

    # The clips database cannot identify anyone.
    cols = {c["name"] for c in inspect(clips_engine).get_columns("audio_clips")}
    assert not cols & {"user_id", "session_id", "email", "event_id", "timestamp"}

    # The owner gets the exact audio back; another user does not.
    got = client.get(f"/api/clips/{anon_id}", headers=user)
    assert got.status_code == 200 and got.content == original
    other = client.post("/api/auth/register", json={"email": "clip-other@test.dev", "password": "pw-123456"})
    assert client.get(f"/api/clips/{anon_id}",
                      headers={"Authorization": f"Bearer {other.json()['access']}"}).status_code == 404

    # Delete removes file, index row and link.
    assert client.delete(f"/api/clips/{anon_id}", headers=user).status_code == 204
    assert not os.path.exists(path)
    with ClipsSessionLocal() as cdb:
        assert cdb.get(AudioClip, anon_id) is None
    with SessionLocal() as db:
        assert db.scalar(select(CoughEvent).where(CoughEvent.clip_anon_id == anon_id)) is None


def test_measurements_from_the_clip(client, user):
    """Event 1 peaks at 22:15:03.600, so the phone's clip starts 750 ms earlier, at
    22:15:02.850. A 300 ms burst placed 400 ms into the clip is the "real" cough: it
    starts at 22:15:03.250 — between the detector's frame-grid start (03.120) and end."""
    sid = synced(client, user)
    anon_id = upload(client, user, sid, data=wav(burst=(0.400, 0.700))).json()["clip_anon_id"]
    f = client.get(f"/api/clips/{anon_id}/features", headers=user).json()
    assert len(f) == 1 and f[0]["method"] == "acoustic-v1"
    f = f[0]

    clip_start = datetime(2026, 10, 9, 22, 15, 2, 850_000, tzinfo=timezone.utc)
    start = datetime.fromisoformat(f["acoustic_start_at"])
    end = datetime.fromisoformat(f["acoustic_end_at"])
    # 10 ms envelope hop, 20 ms window: within 20 ms of the truth.
    assert abs((start - (clip_start + timedelta(milliseconds=400))).total_seconds()) <= 0.02
    assert abs((end - (clip_start + timedelta(milliseconds=700))).total_seconds()) <= 0.02
    assert abs(f["acoustic_duration_ms"] - 300) <= 30
    # Burst RMS 0.3 (-10.5 dBFS) over background 0.001 (-60 dBFS): ~50 dB prominence.
    assert 45 <= f["prominence_db"] <= 55
    assert -13 <= f["rms_dbfs"] <= -9
    assert f["peak_dbfs"] > f["rms_dbfs"]
    # White noise: centroid near a quarter of the sample rate, ~1/8 energy below 1 kHz.
    assert 3000 <= f["spectral_centroid_hz"] <= 5000
    assert 0.05 <= f["low_freq_ratio"] <= 0.2

    with SessionLocal() as db:
        ev = db.scalar(select(CoughEvent).where(CoughEvent.clip_anon_id == anon_id))
        assert ev.clip_started_at == clip_start


def test_explicit_clip_start_time_is_used(client, user):
    sid = synced(client, user)
    anon_id = upload(client, user, sid, data=wav(burst=(1.0, 1.2)),
                     clip_started_at="2026-10-09T22:15:02.500Z").json()["clip_anon_id"]
    f = client.get(f"/api/clips/{anon_id}/features", headers=user).json()[0]
    expected = datetime(2026, 10, 9, 22, 15, 3, 500_000, tzinfo=timezone.utc)
    assert abs((datetime.fromisoformat(f["acoustic_start_at"]) - expected).total_seconds()) <= 0.02


def test_recompute_job_measures_clips_without_features(client, user):
    from app.jobs import compute_features
    sid = synced(client, user)
    anon_id = upload(client, user, sid, data=wav(burst=(0.4, 0.7))).json()["clip_anon_id"]
    with SessionLocal() as db:
        event_id = db.scalar(select(CoughEvent.id).where(CoughEvent.clip_anon_id == anon_id))
        db.query(CoughEventFeatures).filter(CoughEventFeatures.event_id == event_id).delete()
        db.commit()
    compute_features.main()
    with SessionLocal() as db:
        assert db.scalar(select(CoughEventFeatures).where(CoughEventFeatures.event_id == event_id)) is not None


def test_long_or_wrong_audio_rejected(client, user):
    sid = synced(client, user)
    assert upload(client, user, sid, data=wav(6.0)).status_code == 422       # over the 5 s cap
    assert upload(client, user, sid, data=b"not audio at all").status_code == 422


def test_delete_all_clips(client, user):
    sid = synced(client, user)
    ids = [upload(client, user, sid, event_id=e).json()["clip_anon_id"] for e in ("1", "2")]
    assert client.delete("/api/clips", headers=user).status_code == 204
    for anon_id in ids:
        assert not os.path.exists(clip_store._path_for(anon_id))
    with ClipsSessionLocal() as cdb:
        assert cdb.scalars(select(AudioClip).where(AudioClip.anon_id.in_(ids))).all() == []


def test_per_session_cap(client, user, monkeypatch):
    monkeypatch.setattr(get_settings(), "clip_max_per_session", 1)
    sid = synced(client, user)
    assert upload(client, user, sid, event_id="1").status_code == 201
    assert upload(client, user, sid, event_id="2").status_code == 409


def test_retention_purge(client, user):
    sid = synced(client, user)
    anon_id = upload(client, user, sid).json()["clip_anon_id"]
    with ClipsSessionLocal() as cdb:
        cdb.execute(update(AudioClip).where(AudioClip.anon_id == anon_id)
                    .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        cdb.commit()
    assert client.get(f"/api/clips/{anon_id}", headers=user).status_code == 404
    with SessionLocal() as db, ClipsSessionLocal() as cdb:
        assert clip_store.purge_expired(db, cdb) >= 1
    assert not os.path.exists(clip_store._path_for(anon_id))
    with SessionLocal() as db:
        assert db.scalar(select(CoughEvent).where(CoughEvent.clip_anon_id == anon_id)) is None
