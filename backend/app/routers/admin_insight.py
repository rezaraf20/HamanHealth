"""
Admin insight API — read-only views over data the platform already stores but never shows.

Everything here is a SELECT. No endpoint in this module writes, updates or deletes, and
the module adds no table and no migration: it can be deployed and rolled back freely.

Same gate as the rest of the admin API: is_admin=True on the User row plus the
X-Admin-Secret header (see routers/admin.py).

  GET /api/admin/insight/health     — did the nights complete, did the clips arrive
  GET /api/admin/insight/detector   — what the detector produced, and what users rejected
  GET /api/admin/insight/devices    — per phone model / app version / mic route
  GET /api/admin/insight/clips      — clip storage, retention and opt-outs
  GET /api/admin/insight/consent    — who consented to what
  GET /api/admin/insight/users/{id}/sessions — one user's nights, with the recording context
  GET /api/admin/insight/sessions/{id}       — one night, event by event
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.orm import Session

from ..clips_db import AudioClip, get_clips_db
from ..database import get_db
from ..models import CoughEvent, CoughEventFeatures, CoughSession, User, UserConsent
from .admin import AdminUser

router = APIRouter(prefix="/api/admin/insight", tags=["admin-insight"])


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


# ── 1. System health ─────────────────────────────────────────────────────────

class NightHealth(BaseModel):
    window_days: int
    sessions: int
    by_status: dict[str, int]
    # A night the app opened and never closed: phone died, app killed, sync lost.
    unfinished: int
    unfinished_pct: float | None
    # Nights whose recording was interrupted for more than a minute in total.
    with_mic_gaps: int
    median_mic_gap_ms: int | None
    # frames_inferred / frames_seen — below 1.0 means the detector could not keep up.
    median_frame_coverage: float | None


class ClipDelivery(BaseModel):
    window_days: int
    # The phone kept a clip for this event.
    events_with_device_clip: int
    # ...and it reached the server.
    events_with_stored_clip: int
    delivered_pct: float | None
    # Stored clips that have no measurements yet: the compute_features backlog.
    awaiting_features: int


class HealthReport(BaseModel):
    generated_at: datetime
    nights: list[NightHealth]
    clips: list[ClipDelivery]


@router.get("/health", response_model=HealthReport)
def system_health(
    _admin=AdminUser,
    db: Session = Depends(get_db),
    windows: str = Query("7,30,90", description="Comma-separated day windows."),
):
    """Whether nights completed and clips arrived. The first place to look when a user
    says "it recorded nothing last night"."""
    day_windows = [int(w) for w in windows.split(",") if w.strip().isdigit()][:5] or [30]

    nights: list[NightHealth] = []
    clips: list[ClipDelivery] = []

    for days in day_windows:
        since = _since(days)
        rows = db.execute(
            select(CoughSession.status, func.count(CoughSession.id))
            .where(CoughSession.started_at >= since)
            .group_by(CoughSession.status)
        ).all()
        by_status = {(s or "unknown"): n for s, n in rows}
        total = sum(by_status.values())
        unfinished = db.scalar(
            select(func.count(CoughSession.id)).where(
                CoughSession.started_at >= since, CoughSession.ended_at.is_(None))
        ) or 0
        with_gaps = db.scalar(
            select(func.count(CoughSession.id)).where(
                CoughSession.started_at >= since, CoughSession.mic_gap_ms > 60_000)
        ) or 0
        median_gap = db.scalar(
            select(func.percentile_cont(0.5).within_group(CoughSession.mic_gap_ms))
            .where(CoughSession.started_at >= since, CoughSession.mic_gap_ms.is_not(None))
        )
        coverage = db.scalar(
            select(func.percentile_cont(0.5).within_group(
                cast(CoughSession.frames_inferred, Float) / func.nullif(CoughSession.frames_seen, 0)))
            .where(CoughSession.started_at >= since, CoughSession.frames_seen > 0)
        )
        nights.append(NightHealth(
            window_days=days,
            sessions=total,
            by_status=by_status,
            unfinished=unfinished,
            unfinished_pct=_pct(unfinished, total),
            with_mic_gaps=with_gaps,
            median_mic_gap_ms=int(median_gap) if median_gap is not None else None,
            median_frame_coverage=round(float(coverage), 3) if coverage is not None else None,
        ))

        kept, stored = db.execute(
            select(
                func.count(case((CoughEvent.has_device_clip.is_(True), 1))),
                func.count(case((CoughEvent.clip_anon_id.is_not(None), 1))),
            )
            .join(CoughSession, CoughEvent.session_id == CoughSession.id)
            .where(CoughSession.started_at >= since)
        ).one()
        backlog = db.scalar(
            select(func.count(CoughEvent.id))
            .join(CoughSession, CoughEvent.session_id == CoughSession.id)
            .outerjoin(CoughEventFeatures, CoughEventFeatures.event_id == CoughEvent.id)
            .where(
                CoughSession.started_at >= since,
                CoughEvent.clip_anon_id.is_not(None),
                CoughEventFeatures.id.is_(None),
            )
        ) or 0
        clips.append(ClipDelivery(
            window_days=days,
            events_with_device_clip=kept or 0,
            events_with_stored_clip=stored or 0,
            delivered_pct=_pct(stored or 0, kept or 0),
            awaiting_features=backlog,
        ))

    return HealthReport(generated_at=datetime.now(timezone.utc), nights=nights, clips=clips)


# ── 2. Detector quality ──────────────────────────────────────────────────────

class DetectorReport(BaseModel):
    window_days: int
    events: int
    by_type: dict[str, int]
    # The user's own verdict. "not_an_event" is our only field measurement of false
    # positives, and "other" means it was someone else in the room.
    by_user_label: dict[str, int]
    labelled: int
    labelled_pct: float | None
    rejected_pct_of_labelled: float | None
    # Peak model score, bucketed. A detector drifting toward the threshold shows up here
    # before anyone complains.
    confidence_buckets: dict[str, int]
    median_confidence: float | None
    median_snr_db: float | None
    # Per night, over nights that recorded at least one event.
    median_events_per_night: float | None


@router.get("/detector", response_model=DetectorReport)
def detector_quality(
    _admin=AdminUser,
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=3650),
):
    """What the detector produced and what users said about it.

    `by_user_label` is the number that matters: every event a user marked
    "not_an_event" is a false positive observed in real use, on a real phone, in a real
    bedroom. No test set gives that.
    """
    since = _since(days)
    base = select(CoughEvent).join(CoughSession, CoughEvent.session_id == CoughSession.id).where(
        CoughSession.started_at >= since)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    by_type = dict(db.execute(
        select(CoughEvent.event_type, func.count(CoughEvent.id))
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.started_at >= since)
        .group_by(CoughEvent.event_type)
    ).all())

    label_rows = db.execute(
        select(CoughEvent.user_label, func.count(CoughEvent.id))
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.started_at >= since)
        .group_by(CoughEvent.user_label)
    ).all()
    by_user_label = {(lbl or "unlabelled"): n for lbl, n in label_rows}
    labelled = sum(n for lbl, n in by_user_label.items() if lbl != "unlabelled")
    rejected = by_user_label.get("not_an_event", 0)

    buckets = dict(db.execute(
        select(
            case(
                (CoughEvent.confidence < 0.3, "<0.3"),
                (CoughEvent.confidence < 0.5, "0.3-0.5"),
                (CoughEvent.confidence < 0.7, "0.5-0.7"),
                (CoughEvent.confidence < 0.9, "0.7-0.9"),
                else_=">=0.9",
            ).label("bucket"),
            func.count(CoughEvent.id),
        )
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.started_at >= since, CoughEvent.confidence.is_not(None))
        .group_by("bucket")
    ).all())

    med_conf = db.scalar(
        select(func.percentile_cont(0.5).within_group(CoughEvent.confidence))
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.started_at >= since, CoughEvent.confidence.is_not(None)))
    med_snr = db.scalar(
        select(func.percentile_cont(0.5).within_group(CoughEvent.snr_db))
        .join(CoughSession, CoughEvent.session_id == CoughSession.id)
        .where(CoughSession.started_at >= since, CoughEvent.snr_db.is_not(None)))
    med_per_night = db.scalar(
        select(func.percentile_cont(0.5).within_group(cast(CoughSession.event_count, Float)))
        .where(CoughSession.started_at >= since, CoughSession.event_count > 0))

    return DetectorReport(
        window_days=days,
        events=total,
        by_type=by_type,
        by_user_label=by_user_label,
        labelled=labelled,
        labelled_pct=_pct(labelled, total),
        rejected_pct_of_labelled=_pct(rejected, labelled),
        confidence_buckets=buckets,
        median_confidence=round(float(med_conf), 3) if med_conf is not None else None,
        median_snr_db=round(float(med_snr), 1) if med_snr is not None else None,
        median_events_per_night=round(float(med_per_night), 1) if med_per_night is not None else None,
    )


# ── 3. Devices ───────────────────────────────────────────────────────────────

class DeviceRow(BaseModel):
    device_model: str | None
    app_version: str | None
    audio_source: str | None
    sessions: int
    users: int
    total_events: int
    mean_events_per_night: float | None
    median_noise_floor_db: float | None
    median_mic_gap_ms: int | None
    median_frame_coverage: float | None
    last_seen_at: datetime | None


@router.get("/devices", response_model=list[DeviceRow])
def devices(
    _admin=AdminUser,
    db: Session = Depends(get_db),
    days: int = Query(90, ge=1, le=3650),
):
    """One row per phone model / app version / mic route.

    A model whose `mean_events_per_night` is near zero while others are not, or whose
    `median_frame_coverage` is well under 1.0, is a device problem rather than a quiet
    sleeper — which is the distinction nothing in the platform could make before.
    """
    since = _since(days)
    rows = db.execute(
        select(
            CoughSession.device_model,
            CoughSession.app_version,
            CoughSession.audio_source,
            func.count(CoughSession.id),
            func.count(func.distinct(CoughSession.user_id)),
            func.coalesce(func.sum(CoughSession.event_count), 0),
            func.avg(cast(CoughSession.event_count, Float)),
            func.percentile_cont(0.5).within_group(CoughSession.noise_floor_db),
            func.percentile_cont(0.5).within_group(CoughSession.mic_gap_ms),
            func.percentile_cont(0.5).within_group(
                cast(CoughSession.frames_inferred, Float) / func.nullif(CoughSession.frames_seen, 0)),
            func.max(CoughSession.started_at),
        )
        .where(CoughSession.started_at >= since)
        .group_by(CoughSession.device_model, CoughSession.app_version, CoughSession.audio_source)
        .order_by(func.count(CoughSession.id).desc())
    ).all()

    return [
        DeviceRow(
            device_model=m, app_version=v, audio_source=src,
            sessions=sessions, users=users, total_events=int(events or 0),
            mean_events_per_night=round(float(mean_ev), 1) if mean_ev is not None else None,
            median_noise_floor_db=round(float(noise), 1) if noise is not None else None,
            median_mic_gap_ms=int(gap) if gap is not None else None,
            median_frame_coverage=round(float(cov), 3) if cov is not None else None,
            last_seen_at=last,
        )
        for m, v, src, sessions, users, events, mean_ev, noise, gap, cov, last in rows
    ]


# ── 4. Clip storage ──────────────────────────────────────────────────────────

class ClipStorage(BaseModel):
    clips_enabled: bool
    stored_clips: int
    total_bytes: int
    total_mb: float
    median_duration_ms: int | None
    oldest_at: datetime | None
    newest_at: datetime | None
    expiring_within_7_days: int
    already_expired_awaiting_purge: int
    # From the main database: who turned clips off.
    users_with_clips_off: int
    users_with_consent_row: int


@router.get("/clips", response_model=ClipStorage)
def clip_storage(
    _admin=AdminUser,
    db: Session = Depends(get_db),
    clips_db: Session | None = Depends(get_clips_db),
):
    """What is actually stored, how big it is, and when it expires.

    Needed for the DPIA (what personal data exists, and since when) as much as for the
    storage bill. Answers "are clips switched on in this deployment" without a shell.
    """
    off = db.scalar(
        select(func.count(UserConsent.user_id)).where(UserConsent.audio_clips.is_(False))) or 0
    rows = db.scalar(select(func.count(UserConsent.user_id))) or 0

    if clips_db is None:
        return ClipStorage(
            clips_enabled=False, stored_clips=0, total_bytes=0, total_mb=0.0,
            median_duration_ms=None, oldest_at=None, newest_at=None,
            expiring_within_7_days=0, already_expired_awaiting_purge=0,
            users_with_clips_off=off, users_with_consent_row=rows,
        )

    now = datetime.now(timezone.utc)
    count, total_bytes, oldest, newest = clips_db.execute(
        select(func.count(AudioClip.anon_id), func.coalesce(func.sum(AudioClip.size_bytes), 0),
               func.min(AudioClip.created_at), func.max(AudioClip.created_at))
    ).one()
    median_ms = clips_db.scalar(
        select(func.percentile_cont(0.5).within_group(AudioClip.duration_ms)))
    soon = clips_db.scalar(
        select(func.count(AudioClip.anon_id)).where(
            AudioClip.expires_at > now, AudioClip.expires_at <= now + timedelta(days=7))) or 0
    overdue = clips_db.scalar(
        select(func.count(AudioClip.anon_id)).where(AudioClip.expires_at <= now)) or 0

    return ClipStorage(
        clips_enabled=True,
        stored_clips=count or 0,
        total_bytes=int(total_bytes or 0),
        total_mb=round(int(total_bytes or 0) / 1_048_576, 2),
        median_duration_ms=int(median_ms) if median_ms is not None else None,
        oldest_at=oldest,
        newest_at=newest,
        expiring_within_7_days=soon,
        already_expired_awaiting_purge=overdue,
        users_with_clips_off=off,
        users_with_consent_row=rows,
    )


# ── 5. Consent ───────────────────────────────────────────────────────────────

class ConsentReport(BaseModel):
    total_users: int
    users_with_consent_row: int
    users_without_consent_row: int
    accepted: int
    cough_tracking: int
    health_trends: int
    records_processing: int
    product_analytics: int
    audio_clips: int
    audio_clips_changed_by_user: int


@router.get("/consent", response_model=ConsentReport)
def consent_state(_admin=AdminUser, db: Session = Depends(get_db)):
    """Who agreed to what. The admin UI shows only a single accepted_at date; these are
    the five flags behind it."""
    total_users = db.scalar(select(func.count(User.id))) or 0
    counts = db.execute(
        select(
            func.count(UserConsent.user_id),
            func.count(case((UserConsent.accepted_at.is_not(None), 1))),
            func.count(case((UserConsent.cough_tracking.is_(True), 1))),
            func.count(case((UserConsent.health_trends.is_(True), 1))),
            func.count(case((UserConsent.records_processing.is_(True), 1))),
            func.count(case((UserConsent.product_analytics.is_(True), 1))),
            func.count(case((UserConsent.audio_clips.is_(True), 1))),
            func.count(case((UserConsent.audio_clips_changed_at.is_not(None), 1))),
        )
    ).one()
    rows, accepted, cough, trends, records, analytics, clips, clips_changed = counts

    return ConsentReport(
        total_users=total_users,
        users_with_consent_row=rows or 0,
        users_without_consent_row=total_users - (rows or 0),
        accepted=accepted or 0,
        cough_tracking=cough or 0,
        health_trends=trends or 0,
        records_processing=records or 0,
        product_analytics=analytics or 0,
        audio_clips=clips or 0,
        audio_clips_changed_by_user=clips_changed or 0,
    )


# ── 6. Drill-down ────────────────────────────────────────────────────────────

class SessionRow(BaseModel):
    id: int
    device_session_id: str
    started_at: datetime
    ended_at: datetime | None
    status: str | None
    timezone: str | None
    sensitivity: str | None
    event_count: int
    device_model: str | None
    app_version: str | None
    audio_source: str | None
    noise_floor_db: float | None
    mic_gap_ms: int | None
    frames_seen: int | None
    frames_inferred: int | None
    frame_coverage: float | None
    detector_config: dict | None
    synced_at: datetime | None


def _session_row(s: CoughSession) -> SessionRow:
    coverage = (
        round(s.frames_inferred / s.frames_seen, 3)
        if s.frames_seen and s.frames_inferred is not None else None
    )
    return SessionRow(
        id=s.id, device_session_id=s.device_session_id, started_at=s.started_at,
        ended_at=s.ended_at, status=s.status, timezone=s.timezone, sensitivity=s.sensitivity,
        event_count=s.event_count or 0, device_model=s.device_model, app_version=s.app_version,
        audio_source=s.audio_source, noise_floor_db=s.noise_floor_db, mic_gap_ms=s.mic_gap_ms,
        frames_seen=s.frames_seen, frames_inferred=s.frames_inferred, frame_coverage=coverage,
        detector_config=s.detector_config, synced_at=s.synced_at,
    )


@router.get("/users/{user_id}/sessions", response_model=list[SessionRow])
def user_sessions(
    user_id: int,
    _admin=AdminUser,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """One user's nights with the full recording context — the per-user drill-down the
    admin UI has no way to reach today."""
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    sessions = db.scalars(
        select(CoughSession).where(CoughSession.user_id == user_id)
        .order_by(CoughSession.started_at.desc()).offset(offset).limit(limit)
    ).all()
    return [_session_row(s) for s in sessions]


class EventRow(BaseModel):
    id: int
    device_event_id: str | None
    event_type: str
    timestamp: datetime
    ended_at: datetime | None
    duration_ms: int | None
    confidence: float | None
    mean_score: float | None
    peak_db: float | None
    snr_db: float | None
    bout_id: int | None
    subject_label: str | None
    subject_confidence: float | None
    user_label: str | None
    has_device_clip: bool | None
    clip_stored: bool
    feature_methods: list[str]


class SessionDetail(BaseModel):
    session: SessionRow
    user_id: int
    events: list[EventRow]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def session_detail(
    session_id: int,
    _admin=AdminUser,
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=2000),
):
    """One night, event by event — scores, loudness, the user's verdict, and whether the
    clip made it to the server."""
    s = db.get(CoughSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Session not found")

    events = db.scalars(
        select(CoughEvent).where(CoughEvent.session_id == session_id)
        .order_by(CoughEvent.timestamp).limit(limit)
    ).all()
    methods: dict[int, list[str]] = {}
    if events:
        for ev_id, method in db.execute(
            select(CoughEventFeatures.event_id, CoughEventFeatures.method)
            .where(CoughEventFeatures.event_id.in_([e.id for e in events]))
        ).all():
            methods.setdefault(ev_id, []).append(method)

    return SessionDetail(
        session=_session_row(s),
        user_id=s.user_id,
        events=[
            EventRow(
                id=e.id, device_event_id=e.device_event_id, event_type=e.event_type,
                timestamp=e.timestamp, ended_at=e.ended_at, duration_ms=e.duration_ms,
                confidence=e.confidence, mean_score=e.mean_score, peak_db=e.peak_db,
                snr_db=e.snr_db, bout_id=e.bout_id, subject_label=e.subject_label,
                subject_confidence=e.subject_confidence, user_label=e.user_label,
                has_device_clip=e.has_device_clip, clip_stored=e.clip_anon_id is not None,
                feature_methods=sorted(methods.get(e.id, [])),
            )
            for e in events
        ],
    )
