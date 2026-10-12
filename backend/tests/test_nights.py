"""What the web app shows about a night: coughs, sneezes, snoring and the audio clips."""
from tests.test_clips import upload, wav
from tests.test_cough_sync import night


def sync(client, user, **overrides) -> int:
    r = client.post("/api/sessions/sync", json=night(**overrides), headers=user)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_night_list_counts_coughs_sneezes_snoring_and_clips(client, user):
    sid = sync(client, user)
    assert upload(client, user, sid, "1", wav(burst=(0.75, 1.1))).status_code == 201

    nights = client.get("/api/sessions/nights", headers=user).json()
    assert len(nights) == 1
    n = nights[0]
    assert (n["id"], n["source"], n["date"], n["timezone"]) == (sid, "app", "2026-10-10", "Europe/Amsterdam")
    assert (n["coughs"], n["sneezes"], n["snoreMinutes"], n["clips"]) == (3, 1, 30.0, 1)


def test_night_detail_lists_every_event_in_order_with_its_clip(client, user):
    sid = sync(client, user)
    clip_id = upload(client, user, sid, "4", wav(burst=(0.75, 1.1))).json()["clip_anon_id"]  # the sneeze

    d = client.get(f"/api/sessions/nights/{sid}", headers=user).json()
    assert [(e["type"], e["clipId"]) for e in d["events"]] == [
        ("cough", None), ("cough", None), ("cough", None), ("sneeze", clip_id)]
    assert [e["at"] for e in d["events"]] == sorted(e["at"] for e in d["events"])
    first = d["events"][0]
    assert (first["durationMs"], first["confidence"], first["loudnessDb"], first["counted"]) == (1440, 0.91, -21.5, True)
    assert d["snoreEpisodes"] == [{"startedAt": "2026-10-10T00:00:00Z", "endedAt": "2026-10-10T00:30:00Z",
                                   "snoreCount": 400, "meanIntensityDb": -40.0}]
    # The clip id from the list is what plays the audio back.
    assert client.get(f"/api/clips/{clip_id}", headers=user).headers["content-type"] == "audio/wav"


def test_events_the_user_rejected_are_listed_but_not_counted(client, user):
    body = night()
    body["events"][1]["user_label"] = "not_an_event"
    body["events"][3]["user_label"] = "other"  # the sneeze was someone else
    sid = client.post("/api/sessions/sync", json=body, headers=user).json()["id"]

    d = client.get(f"/api/sessions/nights/{sid}", headers=user).json()
    assert (d["coughs"], d["sneezes"]) == (2, 0)
    assert [e["counted"] for e in d["events"]] == [True, False, True, False]
    assert len(d["events"]) == 4  # still shown, so the user can see what was heard


def test_nights_are_newest_first_and_web_sessions_are_marked(client, user):
    older = sync(client, user)
    newer = sync(client, user, device_session_id="18", started_at="2026-10-10T21:00:00.000Z",
                 ended_at="2026-10-11T05:00:00.000Z", events=[], snore_episodes=[])
    web = client.post("/api/sessions", json={"sensitivity": "medium"}, headers=user).json()["id"]

    nights = client.get("/api/sessions/nights", headers=user).json()
    assert [n["id"] for n in nights] == [int(web), newer, older]
    assert [n["source"] for n in nights] == ["web", "app", "app"]
    assert (nights[1]["coughs"], nights[1]["sneezes"], nights[1]["snoreMinutes"], nights[1]["clips"]) == (0, 0, 0.0, 0)
    assert len(client.get("/api/sessions/nights?limit=2", headers=user).json()) == 2


def test_a_night_is_private_to_its_owner(client, user):
    sid = sync(client, user)
    other = client.post("/api/auth/register", json={"email": "nosy-night@test.dev", "password": "pw-123456"})
    other_headers = {"Authorization": f"Bearer {other.json()['access']}"}
    assert client.get(f"/api/sessions/nights/{sid}", headers=other_headers).status_code == 404
    assert client.get("/api/sessions/nights", headers=other_headers).json() == []
    assert client.get(f"/api/sessions/nights/{sid}").status_code == 401


def test_summary_and_dashboard_include_sneezes_and_snoring(client, user):
    empty = client.get("/api/sessions/last/summary", headers=user).json()
    assert (empty["sessionId"], empty["sneezes"], empty["snoreMinutes"], empty["clips"]) == (None, 0, 0.0, 0)

    sid = sync(client, user)
    s = client.get("/api/sessions/last/summary", headers=user).json()
    assert (s["sessionId"], s["coughs"], s["sneezes"], s["snoreMinutes"]) == (sid, 3, 1, 30.0)

    dash = client.get("/api/dashboard?range=90", headers=user).json()
    p = next(p for p in dash["points"] if p["date"] == "2026-10-10")
    assert (p["coughs"], p["sneezes"], p["snoreMinutes"]) == (3, 1, 30.0)
