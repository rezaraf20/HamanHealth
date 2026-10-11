# Cough module data on the platform

How the on-device cough module's output, and health readings such as weight and blood
pressure, are stored in the platform backend. Also covers why it is shaped this way and
how to deploy it. Branch: `platform-cough-data` (based on `platform`).

---

## 1. The model in one picture

Two levels, the same for every kind of health data:

```
LEVEL 1 — everything that happened, each with its exact time  (stored)
  cough_events          one row per cough / sneeze: start, end, duration, scores, magnitude, clip
  cough_event_features  measurements from each cough's audio (ms-accurate boundaries, loudness, ...)
  snore_episodes        one row per run of snoring
  health_observations   one row per reading: weight 07:12, weight 21:40, BP 08:00, ...

LEVEL 2 — numbers per day  (calculated by the database, never stored)
  daily_health_summary  view: user × day × metric → value, count, min, max
  health_timeline       view: coughs, snore episodes and readings in one time-ordered list
```

Nothing at level 2 can drift out of sync with level 1. A label the user changes the next
morning ("that wasn't a cough") shows up in every report immediately.

---

## 2. The flow

```
Phone (CoughAnalysisModule)                        Backend (FastAPI)
───────────────────────────                        ─────────────────
Room DB ── PlatformPayload.build() ──────────►  POST /api/sessions/sync
                                                  cough_sessions, cough_events, snore_episodes
WAV clip per event (2.5 s, on by default) ───►  POST /api/sessions/{id}/events/{device_event_id}/clip
                                                  └─ encrypted file  /var/haman/clips/…
                                                  └─ index row       hamanclips.audio_clips (no user ids)
                                                  └─ measurements    cough_event_features
Weight / BP / … readings ────────────────────►  POST /api/observations → health_observations
                                                GET  /api/reports/daily | /api/reports/timeline
```

---

## 3. Tables

### `cough_sessions` (changed): one row per night
Added: `status` (running/complete/interrupted), `timezone` (IANA), `device_model`,
`app_version`, `audio_source`, `noise_floor_db`, `mic_gap_ms`, `frames_seen`,
`frames_inferred`, `detector_config` (JSONB), and the unique key `(user_id, device_session_id)`.
`event_count` = coughs the user did not reject (sneezes not included).

### `cough_events` (changed): one row per cough or sneeze
| column | meaning |
|---|---|
| `timestamp`, `ended_at` | start / end from the detector (on its 0.48 s frame grid) |
| `duration_ms` | calculated by the database from start/end |
| `peak_at` | start of the loudest analysis frame |
| `confidence`, `mean_score` | YAMNet score: peak and average over the event (0–1) |
| `peak_db`, `snr_db` | phone's magnitude: loudest frame in dBFS, and dB above room noise |
| `bout_id` | coughing fit the cough belongs to |
| `subject_label`, `subject_confidence` | model's guess: was it the user? |
| `user_label` | user's verdict: subject / other / not_an_event |
| `event_type` | cough / sneeze (existing rows became `cough`) |
| `clip_anon_id`, `clip_started_at` | link to the audio and its absolute start time |
| `device_event_id` | the phone's id; makes re-uploads safe |

Every report query must filter on `event_type` and leave out events the user rejected.
Use `services.cough_ingest.counts_for_user("cough")`; the views apply the same rule.

### `cough_event_features` (new): measurements from each cough's audio
Calculated on the server from the clip at upload. The method is versioned in the
`method` column (`acoustic-v1`), so an improved method adds rows next to the old ones.
`python -m app.jobs.compute_features [--all]` re-runs it over every stored clip; no app
release is needed.

| column | meaning |
|---|---|
| `acoustic_start_at`, `acoustic_end_at`, `acoustic_duration_ms` | boundaries from the audio envelope, 10 ms resolution (tested within ±20 ms) |
| `prominence_db` | **proposed magnitude**: loudest point minus the clip's own background. Doesn't depend on phone or mic gain |
| `peak_dbfs`, `rms_dbfs` | absolute levels (phone-dependent) |
| `noise_floor_dbfs` | background level in the clip |
| `crest_factor_db` | peak minus RMS: how explosive the sound is |
| `spectral_centroid_hz`, `low_freq_ratio`, `zero_crossing_rate` | sound character |

### `snore_episodes` (new)
`started_at`, `ended_at`, `snore_count`, `mean_intensity_db`. Individual snores (hundreds
a night) stay on the phone.

### `health_observations` (new): individual readings
One row per value at the moment it was measured; many per day is normal.
`metric` + `value` + `unit` (from `app/metrics.py`, UCUM units, LOINC codes), `effective_start`
(and `effective_end` for periods like steps), `local_date`, `source`, `source_ref`.
Values measured together share a reading id: one blood pressure reading is three rows
(`bp.systolic`, `bp.diastolic`, `heart.rate`) with the same `source_ref`. Sending the same
reading id again updates instead of duplicating.

### `user_consents` (new)
Replaces the in-memory consent dict, which was lost on restart and different in each
uvicorn worker. `audioClips` is **on by default**. Switching it off stops new uploads.
Stored clips stay until retention, or until the user calls `DELETE /api/clips`.
`PUT /api/consent` only changes the fields that are sent.

### Clips database `hamanclips.audio_clips` (new, separate)
`anon_id`, `event_type`, `duration_ms`, `sample_rate`, `size_bytes`, `confidence`,
`created_at`, `expires_at`. It has no user id, session id or event time; the only link is
`cough_events.clip_anon_id` in the main DB. Clip files are Fernet-encrypted (AES-128 +
HMAC) and named by `anon_id`.

### Views
- `daily_health_summary`: `user_id, local_date, metric, unit, n, value_sum, value_avg,
  value_min, value_max, value_last, first_at, last_at`. Cough metrics (`cough.count`,
  `cough.rate`, `cough.bouts`, `sneeze.count`, `snore.duration`, `monitoring.duration`)
  are calculated per night and dated by the **local date the night ended**. Readings are
  grouped per local day. `app/metrics.py` says which column is "the" daily value (steps:
  sum, weight: average, ...); `GET /api/reports/daily` applies it.
- `health_timeline`: `user_id, item_table, item_id, kind, started_at, ended_at,
  duration_ms, value, unit, confidence, magnitude_db, has_clip, counted, session_id, reading_ref`.

---

## 4. Endpoints added or changed

| | |
|---|---|
| `POST /api/sessions/sync` | same URL and shape; now stores every detail and merges re-uploads |
| `POST /api/sessions/{id}/events/{device_event_id}/clip` | upload a clip (multipart `file`, optional `clip_started_at`) |
| `GET /api/clips/{anon_id}` · `/features` | play a clip (owner only) · its measurements |
| `DELETE /api/clips/{anon_id}` · `DELETE /api/clips` | delete one / all of the user's clips |
| `POST/GET /api/observations`, `DELETE /api/observations/{reading_id}` | readings |
| `GET /api/reports/daily?from=&to=&metric=` | daily values, coughs and readings together |
| `GET /api/reports/timeline?from=&to=&kind=` | everything in time order |
| `GET /api/dashboard` | same response; now from the daily view: coughs on the wake-up day, real weight/steps |
| `GET /api/sessions/last/summary` | same response; hours on the user's clock, in night order |

---

## 5. Why not a separate database for cough events

Reports need to combine coughs with users, sessions and readings, and PostgreSQL can't
join across databases. One database is fast enough. Measured locally with 1,000 users
× 60 nights × 30 events (1.8 M cough rows) plus 120,000 readings:

- 30-day dashboard query for one user: **6.5 ms**
- 30-day timeline for one user: **~1 ms**
- the query plan uses the `(session_id, timestamp)` and `user_id` indexes

Partition `cough_events` by month once it passes ~100 M rows. That's a migration, not a
redesign. Audio is never in a database: the files are on a volume today, and only
`services/clip_store.py` touches them. Moving them to object storage (S3 / Hetzner) is
a change to that one module, and fits with the planned move of `/data/records`.

**Storage sizing:** a 2.5 s clip is 80 KB. At 30 coughs a night, 10,000 users and 90-day
retention that's ~2 TB of clips. If needed, compress on the phone (Opus, ~10× smaller)
or shorten retention (`clip_retention_days`).

---

## 6. Deploying

1. **Back up first:** `docker exec haman-db pg_dump -U haman hamanhealth > backup.sql`.
2. `git pull` this branch, then `docker compose -f deploy/docker-compose.haman.yml up -d --build haman-api`.
3. On start, `docker-entrypoint.sh` runs, in order:
   - `alembic upgrade head` on the main DB. Revision `0001` is a baseline that only
     creates what's missing, so it's safe on the existing server and needs no `alembic stamp`.
   - creates the `hamanclips` database and the clip encryption key if missing;
   - `alembic -n clips upgrade head`;
   - uvicorn, with the same flags as before.
4. **Back up the clip key:** `docker exec haman-api cat /var/haman/keys/clips.key`, or set
   `HAMAN_CLIPS_KEY` in `deploy/.env` before the first start. Without the key the clips
   can't be decrypted.
5. Daily cleanup in the host crontab:
   `15 4 * * * docker exec haman-api python -m app.jobs.purge_clips`.

`migrate_add_is_active.py` is covered by migration `0001` and can be deleted.
After a model change: `alembic revision --autogenerate -m "…"`, review it, commit it.

**Tests:** `backend/tests/` has 26 integration tests and needs a throwaway PostgreSQL:
`TEST_DATABASE_URL=… TEST_CLIPS_DATABASE_URL=… pytest backend/tests`.

---

## 7. Open points

- **Privacy texts**: onboarding, consent and session screens (EN + NL) say audio is never
  recorded or uploaded. With clips on by default this is no longer true, and the
  consent screen has no audio switch yet. This is postponed deliberately and needs
  frontend work plus a GDPR check (cough audio tied to an account is health data).
- **Android upload transport**: the Capacitor plugin (`CoughSessionPlugin`) isn't in the
  repo yet. The phone side produces the sync JSON (`PlatformPayload.buildJson`) and
  stores the clip path per event. The plugin has to send both with the user's token.
- Found in `platform` (unchanged here): health-record files live inside the container,
  with no volume, so a rebuild deletes them. `POST /api/auth/refresh` doesn't exist. The
  Notion page lists `/api/sessions/upload` and `/start`, and database `hamandb`; the code
  has `/sync`, `POST /api/sessions` and `hamanhealth`.
