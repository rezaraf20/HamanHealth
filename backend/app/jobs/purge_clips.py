"""
Delete audio clips past their retention date, and clips no event links to any more.

Run daily, e.g. from the host's crontab:
    15 4 * * *  docker exec haman-api python -m app.jobs.purge_clips
"""
from ..clips_db import ClipsSessionLocal, clips_engine
from ..database import SessionLocal
from ..services import clip_store


def main() -> None:
    if clips_engine is None:
        print("clips database not configured; nothing to purge")
        return
    with SessionLocal() as db, ClipsSessionLocal() as clips_db:
        expired = clip_store.purge_expired(db, clips_db)
        orphans = clip_store.purge_orphans(db, clips_db)
    print(f"purged {expired} expired and {orphans} orphaned clips")


if __name__ == "__main__":
    main()
