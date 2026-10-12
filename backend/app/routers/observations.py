"""
Individual health readings and the reports built on top of them.

  POST   /api/observations           – store readings (weight, blood pressure, ...)
  GET    /api/observations           – readings in time order, filterable by metric/time
  DELETE /api/observations/{ref}     – delete one reading (all values sharing that ref)
  GET    /api/reports/daily          – one number per user/day/metric (coughs and readings)
  GET    /api/reports/timeline       – coughs, snore episodes and readings in time order

Each reading keeps its exact time; many per day are normal. Values taken together
(systolic + diastolic + pulse) are sent as one reading and share its reading_id.
Metric codes and units: app/metrics.py.
"""
import math
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..auth import CurrentUser
from ..database import get_db
from ..metrics import METRICS, READING_METRICS
from ..models import HealthObservation

router = APIRouter(prefix="/api", tags=["observations"])


class ReadingValue(BaseModel):
    metric: str
    value: float
    # Optional; if given it must match the catalog unit (no silent conversions).
    unit: str | None = None

    @model_validator(mode="after")
    def _known_metric(self):
        if self.metric not in READING_METRICS:
            raise ValueError(f"unknown reading metric {self.metric!r}; see app/metrics.py")
        if not math.isfinite(self.value):
            raise ValueError("value must be a finite number")
        expected = METRICS[self.metric].unit
        if self.unit is not None and self.unit != expected:
            raise ValueError(f"{self.metric} is stored in {expected!r}, got {self.unit!r}")
        return self


class ReadingIn(BaseModel):
    # Client-chosen id: sending the same reading again (retry) updates instead of
    # duplicating. Generated if omitted.
    reading_id: str | None = Field(None, max_length=48)
    measured_at: AwareDatetime
    # For readings over a period (steps over a day).
    measured_until: AwareDatetime | None = None
    # IANA zone deciding the reading's calendar day. Defaults to the offset in measured_at.
    timezone: str | None = None
    source: str = Field("manual", max_length=32)
    values: list[ReadingValue] = Field(min_length=1, max_length=10)

    @field_validator("timezone")
    @classmethod
    def _known_tz(cls, v):
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(f"unknown timezone {v!r}")
        return v


class ReadingsIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=1000)


class ObservationOut(BaseModel):
    id: int
    reading_id: str | None
    metric: str
    value: float
    unit: str
    measured_at: datetime
    measured_until: datetime | None
    local_date: date
    source: str


def _local_date(r: ReadingIn) -> date:
    t = r.measured_at.astimezone(ZoneInfo(r.timezone)) if r.timezone else r.measured_at
    return t.date()


@router.post("/observations", response_model=list[ObservationOut], status_code=status.HTTP_201_CREATED)
def add_readings(body: ReadingsIn, current_user: CurrentUser, db: Session = Depends(get_db)):
    ids: list[int] = []
    for r in body.readings:
        ref = f"reading:{r.reading_id or uuid.uuid4().hex}"
        for v in r.values:
            stmt = pg_insert(HealthObservation).values(
                user_id=current_user.id, metric=v.metric, value=v.value, unit=METRICS[v.metric].unit,
                effective_start=r.measured_at, effective_end=r.measured_until,
                local_date=_local_date(r), source=r.source, source_ref=ref,
            )
            ids.append(db.scalar(stmt.on_conflict_do_update(
                constraint="uq_health_observations_user_metric_ref",
                set_={k: stmt.excluded[k] for k in
                      ("value", "effective_start", "effective_end", "local_date", "source")},
            ).returning(HealthObservation.id)))
    db.commit()
    rows = db.scalars(select(HealthObservation).where(HealthObservation.id.in_(ids))
                      .order_by(HealthObservation.effective_start, HealthObservation.metric))
    return [_out(o) for o in rows]


@router.get("/observations", response_model=list[ObservationOut])
def list_readings(
    current_user: CurrentUser,
    metric: list[str] | None = Query(None, description="Repeat to select several metrics"),
    since: AwareDatetime | None = Query(None, alias="from"),
    until: AwareDatetime | None = Query(None, alias="to"),
    limit: int = Query(1000, le=10000),
    db: Session = Depends(get_db),
):
    q = select(HealthObservation).where(HealthObservation.user_id == current_user.id)
    if metric:
        q = q.where(HealthObservation.metric.in_(metric))
    if since:
        q = q.where(HealthObservation.effective_start >= since)
    if until:
        q = q.where(HealthObservation.effective_start < until)
    q = q.order_by(HealthObservation.effective_start, HealthObservation.metric).limit(limit)
    return [_out(o) for o in db.scalars(q)]


@router.delete("/observations/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reading(reading_id: str, current_user: CurrentUser, db: Session = Depends(get_db)):
    res = db.execute(delete(HealthObservation).where(
        HealthObservation.user_id == current_user.id,
        HealthObservation.source_ref == f"reading:{reading_id}"))
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Reading not found")
    db.commit()


def _out(o: HealthObservation) -> ObservationOut:
    ref = o.source_ref or ""
    return ObservationOut(
        id=o.id, reading_id=ref.removeprefix("reading:") or None, metric=o.metric, value=o.value,
        unit=o.unit, measured_at=o.effective_start, measured_until=o.effective_end,
        local_date=o.local_date, source=o.source)


# ── Reports ────────────────────────────────────────────────────────────────────

class DailyValue(BaseModel):
    local_date: date
    metric: str
    unit: str
    # The day's number, combined as the catalog says (sum of steps, average weight, ...).
    value: float
    # How many readings (or nights) went into it, and the range across them.
    n: int
    min: float
    max: float
    first_at: datetime
    last_at: datetime


@router.get("/reports/daily", response_model=list[DailyValue])
def daily_report(
    current_user: CurrentUser,
    since: date = Query(..., alias="from"),
    until: date = Query(..., alias="to"),
    metric: list[str] | None = Query(None),
    db: Session = Depends(get_db),
):
    sql = ("SELECT * FROM daily_health_summary WHERE user_id = :uid "
           "AND local_date BETWEEN :since AND :until")
    params: dict = {"uid": current_user.id, "since": since, "until": until}
    if metric:
        sql += " AND metric = ANY(:metrics)"
        params["metrics"] = metric
    rows = db.execute(text(sql + " ORDER BY local_date, metric"), params).mappings()
    out = []
    for r in rows:
        agg = METRICS[r["metric"]].daily if r["metric"] in METRICS else "avg"
        out.append(DailyValue(
            local_date=r["local_date"], metric=r["metric"], unit=r["unit"],
            value=round(r[f"value_{agg}"], 3), n=r["n"], min=r["value_min"], max=r["value_max"],
            first_at=r["first_at"], last_at=r["last_at"]))
    return out


class TimelineItem(BaseModel):
    item_table: str
    item_id: int
    kind: str                 # cough | sneeze | snore_episode | body.weight | bp.systolic | ...
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    value: float | None       # readings and snore counts
    unit: str | None
    confidence: float | None  # coughs/sneezes: YAMNet peak score
    magnitude_db: float | None
    has_clip: bool
    counted: bool             # False when the user rejected the event
    session_id: int | None
    reading_ref: str | None


@router.get("/reports/timeline", response_model=list[TimelineItem])
def timeline_report(
    current_user: CurrentUser,
    since: AwareDatetime = Query(..., alias="from"),
    until: AwareDatetime = Query(..., alias="to"),
    kind: list[str] | None = Query(None),
    limit: int = Query(5000, le=20000),
    db: Session = Depends(get_db),
):
    sql = ("SELECT * FROM health_timeline WHERE user_id = :uid "
           "AND started_at >= :since AND started_at < :until")
    params: dict = {"uid": current_user.id, "since": since, "until": until, "limit": limit}
    if kind:
        sql += " AND kind = ANY(:kinds)"
        params["kinds"] = kind
    rows = db.execute(text(sql + " ORDER BY started_at, item_table, item_id LIMIT :limit"), params).mappings()
    return [TimelineItem(**{k: v for k, v in r.items() if k != "user_id"}) for r in rows]
