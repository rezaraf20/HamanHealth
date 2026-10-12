# Task: make the Android app upload nights and clips to the platform

**For:** Behzad (or a coding agent working in his checkout).
**Branch to work on:** `CoughAnalysisModule` (the Android app under `CoughAnalysisModule/android`).
**Do not change:** the backend. It is finished, deployed, and was verified end to end on
production on 2026-10-12 with exactly the requests described below.

---

## 1. Why

The backend stores coughs, sneezes, snoring episodes and short audio clips, and the web
app shows them (home page, **Night sounds** page with clip playback, Trends, admin panel).
Nothing arrives, because the Android app has no network code at all: the manifest has no
`INTERNET` permission, there is no HTTP client, no login, and `PlatformPayload.build()`
is only called from `DatabaseIntegrityTest`. The production database currently holds
**zero** clips, sneezes and snore episodes.

This task adds the missing transport: sign in, upload each finished night, upload its
clips, retry until done.

## 2. What "done" means

1. A user signs in to the app with their Haman Health account (email + password).
2. When a night ends (status `complete` or `interrupted`), the app uploads it without the
   user doing anything, as soon as there is a network connection.
3. Each cough and sneeze that has a clip on the phone gets that clip uploaded, unless the
   user switched clips off.
4. If the phone is offline, the app is killed, or the server is down, the upload happens
   later. Nothing is lost and nothing is duplicated.
5. If the user labels an event after the night was uploaded ("not a cough", "someone
   else"), the night is uploaded again so the server gets the label.
6. The night appears in the web app at `https://app.hamanhealth.com/nights` with its
   coughs, sneezes, snoring and playable clips.

## 3. The API (all of it already exists)

Base URL: `https://api.hamanhealth.com`. Put it in a `BuildConfig` field
(`PLATFORM_BASE_URL`), not in scattered string literals. JSON bodies use
`Content-Type: application/json`. Authenticated calls send `Authorization: Bearer <access>`.

### 3.1 Sign in

```
POST /api/auth/login
{"email": "...", "password": "..."}

200 {"access": "<jwt>", "refresh": "<jwt>", "token_type": "bearer", "requires2fa": false}
401 {"detail": "Invalid credentials"}
```

- The access token is valid for 30 days. `POST /api/auth/refresh {"refresh": "<jwt>"}`
  returns a fresh pair (same response shape) or 401.
- `GET /api/auth/me` returns `{id, email, name, ...}`; use it to show who is signed in.
- Accounts are created in the web app (`https://app.hamanhealth.com/auth/register`).
  Do not build registration into the Android app.
- Never store the password. Store the two tokens encrypted (Android Keystore-backed,
  e.g. `EncryptedSharedPreferences` or a Keystore-wrapped key). The existing `Prefs`
  class is plain `SharedPreferences` and must not hold tokens.

### 3.2 Upload a night

```
POST /api/sessions/sync        body = PlatformContract.encode(PlatformPayload.build(db, sessionId, prefs.installId()))

201 {"id": 4, "device_session_id": "<installId>:<roomId>", "started_at": "...", "ended_at": "...",
     "sensitivity": "medium", "event_count": 2, "synced_at": "...", "note": null}
```

- `id` in the response is the **server session id**. Keep it: clip uploads need it.
- The call is idempotent. Sending the same `device_session_id` again merges: events are
  matched on `device_event_id`, new ones added, `user_label` updated. So a retry after a
  timeout, or a re-upload after the user labels something, is always safe.
- Limits per request: 5000 events, 500 snore episodes. `PlatformPayload` already sends
  only coughs and sneezes as events (`PlatformContract.UPLOADED_CLASSES`) and snoring as
  episodes; keep that.
- Only upload sessions that are finished (`status` is `complete` or `interrupted`).
- A 422 means the payload broke the contract. That is a bug to fix, not something to
  retry. Log the response body.

Verified example (this exact body returned 201 on production):

```json
{"device_session_id":"check-1","started_at":"2026-10-11T21:00:00.000Z","ended_at":"2026-10-12T05:00:00.000Z",
 "status":"complete","timezone":"Asia/Tehran","sensitivity":"medium","device_model":"deploy-check","app_version":"0.2.0",
 "audio_source":"CAMCORDER@48k","noise_floor_db":-62.5,"mic_gap_ms":0,"frames_seen":60000,"frames_inferred":21000,
 "events":[
  {"device_event_id":"1","event_type":"cough","timestamp":"2026-10-11T22:15:03.120Z","ended_at":"2026-10-11T22:15:04.560Z","peak_at":"2026-10-11T22:15:03.600Z","confidence":0.91,"mean_score":0.7,"peak_db":-21.5,"snr_db":38.0,"bout_id":1,"subject_label":"subject","subject_confidence":0.8,"has_device_clip":true},
  {"device_event_id":"3","event_type":"sneeze","timestamp":"2026-10-12T01:02:00.000Z","ended_at":"2026-10-12T01:02:01.440Z","peak_at":"2026-10-12T01:02:00.500Z","confidence":0.8,"mean_score":0.6,"peak_db":-18.0,"snr_db":40.0,"subject_label":"unknown","subject_confidence":0.5,"has_device_clip":true}],
 "snore_episodes":[{"started_at":"2026-10-12T02:00:00.000Z","ended_at":"2026-10-12T02:20:00.000Z","snore_count":140,"mean_intensity_db":-35.0}]}
```

### 3.3 Upload a clip

```
POST /api/sessions/{serverSessionId}/events/{deviceEventId}/clip
multipart/form-data, one part named "file" (the WAV, content type audio/wav)

201 {"clip_anon_id": "1a6d642ded2c41649014d78e5066ff85"}
```

- `{deviceEventId}` is the same string sent as `device_event_id` in the night, i.e. the
  Room event id (`EventEntity.id.toString()`).
- The night must be uploaded first; otherwise 404 `Event not found — sync the session first`.
- Accepted audio: mono, 16-bit PCM WAV, 8–48 kHz, at most 5 s and 1 MB. The app's clips
  (2.5 s, written by `WavWriter`) fit. Do not re-encode them.
- Do not send `clip_started_at`. The server derives it from the event's `peak_at` and
  `PlatformContract.CLIP_PRE_ROLL_MS`.
- Idempotent: uploading a clip for an event that already has one returns the existing id.
- Responses and what to do:

| status | meaning | action |
|---|---|---|
| 201 | stored | mark the clip uploaded |
| 401 | token invalid | refresh once, retry; if refresh fails, stop and ask the user to sign in |
| 403 | user switched clips off | stop uploading clips for this user; do not retry |
| 404 | night or event unknown to the server | upload the night again, then retry once |
| 409 | 500-clip limit for this night reached | mark the night's remaining clips as skipped |
| 422 | file rejected (not a valid short WAV) | mark this clip failed permanently; do not retry |
| 503 | clips disabled on the server | retry later |
| 5xx, timeout, no network | transient | retry with backoff |

### 3.4 Consent

`GET /api/consent` (with the token) returns `{..., "audioClips": true|false, ...}`.
Clips are on by default. Check it before uploading a night's clips and skip them when it
is `false`; the 403 above is the safety net, not the mechanism. The user changes this in
the web app under Account → Privacy.

### 3.5 Checking the result

- `GET /api/sessions/nights` — the user's nights with `coughs`, `sneezes`,
  `snoreMinutes`, `clips`.
- `GET /api/sessions/nights/{id}` — every event with its `clipId`, and the snore episodes.
- `GET /api/clips/{clipId}` — the WAV back (owner only).

## 4. What to build in the app

Work with the existing structure; do not reorganise it.

1. **Manifest:** add `android.permission.INTERNET` and `ACCESS_NETWORK_STATE`.
2. **HTTP client:** one small class (e.g. `com.haman.sleep.sync.PlatformApi`) wrapping the
   four calls above. OkHttp is fine; add it through `gradle/libs.versions.toml` like the
   other dependencies. Timeouts: 15 s connect, 60 s read/write. HTTPS only (no cleartext).
3. **Token store:** encrypted, as in 3.1. Expose `isSignedIn`, `save(tokens)`, `clear()`.
4. **Sign-in UI:** a section in `SettingsScreen` (email, password, Sign in; when signed
   in: the account email and Sign out). Signing out clears the tokens and stops uploads;
   it does not delete local nights.
5. **Upload state, persisted in Room.** The app must remember, across restarts:
   - per session: the server session id, when it was last uploaded, and whether it
     changed since (a label was added or cleared);
   - per event: whether its clip was uploaded, failed permanently, or was skipped.
   Either add columns or a separate table. This is a schema change: bump
   `HamanDatabase` to version 3, write the `Migration(2, 3)`, commit the exported
   `schemas/.../3.json`, and extend `DatabaseIntegrityTest` to cover the migration.
6. **Clip paths for upload:** `EventDao.forUpload` returns `hasClip` but not the path.
   Add a query that returns `(id, clipPath)` for a session's events of the uploaded
   classes where `clipPath IS NOT NULL` and the clip is not yet uploaded.
7. **The worker:** a `CoroutineWorker` (WorkManager), unique work per session
   (`"platform-sync-<sessionId>"`, `ExistingWorkPolicy.KEEP` or `REPLACE` as fits),
   constraint `NetworkType.CONNECTED`, exponential backoff. Steps:
   1. if not signed in, finish (the work is enqueued again after sign-in);
   2. upload the night, store the server id;
   3. if `audioClips` is on and the app's own "Keep audio clips" setting is on, upload
      each pending clip, marking each one as it succeeds so a restart continues where it
      stopped;
   4. return `Result.retry()` on transient failures, `Result.success()` otherwise.
8. **When to enqueue:**
   - in `MonitoringService`, right after `db.sessions().finish(...)`;
   - in `MainViewModel.init`, after reconciling sessions left `running`, for every
     finished session that was never uploaded or changed since (this also uploads nights
     recorded before this feature existed);
   - in `MainViewModel.label()` / `clearLabel()` for that event's session;
   - after a successful sign-in, for everything pending.
9. **Local retention:** `applyRetention` deletes clip files after `retentionDays`
   (default 14). Uploading happens long before that; no change needed, but the worker
   must treat a missing file as "skipped", not as an error to retry forever.
10. **Show the state:** in `HistoryScreen` / `SessionDetailScreen`, a small line per
    night: "Uploaded", "Waiting for network", "Sign in to upload", or the error.
11. **Version:** `versionCode = 3`, `versionName = "0.3.0"`. Build the APK with
    `tools/release_apk.sh` and replace `HamanCough-v0.2.0.apk` at the repository root.
12. **Docs:** `README.md` and `INSTALL.md` currently say "Nothing is uploaded" / "No audio
    is uploaded". Replace with what is true now: detected events are uploaded after
    sign-in, and a 2.5 s clip of each cough and sneeze unless switched off; a whole night
    is never recorded or uploaded.

## 5. Rules that must hold

- `device_session_id` must stay `"<installId>:<roomSessionId>"`
  (`PlatformPayload.deviceSessionId`). Never start it with `web-`: the platform uses that
  prefix to mark browser-started sessions.
- Never upload individual snores, embeddings, raw frames or continuous audio.
- Never block or slow the capture loop: all network work runs in the worker, never in
  `MonitoringService`'s read loop.
- A failed upload must never delete or change local data.
- Do not log tokens, passwords or request bodies containing them.
- `core-domain` stays plain Kotlin (no Android or network imports); the network code
  belongs in `app`.

## 6. How to test

Use a **test account**, never a real user's. Create one at
`https://app.hamanhealth.com/auth/register` and tell Reza its email so it can be removed
afterwards.

1. Unit tests (JVM): the API client against `MockWebServer` for every row of the table in
   3.3, and for 401 → refresh → retry.
2. Instrumented test: migration 2 → 3 keeps existing sessions, events and labels.
3. On a real phone, with the test account:
   1. sign in; record a short session with a few coughs and one sneeze; stop it;
   2. open `https://app.hamanhealth.com/nights` as the same account: the night is there,
      counts match the phone, each clip plays;
   3. on the phone mark one cough "not an event"; reload the page: that cough shows
      "not counted" and the cough total dropped by one;
   4. airplane mode on, record another session, stop it, airplane mode off: it uploads by
      itself within a few minutes;
   5. force-stop the app during an upload, reopen it: the upload finishes, no duplicates;
   6. in the web app switch off Account → Privacy → Short audio clips, record again: the
      night uploads, `clips` is 0;
   7. sign out, record, sign in: the night uploads after sign-in.
4. Server-side check without the web app (replace the token and id):

   ```
   curl -H "Authorization: Bearer $TOKEN" https://api.hamanhealth.com/api/sessions/nights
   curl -H "Authorization: Bearer $TOKEN" https://api.hamanhealth.com/api/sessions/nights/$ID
   ```

## 7. Branches and deployment

- The backend and web app now live together on **`platform`** (it contains everything
  from `platform-cough-data` plus later work). Production is built from it.
- **Do not rebuild or redeploy the backend from `platform-cough-data`.** The production
  database is one migration ahead of that branch (`0003`), so an image built from it will
  fail at `alembic upgrade head` and the API will not start. If a backend change is ever
  needed, branch from `platform`.
- This task needs no server access and no deployment. Only the APK changes.
- Commit the Android work to `CoughAnalysisModule`. Do not merge that branch into
  `platform`; they are separate trees.

## 8. Report back

When finished, state plainly: which of the test steps in section 6 were run and passed,
which were not run, the APK version, and anything in this document that turned out to be
wrong or unclear.
