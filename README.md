# Haman Health — Platform Repository

Night-time cough monitoring wellness app for Android.  
**Not a medical device.** For personal wellness tracking only.

## Repository Structure

```
hamanhealth/
├── backend/          # FastAPI + PostgreSQL API server
├── web/              # TanStack Start SPA (Capacitor web layer)
├── android/          # Android native modules (Behzad's cough engine)
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

```bash
# On the Hetzner server (one-time setup):
bash deploy/setup-server.sh

# After DNS for api.hamanhealth.com is active:
certbot --apache -d api.hamanhealth.com
systemctl reload httpd
```

## Web App

```bash
cd web
bun install
bun run dev          # mock mode (no backend needed)
bun run build        # production build → .output/public/
```

Set `VITE_API_BASE_URL=https://api.hamanhealth.com/api` in `.env.local` to use the real backend.

## Branches

| Branch    | Purpose |
|-----------|---------|
| `main`    | Lovable web UI source (do not rebase) |
| `platform`| Full platform: backend + web + deploy scripts |

---

HamanTech © 2026 — Reza Rafiei & Behzad Rezaiefar
