# Haman Health Companion

Build "Haman Health", a mobile-first responsive web app (wellness, NOT a diagnostic tool).

Match the attached screenshots: Inter font, teal primary #0F766E, light bg #F6F8FB,

dark night theme #0B1220 with accent #2DD4BF, rounded cards (18px), soft borders #E2E8F0.

IMPORTANT ARCHITECTURE RULES

- Frontend only. Do NOT use Lovable Cloud or Supabase for auth, database or storage.

- All data goes through one typed API client (src/lib/api.ts) that calls an external

  FastAPI backend at VITE_API_BASE_URL / env var. Use JWT (access + refresh) auth.

- Until the backend exists, the API client returns mock data behind a USE_MOCKS flag.

- Never store or upload raw audio. The app only sends cough events

  (timestamp, count, session_id).

- Charts with Recharts. English UI, i18n-ready (en, nl).

PAGES

1. Auth: elegant login, register, forgot password, 2FA code screen, consent step.

2. Onboarding & consent (as in screenshot 01).

3. Night session setup + active session (screenshots 02–03).

4. Home / morning summary (screenshot 04).

5. Full dashboard: cough per night, weight, activity, sleep, medications,

   7/30/90-day ranges, "change noticed" cards (trend only, no triage, no colors

   like red/yellow/green urgency).

6. Trends (screenshot 05) and Health timeline with filters (screenshot 06).

7. Records: upload PDF/images, list with type/date, detail view showing

   extracted fields as "extracted information", not medical interpretation.

8. User account panel: profile, security (password, 2FA, active sessions),

   privacy (consent management, data export, delete account), notifications,

   language, connected devices (placeholder).

9. Support chatbot: floating button + panel on all pages, calls POST /support/chat

   on our backend. Scope: app help only. If asked medical questions, reply that

   it can't give medical advice and suggest contacting a GP.

Bottom tab bar on mobile (Home, Trends, Timeline, Profile), sidebar on desktop.
I attached a photo that i like this UI

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/3a5587b7-03ed-4d2b-a40c-b84574e8ec6a).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
