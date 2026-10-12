from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..schemas import WebDashboardData, DailyPoint, ChangeCard, DashboardAverages

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=WebDashboardData)
def web_dashboard(
    days_range: int = Query(7, alias="range"),
    client_today: date | None = Query(None, alias="today", description="The user's local date"),
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    """
    Dashboard data for the web app (GET /api/dashboard?range=7|14|30).
    Read from the daily_health_summary view: a night counts on the day it ended
    (the morning the user woke up), weight is the day's average reading and steps the
    day's total. Sleep is what the user entered for that day, or else the hours the
    microphone listened. Medications are the doses the user entered as taken / planned.
    """
    days = max(1, min(days_range, 90))
    today = datetime.now(timezone.utc).date()
    # Readings are dated in the user's timezone, which can be a day ahead of or behind UTC.
    if client_today is not None and abs((client_today - today).days) <= 1:
        today = client_today
    first = today - timedelta(days=days - 1)

    rows = db.execute(text(
        "SELECT local_date, metric, value_sum, value_avg FROM daily_health_summary "
        "WHERE user_id = :uid AND local_date BETWEEN :first AND :today "
        "AND metric IN ('cough.count', 'monitoring.duration', 'body.weight', 'activity.steps', "
        "'sleep.duration', 'medication.taken', 'medication.planned', 'sneeze.count', 'snore.duration')"
    ), {"uid": current_user.id, "first": first, "today": today}).mappings()
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        value = r["value_avg"] if r["metric"] == "body.weight" else r["value_sum"]
        by_day.setdefault(str(r["local_date"]), {})[r["metric"]] = value

    # Build full date range (fill gaps with zeros)
    points: list[DailyPoint] = []
    monitored_nights = 0
    for i in range(days):
        day_str = str(first + timedelta(days=i))
        d = by_day.get(day_str, {})
        if "sleep.duration" in d:
            sleep = min(d["sleep.duration"], 24.0)
        else:
            sleep = min(d.get("monitoring.duration", 0.0), 12.0)
        if "cough.count" in d or d.get("monitoring.duration", 0.0) > 0:
            monitored_nights += 1
        points.append(DailyPoint(
            date=day_str,
            coughs=int(d.get("cough.count", 0)),
            sleepHours=round(sleep, 1),
            weight=round(d.get("body.weight", 0.0), 1),
            steps=int(d.get("activity.steps", 0)),
            medsTaken=int(d.get("medication.taken", 0)),
            medsPlanned=int(d.get("medication.planned", 0)),
            sneezes=int(d.get("sneeze.count", 0)),
            snoreMinutes=round(d.get("snore.duration", 0.0), 1),
        ))

    # Averages: each over the days that have a value, so days without an entry don't pull it down
    def mean(values: list[float], digits: int) -> float:
        return round(sum(values) / len(values), digits) if values else 0.0

    planned = sum(p.medsPlanned for p in points)
    averages = DashboardAverages(
        coughs=round(sum(p.coughs for p in points) / (monitored_nights or 1), 1),
        weight=mean([p.weight for p in points if p.weight > 0], 1),
        steps=mean([p.steps for p in points if p.steps > 0], 0),
        sleepHours=mean([p.sleepHours for p in points if p.sleepHours > 0], 1),
        adherence=round(min(sum(p.medsTaken for p in points) / planned, 1.0), 2) if planned else 0.0,
    )

    # Build change cards from real data
    changes: list[ChangeCard] = []
    half = days // 2
    if half > 0 and len(points) >= half * 2:
        first_half = points[:half]
        second_half = points[half:]
        avg_first = sum(p.coughs for p in first_half) / max(half, 1)
        avg_second = sum(p.coughs for p in second_half) / max(half, 1)
        delta = avg_second - avg_first
        if abs(delta) >= 1:
            direction = "up" if delta > 0 else "down"
            sign = "+" if delta > 0 else ""
            changes.append(ChangeCard(
                id="c_coughs",
                metric="coughs",
                title=f"Night coughs {'higher' if delta > 0 else 'lower'} this period",
                description=f"Average of {avg_second:.0f} per night versus {avg_first:.0f} the previous period.",
                direction=direction,
                deltaLabel=f"{sign}{delta:.0f} / night",
                since=f"vs. previous {half} nights",
            ))
        else:
            changes.append(ChangeCard(
                id="c_coughs",
                metric="coughs",
                title="Night coughs steady",
                description=f"Average of {avg_second:.0f} per night — similar to the previous period.",
                direction="steady",
                deltaLabel=f"±{abs(delta):.0f} / night",
                since=f"vs. previous {half} nights",
            ))

    return WebDashboardData(
        range=days,
        points=points,
        changes=changes,
        medications=[],
        averages=averages,
    )
