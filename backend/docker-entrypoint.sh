#!/bin/sh
# Bring both databases up to date, then start the API.
# Migrations run once here, before the workers start, so two workers never race.
set -e

alembic upgrade head
if [ -n "$CLIPS_DATABASE_URL" ]; then
  python -m app.jobs.prepare_clips
  alembic -n clips upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 2
