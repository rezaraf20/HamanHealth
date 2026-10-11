"""Cough module data integration.

- cough_sessions: recording context (status, timezone, device, mic route, noise floor,
  mic gaps, detector config) + one row per device session.
- cough_events: full event detail (end time, peak time, scores, magnitude, SNR, bout,
  attribution, user label, event type) + re-sync key.
- cough_event_features: new — measurements calculated from each event's audio clip.
- snore_episodes: new.
- health_observations: new — individual readings (weight, blood pressure, ...), many per day.
- user_consents: new — replaces the in-memory consent store; audio clips on by default.
- views: daily_health_summary (one row per user/day/metric, from coughs and readings)
  and health_timeline (coughs, snore episodes and readings in one time-ordered list).

All new columns are nullable or defaulted, so existing rows and clients are unaffected.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _fail_on_duplicates(sql: str, what: str) -> None:
    dupes = op.get_bind().execute(sa.text(sql)).fetchall()
    if dupes:
        raise RuntimeError(
            f"Cannot add unique constraint: duplicate {what} exist ({len(dupes)} groups, "
            f"e.g. {list(dupes[0])}). Resolve them, then re-run the migration."
        )


def upgrade() -> None:
    # ── cough_sessions ───────────────────────────────────────────────────────
    for col in (
        sa.Column("status", sa.String(16)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("device_model", sa.String(128)),
        sa.Column("app_version", sa.String(32)),
        sa.Column("audio_source", sa.String(64)),
        sa.Column("noise_floor_db", sa.Float()),
        sa.Column("mic_gap_ms", sa.BigInteger()),
        sa.Column("frames_seen", sa.BigInteger()),
        sa.Column("frames_inferred", sa.BigInteger()),
        sa.Column("detector_config", postgresql.JSONB()),
    ):
        op.add_column("cough_sessions", col)

    _fail_on_duplicates(
        "SELECT user_id, device_session_id FROM cough_sessions "
        "GROUP BY 1, 2 HAVING COUNT(*) > 1 LIMIT 5",
        "device sessions per user",
    )
    op.create_unique_constraint(
        "uq_cough_sessions_user_device_session", "cough_sessions", ["user_id", "device_session_id"])

    # ── cough_events ─────────────────────────────────────────────────────────
    op.add_column("cough_events", sa.Column(
        "event_type", sa.String(16), nullable=False, server_default="cough"))
    for col in (
        sa.Column("device_event_id", sa.String(64)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("peak_at", sa.DateTime(timezone=True)),
        sa.Column("mean_score", sa.Float()),
        sa.Column("peak_db", sa.Float()),
        sa.Column("snr_db", sa.Float()),
        sa.Column("bout_id", sa.Integer()),
        sa.Column("subject_label", sa.String(16)),
        sa.Column("subject_confidence", sa.Float()),
        sa.Column("user_label", sa.String(16)),
        sa.Column("has_device_clip", sa.Boolean()),
        sa.Column("clip_started_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("cough_events", col)
    op.add_column("cough_events", sa.Column(
        "duration_ms", sa.Integer(),
        sa.Computed('(EXTRACT(EPOCH FROM (ended_at - "timestamp")) * 1000)::integer', persisted=True)))

    op.create_unique_constraint(
        "uq_cough_events_session_device_event", "cough_events", ["session_id", "device_event_id"])
    _fail_on_duplicates(
        "SELECT clip_anon_id FROM cough_events WHERE clip_anon_id IS NOT NULL "
        "GROUP BY 1 HAVING COUNT(*) > 1 LIMIT 5",
        "clip_anon_id values",
    )
    op.create_unique_constraint("cough_events_clip_anon_id_key", "cough_events", ["clip_anon_id"])
    op.create_index("ix_cough_events_session_timestamp", "cough_events", ["session_id", "timestamp"])

    # ── cough_event_features ─────────────────────────────────────────────────
    op.create_table(
        "cough_event_features",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.BigInteger(),
                  sa.ForeignKey("cough_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("acoustic_start_at", sa.DateTime(timezone=True)),
        sa.Column("acoustic_end_at", sa.DateTime(timezone=True)),
        sa.Column("acoustic_duration_ms", sa.Integer()),
        sa.Column("peak_dbfs", sa.Float()),
        sa.Column("rms_dbfs", sa.Float()),
        sa.Column("prominence_db", sa.Float()),
        sa.Column("noise_floor_dbfs", sa.Float()),
        sa.Column("crest_factor_db", sa.Float()),
        sa.Column("spectral_centroid_hz", sa.Float()),
        sa.Column("low_freq_ratio", sa.Float()),
        sa.Column("zero_crossing_rate", sa.Float()),
        sa.UniqueConstraint("event_id", "method", name="uq_cough_event_features_event_method"),
    )
    op.create_index("ix_cough_event_features_event_id", "cough_event_features", ["event_id"])

    # ── snore_episodes ───────────────────────────────────────────────────────
    op.create_table(
        "snore_episodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("session_id", sa.BigInteger(),
                  sa.ForeignKey("cough_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snore_count", sa.Integer(), nullable=False),
        sa.Column("mean_intensity_db", sa.Float()),
        sa.UniqueConstraint("session_id", "started_at", name="uq_snore_episodes_session_start"),
    )
    op.create_index("ix_snore_episodes_session_id", "snore_episodes", ["session_id"])

    # ── health_observations ──────────────────────────────────────────────────
    op.create_table(
        "health_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("effective_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_end", sa.DateTime(timezone=True)),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "metric", "source_ref", name="uq_health_observations_user_metric_ref"),
    )
    op.create_index("ix_health_observations_user_id", "health_observations", ["user_id"])
    op.create_index("ix_health_observations_user_metric_date", "health_observations",
                    ["user_id", "metric", "local_date"])

    # ── user_consents ────────────────────────────────────────────────────────
    op.create_table(
        "user_consents",
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cough_tracking", sa.Boolean(), nullable=False),
        sa.Column("health_trends", sa.Boolean(), nullable=False),
        sa.Column("records_processing", sa.Boolean(), nullable=False),
        sa.Column("product_analytics", sa.Boolean(), nullable=False),
        sa.Column("audio_clips", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("audio_clips_changed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


    op.execute(DAILY_HEALTH_SUMMARY)
    op.execute(HEALTH_TIMELINE)


# An event counts toward the user's numbers unless the user rejected it. Same rule as
# services/cough_ingest.counts_for_user.
_COUNTED = "(e.user_label IS NULL OR e.user_label = 'subject')"

DAILY_HEALTH_SUMMARY = f"""
CREATE VIEW daily_health_summary AS
WITH nights AS (
    -- A night belongs to the local date it ended on (the morning the user woke up).
    SELECT s.id, s.user_id, s.started_at, s.ended_at,
           (s.ended_at AT TIME ZONE COALESCE(s.timezone, 'UTC'))::date AS local_date,
           GREATEST(0, EXTRACT(EPOCH FROM (s.ended_at - s.started_at))
                       - COALESCE(s.mic_gap_ms, 0) / 1000.0) / 3600.0 AS monitored_hours
    FROM cough_sessions s
    WHERE s.ended_at IS NOT NULL AND NOT COALESCE(s.is_active, false)
),
per_night AS (
    SELECT n.id, n.user_id, n.local_date, n.started_at, n.ended_at, n.monitored_hours,
           COUNT(e.id) FILTER (WHERE e.event_type = 'cough' AND {_COUNTED}) AS coughs,
           COUNT(e.id) FILTER (WHERE e.event_type = 'sneeze' AND {_COUNTED}) AS sneezes,
           -- coughs without a bout id (older clients) count as their own fit
           COUNT(DISTINCT e.bout_id) FILTER (WHERE e.event_type = 'cough' AND {_COUNTED})
             + COUNT(e.id) FILTER (WHERE e.event_type = 'cough' AND {_COUNTED} AND e.bout_id IS NULL) AS bouts,
           COALESCE((SELECT SUM(EXTRACT(EPOCH FROM (ep.ended_at - ep.started_at)))
                     FROM snore_episodes ep WHERE ep.session_id = n.id), 0) / 60.0 AS snore_minutes
    FROM nights n
    LEFT JOIN cough_events e ON e.session_id = n.id
    GROUP BY n.id, n.user_id, n.local_date, n.started_at, n.ended_at, n.monitored_hours
),
cough_days AS (
    SELECT user_id, local_date, COUNT(*) AS nights,
           SUM(coughs) AS coughs, SUM(sneezes) AS sneezes, SUM(bouts) AS bouts,
           SUM(snore_minutes) AS snore_minutes, SUM(monitored_hours) AS hours,
           MIN(started_at) AS first_at, MAX(ended_at) AS last_at
    FROM per_night GROUP BY user_id, local_date
)
SELECT d.user_id, d.local_date, m.metric::text AS metric, m.unit::text AS unit,
       d.nights AS n, m.value AS value_sum, m.value AS value_avg, m.value AS value_min,
       m.value AS value_max, m.value AS value_last, d.first_at, d.last_at
FROM cough_days d
CROSS JOIN LATERAL (VALUES
    ('cough.count', '{{count}}', d.coughs::float8),
    -- a rate over a few minutes of listening is noise, not a measurement
    ('cough.rate', '{{count}}/h', CASE WHEN d.hours >= 0.5
                                      THEN round((d.coughs / d.hours)::numeric, 2)::float8 END),
    ('cough.bouts', '{{count}}', d.bouts::float8),
    ('sneeze.count', '{{count}}', d.sneezes::float8),
    ('snore.duration', 'min', round(d.snore_minutes::numeric, 1)::float8),
    ('monitoring.duration', 'h', round(d.hours::numeric, 2)::float8)
) AS m(metric, unit, value)
WHERE m.value IS NOT NULL

UNION ALL

SELECT o.user_id, o.local_date, o.metric::text, o.unit::text,
       COUNT(*) AS n, SUM(o.value), AVG(o.value), MIN(o.value), MAX(o.value),
       (ARRAY_AGG(o.value ORDER BY o.effective_start DESC))[1],
       MIN(o.effective_start), MAX(COALESCE(o.effective_end, o.effective_start))
FROM health_observations o
GROUP BY o.user_id, o.local_date, o.metric, o.unit
"""

HEALTH_TIMELINE = f"""
CREATE VIEW health_timeline AS
SELECT s.user_id, 'cough_events'::text AS item_table, e.id AS item_id,
       e.event_type::text AS kind, e."timestamp" AS started_at, e.ended_at, e.duration_ms,
       NULL::float8 AS value, NULL::text AS unit,
       e.confidence::float8 AS confidence, e.peak_db::float8 AS magnitude_db,
       (e.clip_anon_id IS NOT NULL) AS has_clip, {_COUNTED} AS counted,
       e.session_id AS session_id, NULL::text AS reading_ref
FROM cough_events e JOIN cough_sessions s ON s.id = e.session_id

UNION ALL

SELECT s.user_id, 'snore_episodes', ep.id, 'snore_episode', ep.started_at, ep.ended_at,
       (EXTRACT(EPOCH FROM (ep.ended_at - ep.started_at)) * 1000)::integer,
       ep.snore_count::float8, '{{count}}', NULL, ep.mean_intensity_db::float8,
       false, true, ep.session_id, NULL
FROM snore_episodes ep JOIN cough_sessions s ON s.id = ep.session_id

UNION ALL

SELECT o.user_id, 'health_observations', o.id, o.metric::text, o.effective_start, o.effective_end,
       (EXTRACT(EPOCH FROM (o.effective_end - o.effective_start)) * 1000)::integer,
       o.value, o.unit::text, NULL, NULL, false, true, NULL, o.source_ref::text
FROM health_observations o
"""


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS health_timeline")
    op.execute("DROP VIEW IF EXISTS daily_health_summary")
    op.drop_table("user_consents")
    op.drop_table("health_observations")
    op.drop_table("snore_episodes")
    op.drop_table("cough_event_features")
    op.drop_index("ix_cough_events_session_timestamp", table_name="cough_events")
    op.drop_constraint("cough_events_clip_anon_id_key", "cough_events", type_="unique")
    op.drop_constraint("uq_cough_events_session_device_event", "cough_events", type_="unique")
    for col in ("duration_ms", "clip_started_at", "event_type", "device_event_id", "ended_at", "peak_at", "mean_score", "peak_db",
                "snr_db", "bout_id", "subject_label", "subject_confidence", "user_label",
                "has_device_clip"):
        op.drop_column("cough_events", col)
    op.drop_constraint("uq_cough_sessions_user_device_session", "cough_sessions", type_="unique")
    for col in ("status", "timezone", "device_model", "app_version", "audio_source",
                "noise_floor_db", "mic_gap_ms", "frames_seen", "frames_inferred", "detector_config"):
        op.drop_column("cough_sessions", col)
