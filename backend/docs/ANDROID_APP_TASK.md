# Task: one Android app — the web app as the interface, the cough module underneath

**For:** Behzad (or a coding agent working in his checkout).
**Goal:** a single installable app. The user signs in, starts the night, and sees the
results all in one place. No second app, no browser.

Today there are two separate things: the web app (`web/` on `platform`), which has every
screen but cannot listen, and the Android detector app (`CoughAnalysisModule` branch),
which listens but has no network code, so nothing it detects ever reaches the platform.
This task joins them.

**Do not change the backend.** It is finished, deployed, and was verified end to end on
production on 2026-10-12 with exactly the requests in section 4.

---

## 1. The shape of the app

```
┌──────────────────────── Android app (one APK) ────────────────────────┐
│  Capacitor WebView  ── loads https://app.hamanhealth.com  (live)       │
│     screens, sign-in, results, settings          (TypeScript, exists)  │
│              │  Capacitor plugin "CoughSession"   (contract: §3)       │
│              ▼                                                         │
│  Native layer (Kotlin, your existing modules)                          │
│     MonitoringService · detector · Room DB · clips       (exists)      │
│     plugin class · upload worker · token store            (to build)   │
└────────────────────────────────┬───────────────────────────────────────┘
                                 ▼  HTTPS
                     https://api.hamanhealth.com   (exists, do not change)
```

- The **web layer** owns every screen and the login. It already contains the Capacitor
  side: `web/src/lib/cough-session.capacitor.ts` calls the plugin, and
  `web/src/lib/cough-session.ts` selects it automatically when
  `window.Capacitor.isNativePlatform()` is true. You should not need to edit the web app.
- **The interface is loaded live, not bundled.** The WebView opens
  `https://app.hamanhealth.com` (`server.url` in `web/capacitor.config.json`). A change
  deployed to the web app appears in the installed app the next time it is opened, with
  no new APK. Only native changes need a new APK. See section 5a for what this requires.
- The **native layer** owns the microphone, the detector, local storage and the upload.
  Upload must be native because it has to finish when the WebView is closed.

## 2. What "done" means

1. Installing one APK gives the user the Haman Health interface they know from
   `https://app.hamanhealth.com`.
2. They sign in on the app's own sign-in screen (the web layer's).
3. **Night session → Start** starts your `MonitoringService`; the live cough count on the
   session screen updates as coughs are detected; **End session** stops it.
4. The finished night uploads by itself: the night first, then a clip for each cough and
   sneeze that has one. Offline, app killed, server down: it happens later, nothing is
   lost, nothing is duplicated.
5. Home, **Night sounds**, Trends and Dashboard show that night, with playable clips.
6. Signing out stops uploads and keeps local nights. Signing in again uploads what is pending.

## 3. The plugin contract

The single source of truth is **`web/src/lib/cough-session.plugin.ts`** on `platform`.
Read it; every method, argument, return shape and event below is defined there with
comments. Implement a Capacitor plugin named **`CoughSession`** with exactly these:

| method | native behaviour |
|---|---|
| `getInfo()` → `{contractVersion, appVersion}` | `contractVersion` = 1 (the `CONTRACT_VERSION` in the contract file); `appVersion` = `versionName` |
| `isAvailable()` → `{available}` | model loadable and a microphone exists |
| `requestPermissions()` → `{microphone}` | request `RECORD_AUDIO` (and `POST_NOTIFICATIONS` on 33+); `"granted"` only if the microphone was granted |
| `start({sensitivity, autoStopAt?})` → `{sessionId}` | start `MonitoringService`; map `low/medium/high` to your 0–1 dial (use the midpoints of the ranges in `PlatformContract.sensitivityLevel`: 0.17 / 0.5 / 0.83); stop automatically at `autoStopAt` if given; reject if already running |
| `stop()` → summary | stop the service, wait until `db.sessions().finish()` has run, enqueue the upload, return the summary |
| `getStatus()` → status | from `MonitorState`; `eventCount` = coughs so far |
| `listSessions({from, to})` → `{sessions}` | finished sessions from Room |
| `setAuth({baseUrl, access, refresh})` | store encrypted; enqueue upload of everything pending |
| `clearAuth()` | delete the tokens; cancel queued uploads; keep local data |
| `syncNow()` → sync status | run the upload now and resolve when the attempt ends |
| `getSyncStatus()` → sync status | signed in?, pending nights, last success, last error |
| event `detectedEvent` | emit for every cough, sneeze and snore while running |
| event `syncStatus` | emit whenever an upload attempt ends or the pending count changes |

Rules for the plugin:

- All times are ISO 8601 UTC with milliseconds (`PlatformContract.isoUtc`).
- `sessionId` in the plugin is the phone's Room id as a string. The server's id is
  internal to the upload worker.
- `baseUrl` already ends in `/api` (`https://api.hamanhealth.com/api`). Do not hard-code
  a host in Kotlin.
- A method that cannot do its job rejects with a short human-readable message; the web
  layer shows it to the user as is.
- Plugin methods must return quickly. Nothing in the plugin may block the capture loop.

## 4. The upload (native, background)

Authenticated calls send `Authorization: Bearer <access>`. Paths below are relative to
`baseUrl`.

### 4.1 Tokens

- The web layer calls `setAuth` on app start, after sign-in and after each refresh.
- The access token lasts 30 days. If a call returns 401, call
  `POST /auth/refresh {"refresh": "<jwt>"}` → `{"access","refresh",...}` once and retry.
  If refresh also fails, stop, set `lastError` ("Sign in again to upload"), and wait for
  the next `setAuth`. Refreshing natively does not invalidate the web layer's tokens.
- Store tokens encrypted (Android Keystore-backed). Not in the existing `Prefs` class,
  which is plain `SharedPreferences`. Never log them.

### 4.2 Upload a night

```
POST /sessions/sync     body = PlatformContract.encode(PlatformPayload.build(db, sessionId, prefs.installId()))
201 {"id": 4, "device_session_id": "<installId>:<roomId>", "event_count": 2, ...}
```

- `id` is the **server session id**; keep it for the clip uploads.
- Idempotent: the same `device_session_id` merges (events matched on `device_event_id`,
  `user_label` updated). Retrying is always safe.
- Only finished sessions (`complete` or `interrupted`). Limits: 5000 events, 500 snore
  episodes per request. Keep `PlatformContract.UPLOADED_CLASSES` as is: coughs and
  sneezes as events, snoring only as episodes.
- 422 = the payload broke the contract: a bug, do not retry; record the response body.

Verified example (returned 201 on production):

```json
{"device_session_id":"check-install:1","started_at":"2026-10-11T19:30:00.000Z","ended_at":"2026-10-12T03:30:00.000Z",
 "status":"complete","timezone":"Asia/Tehran","sensitivity":"medium","device_model":"deploy-check","app_version":"0.3.0",
 "audio_source":"CAMCORDER@48k","noise_floor_db":-62.5,"mic_gap_ms":0,"frames_seen":60000,"frames_inferred":21000,
 "events":[
  {"device_event_id":"1","event_type":"cough","timestamp":"2026-10-11T22:15:03.120Z","ended_at":"2026-10-11T22:15:04.560Z","peak_at":"2026-10-11T22:15:03.600Z","confidence":0.91,"mean_score":0.7,"peak_db":-21.5,"snr_db":38.0,"bout_id":1,"subject_label":"subject","subject_confidence":0.8,"has_device_clip":true},
  {"device_event_id":"3","event_type":"sneeze","timestamp":"2026-10-12T01:02:00.000Z","ended_at":"2026-10-12T01:02:01.440Z","peak_at":"2026-10-12T01:02:00.500Z","confidence":0.8,"mean_score":0.6,"peak_db":-18.0,"snr_db":40.0,"subject_label":"unknown","subject_confidence":0.5,"has_device_clip":true}],
 "snore_episodes":[{"started_at":"2026-10-12T02:00:00.000Z","ended_at":"2026-10-12T02:20:00.000Z","snore_count":140,"mean_intensity_db":-35.0}]}
```

### 4.3 Upload a clip

```
POST /sessions/{serverSessionId}/events/{deviceEventId}/clip
multipart/form-data, one part named "file" (the WAV, audio/wav)
201 {"clip_anon_id": "1a6d642ded2c41649014d78e5066ff85"}
```

- `{deviceEventId}` = `EventEntity.id.toString()`, the same value sent in the night.
- The night must be uploaded first.
- Accepted: mono 16-bit PCM WAV, 8–48 kHz, ≤ 5 s, ≤ 1 MB. Your 2.5 s clips fit; do not
  re-encode. Do not send `clip_started_at`; the server derives it from `peak_at` and
  `PlatformContract.CLIP_PRE_ROLL_MS`.
- Idempotent: an event that already has a clip returns the existing id.

| status | meaning | action |
|---|---|---|
| 201 | stored | mark the clip uploaded |
| 401 | token invalid | refresh once and retry (4.1) |
| 403 | the user switched clips off | stop uploading clips; do not retry |
| 404 | night or event unknown to the server | upload the night again, retry once |
| 409 | 500-clip limit for this night | mark the night's remaining clips skipped |
| 422 | file rejected | mark this clip failed permanently |
| 503 | clips disabled on the server | retry later |
| 5xx, timeout, no network | transient | retry with backoff |

### 4.4 Consent

`GET /consent` → `{..., "audioClips": true|false}`. On by default; the user changes it in
the app under Account → Privacy. Check it before a night's clips and skip them when
false. Whether clips are *kept on the phone* stays your existing "keep clips" setting,
default on.

### 4.5 The worker

A `CoroutineWorker` (WorkManager), unique per session, constraint
`NetworkType.CONNECTED`, exponential backoff:

1. no tokens → finish (re-enqueued by the next `setAuth`);
2. upload the night, store the server id;
3. if `audioClips` is on, upload each pending clip, marking each as it succeeds so a
   restart continues where it stopped; a missing file (local retention deleted it) is
   "skipped", not an error;
4. `Result.retry()` on transient failures, otherwise `Result.success()`;
5. emit `syncStatus`.

Enqueue it: after `db.sessions().finish(...)` in `MonitoringService`; at app start for
every finished session never uploaded or changed since (this also uploads nights
recorded before this version); after `setAuth`.

### 4.6 State that must survive restarts (Room, schema v3)

- per session: server session id, last upload time, "changed since upload";
- per event: clip uploaded / failed permanently / skipped.

Add columns or a table. Bump `HamanDatabase` to 3, write `Migration(2, 3)`, commit
`schemas/.../3.json`, extend `DatabaseIntegrityTest` to cover the migration.
`EventDao.forUpload` returns `hasClip` but not the path: add a query returning
`(id, clipPath)` for a session's pending clips.

## 5. Building the app

1. **One repository tree.** Create a branch `android-app` from `platform` and merge
   `origin/CoughAnalysisModule` into it (the only path both have is `README.md`). From
   then on the Android project sits next to `web/`, whose contract file and Capacitor
   config it uses.
2. **Add Capacitor to your existing Gradle project** (`CoughAnalysisModule/android`):
   depend on Capacitor Android (same major as `@capacitor/core` in `web/package.json`,
   currently 8), make `MainActivity` extend `BridgeActivity` and register the plugin.
   Generating a scratch project with `npx cap add android` to copy its wiring from is
   fine; the result must be **one Gradle build producing one APK** that contains your
   four `core-*` modules. Keep `applicationId = "com.haman.sleep"` so it installs over
   0.2.0.
3. **Use `web/capacitor.config.json` as it is.** It sets `server.url` to
   `https://app.hamanhealth.com`, `webDir` to `native-shell` (the folder `web/native-shell`) and `server.errorPath`
   to `offline.html`. Ship `web/native-shell` as the WebView's assets (`npx cap copy android`,
   or a Gradle task copying it to `assets/public`, plus the generated
   `assets/capacitor.config.json`). You do **not** need to build the web app (no bun, no
   node) to build the APK.
4. **Manifest:** add `INTERNET` and `ACCESS_NETWORK_STATE`. HTTPS only.
5. **The Compose screens** (`HomeScreen`, `HistoryScreen`, `SessionDetailScreen`,
   `SettingsScreen`) are replaced by the web interface. Keep `DiagnosticsScreen`
   (microphone route test) reachable, e.g. from the notification or a long-press; it has
   no web equivalent yet.
6. **Version:** `versionCode = 3`, `versionName = "0.3.0"`. Build with
   `tools/release_apk.sh`; replace the APK at the repository root.
7. **Docs:** `README.md` and `INSTALL.md` say "Nothing is uploaded". Replace with what is
   true: after sign-in, detected events are uploaded, and a 2.5 s clip of each cough and
   sneeze unless switched off; a whole night is never recorded or uploaded.

## 5a. What live loading requires

The installed APK and the web app are now released separately, so they can be different
versions. These points keep that safe:

1. **The bridge must work on the live site.** Capacitor injects its bridge into pages
   from `server.url`. Verify on a device that, on `https://app.hamanhealth.com` inside
   the app, `window.Capacitor.isNativePlatform()` is `true` and
   `Capacitor.Plugins.CoughSession.getInfo()` resolves (Chrome → `chrome://inspect` → the
   WebView → console). If either fails, stop and report; do not work around it by
   bundling the web app.
2. **Only `app.hamanhealth.com` gets the bridge.** Do not add other hosts to
   `server.allowNavigation`. Links to other sites must open in the browser, not in the
   WebView (Capacitor's default; keep it).
3. **The contract only grows.** The web app in production may be newer than the APK a
   user has. Never remove or rename a method, argument, field or event; add new ones and
   bump `CONTRACT_VERSION` in `cough-session.plugin.ts` and in `getInfo()` together. The
   web side guards anything newer than version 1 with `getInfo().contractVersion`.
4. **Offline.** Without a connection the WebView cannot load the interface;
   `offline.html` is shown instead (it is bundled, and by Capacitor's design has no
   access to the plugin). Therefore:
   - the foreground notification keeps its **Stop** action (it has one today:
     `MonitoringService.ACTION_STOP`), so a running night can always be ended without
     the interface;
   - `autoStopAt` is enforced natively;
   - recording, detection and local storage never depend on the network; the upload
     waits for a connection (4.5).
5. **Session survives the WebView.** Closing the app, or the WebView being reloaded or
   killed, must not stop a running session. `getStatus()` after reopening reports the
   running session, and `detectedEvent` resumes.
6. **Requests come from `https://app.hamanhealth.com`.** That origin is already allowed
   by the API (CORS). The native upload does not go through the WebView and is not
   subject to CORS.
7. **Capacitor documents `server.url` as meant for live reload rather than production.**
   It is used here deliberately while the app is distributed directly as an APK. Before
   any store release it will be replaced by bundled assets with over-the-air updates;
   nothing in the plugin depends on which of the two is used, so keep it that way.

## 6. Rules that must hold

- `device_session_id` stays `"<installId>:<roomSessionId>"`
  (`PlatformPayload.deviceSessionId`). Never start it with `web-`.
- Never upload individual snores, embeddings, raw frames or continuous audio.
- Never block or slow the capture loop; all network work is in the worker.
- A failed upload never deletes or changes local data.
- `core-domain` stays plain Kotlin; network and Capacitor code live in `app`.
- If the plugin contract cannot be implemented as written, say so and propose the change
  to `cough-session.plugin.ts`; do not silently diverge.
- The contract only ever grows (section 5a). Never remove or rename something in it.

## 7. Known gap, deliberately left for later

The native app let the user label an event ("not a cough", "someone else"). The web
interface has no labelling yet, so this version loses that. The server already accepts
labels through `/sessions/sync`. Do not build a workaround; it will be added to the web
layer and the plugin together.

## 8. How to test

Use a **test account**, never a real user's. Create it at
`https://app.hamanhealth.com/auth/register` and give Reza its email for removal.

1. JVM tests: the upload client against `MockWebServer` for every row of the table in
   4.3 and for 401 → refresh → retry.
2. Instrumented: migration 2 → 3 keeps sessions, events and labels.
3. On a real phone:
   1. install the APK over 0.2.0; the Haman Health sign-in screen appears (loaded from
      `https://app.hamanhealth.com`); sign in; check item 1 of section 5a in the console;
   2. Night session → Start; cough a few times and sneeze once; the count rises; End;
   3. within a minute Home shows the night, and Night sounds lists each cough and the
      sneeze with a clip that plays;
   4. the same night is visible at `https://app.hamanhealth.com/nights` in a browser;
   5. airplane mode on, record, end, airplane mode off: it uploads by itself;
   6. force-stop the app mid-upload, reopen: it finishes, no duplicates;
   7. Account → Privacy → switch off Short audio clips, record again: the night uploads
      with 0 clips;
   8. sign out, record, sign in: the night uploads after sign-in;
   9. lock the screen during a session for at least 30 minutes: it keeps detecting;
   10. during a session swipe the app away and reopen it: the session screen shows the
       session still running with the right count;
   11. airplane mode on, open the app: the "No connection" page appears; stop a running
       session from its notification; turn the connection back on, tap Try again: the
       interface loads and the night uploads;
   12. ask Reza to deploy a visible change to the web app; close and reopen the app: the
       change is there without reinstalling.
4. Server-side check:

   ```
   curl -H "Authorization: Bearer $TOKEN" https://api.hamanhealth.com/api/sessions/nights
   curl -H "Authorization: Bearer $TOKEN" https://api.hamanhealth.com/api/sessions/nights/$ID
   ```

## 9. Branches and deployment

- Backend, web app and admin panel live on **`platform`**; production is built from it.
- **Never rebuild or deploy the backend from `platform-cough-data`.** The production
  database is one migration ahead of it (`0003`); an image built from it fails at
  `alembic upgrade head` and the API does not start.
- This task needs no server access and no deployment. Its output is an APK and the
  `android-app` branch. Open a pull request from `android-app` into `platform`; do not
  push to `platform` directly.

## 10. Report back

State plainly: which test steps in section 8 were run on a real phone and passed, which
were not run, the APK version, and anything in this document or in
`cough-session.plugin.ts` that turned out to be wrong or unclear.
