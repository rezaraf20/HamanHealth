from tests.test_cough_sync import night


def post(client, user, *readings):
    return client.post("/api/observations", json={"readings": list(readings)}, headers=user)


def test_many_weight_readings_in_one_day_form_a_timeline(client, user):
    r = post(client, user,
             {"measured_at": "2026-10-10T07:12:00+02:00", "values": [{"metric": "body.weight", "value": 82.4}]},
             {"measured_at": "2026-10-10T13:05:00+02:00", "values": [{"metric": "body.weight", "value": 83.0}]},
             {"measured_at": "2026-10-10T21:40:00+02:00", "values": [{"metric": "body.weight", "value": 83.3, "unit": "kg"}]})
    assert r.status_code == 201, r.text
    got = client.get("/api/observations?metric=body.weight", headers=user).json()
    assert [o["value"] for o in got] == [82.4, 83.0, 83.3]  # in time order, all kept
    assert {o["local_date"] for o in got} == {"2026-10-10"}

    day = client.get("/api/reports/daily?from=2026-10-10&to=2026-10-10", headers=user).json()
    w = next(d for d in day if d["metric"] == "body.weight")
    assert (w["n"], w["min"], w["max"]) == (3, 82.4, 83.3)
    assert w["value"] == round((82.4 + 83.0 + 83.3) / 3, 3)  # weight: daily average


def test_blood_pressure_values_stay_together_and_retries_do_not_duplicate(client, user):
    reading = {"reading_id": "bp-1", "measured_at": "2026-10-10T08:00:00+02:00",
               "values": [{"metric": "bp.systolic", "value": 128}, {"metric": "bp.diastolic", "value": 82},
                          {"metric": "heart.rate", "value": 64}]}
    post(client, user, reading)
    post(client, user, reading)  # network retry
    rows = client.get("/api/observations", headers=user).json()
    assert len(rows) == 3 and {r["reading_id"] for r in rows} == {"bp-1"}

    assert client.delete("/api/observations/bp-1", headers=user).status_code == 204
    assert client.get("/api/observations", headers=user).json() == []


def test_steps_are_summed_per_day(client, user):
    post(client, user,
         {"measured_at": "2026-10-10T09:00:00Z", "measured_until": "2026-10-10T12:00:00Z",
          "values": [{"metric": "activity.steps", "value": 3000}]},
         {"measured_at": "2026-10-10T12:00:00Z", "measured_until": "2026-10-10T18:00:00Z",
          "values": [{"metric": "activity.steps", "value": 4500}]})
    day = client.get("/api/reports/daily?from=2026-10-10&to=2026-10-10&metric=activity.steps", headers=user).json()
    assert [d["value"] for d in day] == [7500]


def test_reading_day_follows_the_users_timezone(client, user):
    # 23:30 UTC is already the next day in Amsterdam.
    post(client, user, {"measured_at": "2026-10-10T23:30:00Z", "timezone": "Europe/Amsterdam",
                        "values": [{"metric": "body.weight", "value": 80}]})
    assert client.get("/api/observations", headers=user).json()[0]["local_date"] == "2026-10-11"


def test_bad_readings_rejected(client, user):
    def status(values, at="2026-10-10T08:00:00Z"):
        return post(client, user, {"measured_at": at, "values": values}).status_code
    assert status([{"metric": "body.wieght", "value": 80}]) == 422              # typo in metric
    assert status([{"metric": "body.weight", "value": 176, "unit": "lb"}]) == 422  # no silent conversion
    assert status([{"metric": "cough.count", "value": 3}]) == 422               # derived, not a reading
    assert status([{"metric": "body.weight", "value": 80}], at="2026-10-10T08:00:00") == 422  # no timezone


def test_one_report_for_coughs_and_vitals(client, user):
    client.post("/api/sessions/sync", json=night(), headers=user)
    post(client, user, {"measured_at": "2026-10-10T07:30:00+02:00", "values": [{"metric": "body.weight", "value": 82}]})

    day = {d["metric"]: d["value"] for d in
           client.get("/api/reports/daily?from=2026-10-10&to=2026-10-10", headers=user).json()}
    assert day["cough.count"] == 3 and day["body.weight"] == 82

    dash = client.get("/api/dashboard?range=90", headers=user).json()
    p = next(p for p in dash["points"] if p["date"] == "2026-10-10")
    assert (p["coughs"], p["weight"]) == (3, 82.0)


def test_timeline_lists_every_cough_and_reading_in_order(client, user):
    client.post("/api/sessions/sync", json=night(), headers=user)
    post(client, user, {"measured_at": "2026-10-10T07:30:00+02:00", "values": [{"metric": "body.weight", "value": 82}]})
    items = client.get("/api/reports/timeline?from=2026-10-09T00:00:00Z&to=2026-10-11T00:00:00Z",
                       headers=user).json()
    assert [i["kind"] for i in items] == ["cough", "cough", "snore_episode", "cough", "sneeze", "body.weight"]
    first = items[0]
    assert first["duration_ms"] == 1440 and first["confidence"] == 0.91 and first["magnitude_db"] == -21.5
    assert items[-1]["value"] == 82 and items[-1]["unit"] == "kg"

    only_coughs = client.get("/api/reports/timeline?from=2026-10-09T00:00:00Z&to=2026-10-11T00:00:00Z&kind=cough",
                             headers=user).json()
    assert len(only_coughs) == 3
