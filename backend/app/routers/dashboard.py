from datetime import datetime, timedelta, timezone
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
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    """
    Dashboard data for the web app (GET /api/dashboard?range=7|14|30).
    Read from the daily_health_summary view: a night counts on the day it ended
    (the morning the user woke up), weight is the day's average reading and steps the
    day's total. Medications are not tracked yet and stay 0.
    """
    days = max(1, min(days_range, 90))
    today = datetime.now(timezone.utc).date()
    first = today - timedelta(days=days - 1)

    rows = db.execute(text(
        "SELECT local_date, metric, value_sum, value_avg FROM daily_health_summary "
        "WHERE user_id = :uid AND local_date BETWEEN :first AND :today "
        "AND metric IN ('cough.count', 'monitoring.duration', 'body.weight', 'activity.steps')"
    ), {"uid": current_user.id, "first": first, "today": today}).mappings()
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        value = r["value_avg"] if r["metric"] == "body.weight" else r["value_sum"]
        by_day.setdefault(str(r["local_date"]), {})[r["metric"]] = value

    # Build full date range (fill gaps with zeros)
    points: list[DailyPoint] = []
    for i in range(days):
        day_str = str(first + timedelta(days=i))
        d = by_day.get(day_str, {})
        points.append(DailyPoint(
            date=day_str,
            coughs=int(d.get("cough.count", 0)),
            sleepHours=round(min(d.get("monitoring.duration", 0.0), 12.0), 1),
            weight=round(d.get("body.weight", 0.0), 1),
            steps=int(d.get("activity.steps", 0)),
            medsTaken=0,
            medsPlanned=0,
        ))

    # Averages
    total_coughs = sum(p.coughs for p in points)
    days_with_data = sum(1 for p in points if p.coughs > 0 or p.sleepHours > 0) or 1
    avg_coughs = round(total_coughs / days_with_data, 1)
    avg_sleep = round(sum(p.sleepHours for p in points if p.sleepHours > 0) / days_with_data, 1)

    weights = [p.weight for p in points if p.weight > 0]
    steps = [p.steps for p in points if p.steps > 0]
    averages = DashboardAverages(
        coughs=avg_coughs,
        weight=round(sum(weights) / len(weights), 1) if weights else 0.0,
        steps=round(sum(steps) / len(steps), 0) if steps else 0.0,
        sleepHours=avg_sleep,
        adherence=0.0,
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
