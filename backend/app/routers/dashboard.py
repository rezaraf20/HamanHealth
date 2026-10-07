from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..models import CoughSession, CoughEvent
from ..schemas import WebDashboardData, DailyPoint, ChangeCard, DashboardAverages

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=WebDashboardData)
def web_dashboard(
    range: int = 7,
    current_user: CurrentUser = ...,
    db: Session = Depends(get_db),
):
    """
    Dashboard data for the web app (GET /api/dashboard?range=7|14|30).
    Returns per-day cough counts; weight/steps/meds are stubbed at 0
    until those data sources are added.
    """
    days = max(1, min(range, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Build date → cough_count map from real events
    rows = (
        db.query(
            cast(CoughEvent.timestamp, Date).label("day"),
            func.count(CoughEvent.id).label("coughs"),
        )
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .filter(
            CoughSession.user_id == current_user.id,
            CoughEvent.timestamp >= since,
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    cough_by_day = {str(r.day): r.coughs for r in rows}

    # Also pull session sleep hours per day
    sleep_rows = (
        db.query(
            cast(CoughSession.started_at, Date).label("day"),
            CoughSession.started_at,
            CoughSession.ended_at,
        )
        .filter(
            CoughSession.user_id == current_user.id,
            CoughSession.started_at >= since,
        )
        .all()
    )
    sleep_by_day: dict[str, float] = {}
    for r in sleep_rows:
        if r.ended_at and r.started_at:
            hours = round((r.ended_at - r.started_at).total_seconds() / 3600, 1)
            sleep_by_day[str(r.day)] = min(hours, 12.0)

    # Build full date range (fill gaps with zeros)
    points: list[DailyPoint] = []
    for i in range(days):
        day = (since + timedelta(days=i + 1)).date()
        day_str = str(day)
        points.append(DailyPoint(
            date=day_str,
            coughs=cough_by_day.get(day_str, 0),
            sleepHours=sleep_by_day.get(day_str, 0.0),
            weight=0.0,
            steps=0,
            medsTaken=0,
            medsPlanned=0,
        ))

    # Averages
    total_coughs = sum(p.coughs for p in points)
    days_with_data = sum(1 for p in points if p.coughs > 0 or p.sleepHours > 0) or 1
    avg_coughs = round(total_coughs / days_with_data, 1)
    avg_sleep = round(sum(p.sleepHours for p in points if p.sleepHours > 0) / days_with_data, 1)

    averages = DashboardAverages(
        coughs=avg_coughs,
        weight=0.0,
        steps=0.0,
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
