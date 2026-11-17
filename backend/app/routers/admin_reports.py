"""Admin reports — aggregate numbers only, never one person's health data.

  GET /api/admin/reports/signups    — new users per day / week / month, with running total
  GET /api/admin/reports/activity   — daily active users, plus 24h / 7d / 30d active counts
  GET /api/admin/reports/retention  — weekly sign-up cohorts: share still active 1-4 weeks later
  GET /api/admin/reports/usage      — which features people use (nights, each measurement, uploads)
  GET /api/admin/reports/nights     — how nights are recorded: frequency, length, cough counts
  GET /api/admin/reports/export/{name}.csv — any of the above as CSV (every export is audited)

Definitions (the same everywhere, so numbers can be compared):
  * Dates and weeks are UTC; weeks start on Monday.
  * An "active" user did at least one of: started a night recording, saved a health
    reading, uploaded a health record.
  * Cough counts are the server's event_count (coughs only, minus events the user
    rejected), the same figure the user list shows.
"""
import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import Float, case, cast, func, literal, select, union_all
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db
from ..models import CoughSession, HealthObservation, User
from ..services.admin_security import audit
from .admin import AdminUser
from .records import HealthRecord

router = APIRouter(prefix="/api/admin/reports", tags=["admin-reports"])


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(dt: datetime) -> date:
    return dt.astimezone(timezone.utc).date()


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def _bucket_start(d: date, bucket: str) -> date:
    if bucket == "week":
        return _week_start(d)
    if bucket == "month":
        return d.replace(day=1)
    return d


def _next_bucket(d: date, bucket: str) -> date:
    if bucket == "week":
        return d + timedelta(days=7)
    if bucket == "month":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return d + timedelta(days=1)


def _activity():
    """(user_id, ts) for everything that counts as being active."""
    return union_all(
        select(CoughSession.user_id.label("user_id"), CoughSession.started_at.label("ts")),
        select(HealthObservation.user_id, HealthObservation.created_at),
        select(HealthRecord.user_id, HealthRecord.created_at),
    ).subquery("activity")


# ── 1. Sign-ups ──────────────────────────────────────────────────────────────

class SignupRow(BaseModel):
    period: date
    new_users: int
    total_users: int


@router.get("/signups", response_model=list[SignupRow])
def signups(_admin=AdminUser, db: Session = Depends(get_db),
            days: int = Query(90, ge=1, le=3650),
            bucket: str = Query("day", pattern="^(day|week|month)$")):
    since = _bucket_start(_day(_now() - timedelta(days=days)), bucket)
    before = db.scalar(select(func.count(User.id)).where(User.created_at < datetime.combine(
        since, datetime.min.time(), tzinfo=timezone.utc))) or 0
    created = db.scalars(select(User.created_at).where(User.created_at >= datetime.combine(
        since, datetime.min.time(), tzinfo=timezone.utc))).all()
    per: dict[date, int] = {}
    for c in created:
        k = _bucket_start(_day(c), bucket)
        per[k] = per.get(k, 0) + 1

    rows, cur, total, end = [], since, before, _day(_now())
    while cur <= end:
        total += per.get(cur, 0)
        rows.append(SignupRow(period=cur, new_users=per.get(cur, 0), total_users=total))
        cur = _next_bucket(cur, bucket)
    return rows


# ── 2. Activity ──────────────────────────────────────────────────────────────

class DailyActive(BaseModel):
    date: date
    active_users: int


class ActivityReport(BaseModel):
    active_24h: int
    active_7d: int
    active_30d: int
    # Share of the 30-day active users who were also active in the last 24 hours.
    stickiness_pct: float | None
    daily: list[DailyActive]


@router.get("/activity", response_model=ActivityReport)
def activity(_admin=AdminUser, db: Session = Depends(get_db), days: int = Query(30, ge=1, le=365)):
    act = _activity()
    now = _now()

    def distinct_since(delta: timedelta) -> int:
        return db.scalar(select(func.count(func.distinct(act.c.user_id))).where(act.c.ts >= now - delta)) or 0

    d1, d7, d30 = distinct_since(timedelta(hours=24)), distinct_since(timedelta(days=7)), distinct_since(timedelta(days=30))

    start = _day(now) - timedelta(days=days - 1)
    day_col = func.date(func.timezone("UTC", act.c.ts))
    counts = dict(db.execute(
        select(day_col, func.count(func.distinct(act.c.user_id)))
        .where(act.c.ts >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by(day_col)
    ).all())
    daily = [DailyActive(date=start + timedelta(days=i), active_users=counts.get(start + timedelta(days=i), 0))
             for i in range(days)]
    return ActivityReport(active_24h=d1, active_7d=d7, active_30d=d30,
                          stickiness_pct=_pct(d1, d30), daily=daily)


# ── 3. Retention ─────────────────────────────────────────────────────────────

class CohortRow(BaseModel):
    cohort_week: date
    users: int
    # Active in calendar week +1 … +4 after the sign-up week. None = that week is not over yet.
    week_1_pct: float | None
    week_2_pct: float | None
    week_3_pct: float | None
    week_4_pct: float | None


@router.get("/retention", response_model=list[CohortRow])
def retention(_admin=AdminUser, db: Session = Depends(get_db), weeks: int = Query(8, ge=1, le=52)):
    this_week = _week_start(_day(_now()))
    first = this_week - timedelta(weeks=weeks - 1)
    users = db.execute(select(User.id, User.created_at).where(User.created_at >= datetime.combine(
        first, datetime.min.time(), tzinfo=timezone.utc))).all()
    cohort_of = {uid: _week_start(_day(c)) for uid, c in users}

    act = _activity()
    week_col = func.date(func.date_trunc("week", func.timezone("UTC", act.c.ts)))
    active: dict[int, set[date]] = {}
    if cohort_of:
        for uid, wk in db.execute(
            select(act.c.user_id, week_col).where(act.c.user_id.in_(cohort_of.keys())).group_by(act.c.user_id, week_col)
        ).all():
            active.setdefault(uid, set()).add(wk)

    rows = []
    for i in range(weeks):
        wk = first + timedelta(weeks=i)
        members = [u for u, c in cohort_of.items() if c == wk]
        pcts: list[float | None] = []
        for k in range(1, 5):
            target = wk + timedelta(weeks=k)
            if target >= this_week or not members:   # not finished yet (or nobody to measure)
                pcts.append(None)
            else:
                pcts.append(_pct(sum(1 for u in members if target in active.get(u, set())), len(members)))
        rows.append(CohortRow(cohort_week=wk, users=len(members),
                              week_1_pct=pcts[0], week_2_pct=pcts[1], week_3_pct=pcts[2], week_4_pct=pcts[3]))
    return rows


# ── 4. Feature usage ─────────────────────────────────────────────────────────

class FeatureRow(BaseModel):
    feature: str
    users: int
    share_of_active_pct: float | None
    records: int


class UsageReport(BaseModel):
    window_days: int
    total_users: int
    active_users: int
    features: list[FeatureRow]


@router.get("/usage", response_model=UsageReport)
def usage(_admin=AdminUser, db: Session = Depends(get_db), days: int = Query(30, ge=1, le=3650)):
    since = _now() - timedelta(days=days)
    act = _activity()
    active = db.scalar(select(func.count(func.distinct(act.c.user_id))).where(act.c.ts >= since)) or 0
    total = db.scalar(select(func.count(User.id))) or 0

    feats: list[tuple[str, int, int]] = []
    n_users, n_rows = db.execute(
        select(func.count(func.distinct(CoughSession.user_id)), func.count(CoughSession.id))
        .where(CoughSession.started_at >= since)).one()
    feats.append(("night_recording", n_users, n_rows))
    for metric, u, n in db.execute(
        select(HealthObservation.metric, func.count(func.distinct(HealthObservation.user_id)), func.count(HealthObservation.id))
        .where(HealthObservation.created_at >= since).group_by(HealthObservation.metric)
        .order_by(func.count(func.distinct(HealthObservation.user_id)).desc())
    ).all():
        feats.append((f"reading:{metric}", u, n))
    r_users, r_rows = db.execute(
        select(func.count(func.distinct(HealthRecord.user_id)), func.count(HealthRecord.id))
        .where(HealthRecord.created_at >= since)).one()
    feats.append(("record_upload", r_users, r_rows))

    return UsageReport(window_days=days, total_users=total, active_users=active, features=[
        FeatureRow(feature=f, users=u, share_of_active_pct=_pct(u, active), records=n) for f, u, n in feats])


# ── 5. Nights ────────────────────────────────────────────────────────────────

class Bucket(BaseModel):
    bucket: str
    count: int


class NightsReport(BaseModel):
    window_days: int
    nights: int
    recording_users: int
    complete_pct: float | None
    median_night_hours: float | None
    nights_per_user: list[Bucket]
    coughs_per_night: list[Bucket]


def _histogram(values: list[int], edges: list[tuple[str, int, int | None]]) -> list[Bucket]:
    out = []
    for label, lo, hi in edges:
        out.append(Bucket(bucket=label, count=sum(1 for v in values if v >= lo and (hi is None or v <= hi))))
    return out


@router.get("/nights", response_model=NightsReport)
def nights(_admin=AdminUser, db: Session = Depends(get_db), days: int = Query(30, ge=1, le=3650)):
    since = _now() - timedelta(days=days)
    where = CoughSession.started_at >= since
    total, users, complete = db.execute(
        select(func.count(CoughSession.id), func.count(func.distinct(CoughSession.user_id)),
               func.count(case((CoughSession.status == "complete", 1)))).where(where)).one()
    hours = db.scalar(select(func.percentile_cont(0.5).within_group(
        cast(func.extract("epoch", CoughSession.ended_at - CoughSession.started_at), Float) / 3600.0))
        .where(where, CoughSession.ended_at.is_not(None)))
    per_user = [n for (n,) in db.execute(select(func.count(CoughSession.id)).where(where).group_by(CoughSession.user_id)).all()]
    coughs = [n or 0 for (n,) in db.execute(select(CoughSession.event_count).where(where, CoughSession.ended_at.is_not(None))).all()]
    return NightsReport(
        window_days=days, nights=total, recording_users=users,
        complete_pct=_pct(complete, total),
        median_night_hours=round(float(hours), 1) if hours is not None else None,
        nights_per_user=_histogram(per_user, [("1", 1, 1), ("2-3", 2, 3), ("4-7", 4, 7), ("8-14", 8, 14), ("15+", 15, None)]),
        coughs_per_night=_histogram(coughs, [("0", 0, 0), ("1-5", 1, 5), ("6-20", 6, 20), ("21-50", 21, 50), ("51+", 51, None)]),
    )


# ── CSV export ───────────────────────────────────────────────────────────────

def _safe(v):
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _flatten(name: str, data) -> tuple[list[str], list[list]]:
    if name in ("signups", "retention"):
        rows = [r.model_dump() for r in data]
        return list(rows[0].keys()) if rows else [], [list(r.values()) for r in rows]
    if name == "activity":
        return ["date", "active_users"], [[r.date, r.active_users] for r in data.daily]
    if name == "usage":
        return ["feature", "users", "share_of_active_pct", "records"], [
            [f.feature, f.users, f.share_of_active_pct, f.records] for f in data.features]
    if name == "nights":
        rows = [["nights_per_user", b.bucket, b.count] for b in data.nights_per_user]
        rows += [["coughs_per_night", b.bucket, b.count] for b in data.coughs_per_night]
        return ["histogram", "bucket", "count"], rows
    raise HTTPException(status_code=404, detail="Unknown report")


@router.get("/export/{name}.csv")
def export_csv(name: str, request: Request, _admin=AdminUser, db: Session = Depends(get_db),
               days: int | None = Query(None, ge=1, le=3650),
               bucket: str = Query("day", pattern="^(day|week|month)$"),
               weeks: int = Query(8, ge=1, le=52)):
    if name == "signups":
        data, params = signups(_admin, db, days or 90, bucket), {"days": days or 90, "bucket": bucket}
    elif name == "activity":
        data, params = activity(_admin, db, days or 30), {"days": days or 30}
    elif name == "retention":
        data, params = retention(_admin, db, weeks), {"weeks": weeks}
    elif name == "usage":
        data, params = usage(_admin, db, days or 30), {"days": days or 30}
    elif name == "nights":
        data, params = nights(_admin, db, days or 30), {"days": days or 30}
    else:
        raise HTTPException(status_code=404, detail="Unknown report")

    header, rows = _flatten(name, data)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(c) for c in r])
    audit(db, _admin, "report.export", request, "report", name, {"params": params, "rows": len(rows)})
    db.commit()
    return Response(
        content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="haman-{name}-{_day(_now())}.csv"'})
