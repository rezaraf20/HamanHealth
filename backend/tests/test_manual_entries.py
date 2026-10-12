"""Sleep, weight, steps and medication doses the user types in themselves."""
from datetime import datetime, timedelta, timezone

from tests.test_cough_sync import night

TODAY = datetime.now(timezone.utc).date()


def log(client, user, day, values, reading_id=None):
    return client.post("/api/observations", headers=user, json={"readings": [{
        "reading_id": reading_id, "measured_at": f"{day}T12:00:00+00:00",
        "values": [{"metric": m, "value": v} for m, v in values.items()]}]})


def dashboard(client, user, query="range=7"):
    return client.get(f"/api/dashboard?{query}", headers=user).json()


def test_entered_numbers_are_kept_and_shown_on_the_dashboard(client, user):
    assert log(client, user, TODAY, {"sleep.duration": 7.5}).status_code == 201
    assert log(client, user, TODAY, {"body.weight": 80.4}).status_code == 201
    assert log(client, user, TODAY, {"activity.steps": 8000}).status_code == 201
    assert log(client, user, TODAY, {"medication.taken": 3, "medication.planned": 4}).status_code == 201

    dash = dashboard(client, user)
    today = dash["points"][-1]
    assert today["date"] == str(TODAY)
    assert (today["sleepHours"], today["weight"], today["steps"]) == (7.5, 80.4, 8000)
    assert (today["medsTaken"], today["medsPlanned"]) == (3, 4)
    assert dash["averages"] == {"coughs": 0.0, "weight": 80.4, "steps": 8000.0, "sleepHours": 7.5, "adherence": 0.75}

    stored = client.get("/api/observations", headers=user).json()
    assert {o["metric"]: o["value"] for o in stored} == {
        "sleep.duration": 7.5, "body.weight": 80.4, "activity.steps": 8000,
        "medication.taken": 3, "medication.planned": 4}
    assert {o["source"] for o in stored} == {"manual"}


def test_averages_only_count_days_that_have_an_entry(client, user):
    log(client, user, TODAY, {"sleep.duration": 8, "activity.steps": 10000})
    log(client, user, TODAY - timedelta(days=2), {"sleep.duration": 6, "activity.steps": 4000})
    avg = dashboard(client, user)["averages"]
    assert (avg["sleepHours"], avg["steps"]) == (7.0, 7000.0)  # not divided by all 7 days


def test_entering_the_same_day_again_corrects_it_instead_of_adding(client, user):
    log(client, user, TODAY, {"activity.steps": 3000}, reading_id=f"manual-activity-{TODAY}")
    log(client, user, TODAY, {"activity.steps": 9000}, reading_id=f"manual-activity-{TODAY}")
    assert dashboard(client, user)["points"][-1]["steps"] == 9000

    assert client.delete(f"/api/observations/manual-activity-{TODAY}", headers=user).status_code == 204
    assert dashboard(client, user)["points"][-1]["steps"] == 0


def test_entered_sleep_wins_over_microphone_hours_without_touching_coughs(client, user):
    client.post("/api/sessions/sync", json=night(), headers=user)  # 7 monitored hours, 3 coughs, 2026-10-10
    before = next(p for p in dashboard(client, user, "range=90")["points"] if p["date"] == "2026-10-10")
    assert (before["sleepHours"], before["coughs"]) == (7.0, 3)

    log(client, user, "2026-10-10", {"sleep.duration": 6.5})
    dash = dashboard(client, user, "range=90")
    after = next(p for p in dash["points"] if p["date"] == "2026-10-10")
    assert (after["sleepHours"], after["coughs"]) == (6.5, 3)
    assert dash["averages"]["coughs"] == 3.0  # one monitored night


def test_medication_adherence_never_exceeds_100_percent(client, user):
    log(client, user, TODAY, {"medication.taken": 5, "medication.planned": 4})
    assert dashboard(client, user)["averages"]["adherence"] == 1.0


def test_negative_and_unknown_values_are_refused(client, user):
    assert log(client, user, TODAY, {"body.weight": -70}).status_code == 422
    assert log(client, user, TODAY, {"sleep.quality": 5}).status_code == 422
    assert client.get("/api/observations", headers=user).json() == []


def test_dashboard_can_end_on_the_users_local_date(client, user):
    tomorrow = TODAY + timedelta(days=1)  # already "today" for someone east of UTC
    log(client, user, tomorrow, {"body.weight": 79})
    assert dashboard(client, user, f"range=7&today={tomorrow}")["points"][-1] == {
        "date": str(tomorrow), "coughs": 0, "sleepHours": 0.0, "weight": 79.0, "steps": 0,
        "medsTaken": 0, "medsPlanned": 0, "sneezes": 0, "snoreMinutes": 0.0}
    # A date far from the server's is ignored rather than trusted.
    assert dashboard(client, user, "range=7&today=2020-01-01")["points"][-1]["date"] == str(TODAY)
