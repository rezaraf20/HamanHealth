# Haman Health — Platform Repository

Night-time cough monitoring wellness app for Android.  
**Not a medical device.** For personal wellness tracking only.

## Repository Structure

```
hamanhealth/
├── backend/          # FastAPI + PostgreSQL API server
├── web/              # TanStack Start SPA (Capacitor web layer)
├── CoughAnalysisModule/android/   # The Android app: Capacitor shell + cough engine
└── deploy/           # Docker Compose + Apache vhost configs
```

## Architecture

```
Android APK
  ├── Capacitor (web ↔ native bridge)
  │   ├── web/  →  SPA (React, TanStack Start, Tailwind)
  │   └── CoughSessionPlugin (Kotlin)
  │       └── MonitoringService (foreground, mic, YAMNet TFLite)
  └── FastAPI backend  →  api.hamanhealth.com
      └── PostgreSQL (sessions + events)
```

## Backend (FastAPI)

### Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql://haman:pass@localhost:5432/hamanhealth \
SECRET_KEY=dev-secret \
uvicorn app.main:app --reload
```

API docs: http://localhost:8002/api/docs

### Deploy to server

Server: **128.140.54.86** (Hetzner), SSH on port **2025**, DirectAdmin user **hamanhea**  
Wildcard cert `*.hamanhealth.com` is already installed (valid Dec 2026).

```bash
# On the Hetzner server as root — one-time API bootstrap:
bash deploy/setup-server.sh

# Deploy / update the web SPA to hamanhealth.com:
bash deploy/deploy-web.sh

# Test endpoints:
curl https://api.hamanhealth.com/api/health   # API
curl https://hamanhealth.com                  # Web SPA
```

> **Note:** This server uses DirectAdmin's `cust_httpd` file (not `/etc/httpd/conf.d/`).
> `deploy/directadmin-proxy-setup.sh` documents and applies the proxy config for `api.hamanhealth.com`.

## Web App

```bash
cd web
bun install
bun run dev          # mock mode (no backend needed)
bun run build        # production build → .output/public/
```

Set `VITE_API_BASE_URL=https://api.hamanhealth.com/api` in `.env.local` to use the real backend.

## Android App

One APK: the web interface (loaded live from `https://app.hamanhealth.com` in a
Capacitor WebView) with the on-device cough detector underneath as the `CoughSession`
plugin, which also uploads finished nights and clips in the background.
Task and contract: `backend/docs/ANDROID_APP_TASK.md`, `web/src/lib/cough-session.plugin.ts`.

```bash
CoughAnalysisModule/tools/setup_env.sh     # JDK + Android SDK, once (macOS)
CoughAnalysisModule/tools/release_apk.sh   # tests + release APK → HamanCough-v<version>.apk here
```

No node or bun is needed: the build copies `web/native-shell` and
`web/capacitor.config.json` into the APK itself.

**Privacy:** after sign-in the app uploads the detected events, and a 2.5-second clip of
each cough and sneeze unless the user switches clips off (Account → Privacy). A whole
night is never recorded or uploaded.

## Branches

| Branch    | Purpose |
|-----------|---------|
| `main`    | Lovable web UI source (do not rebase) |
| `platform`| Full platform: backend + web + deploy scripts |

---

HamanTech © 2026 — Reza Rafiei & Behzad Rezaiefar
