"""
Run on container start, before the clips migrations: make sure the clips database
exists and the encryption key is in place, so audio clips work on a fresh server
without manual steps.

Creating the database uses the main database's credentials (the haman role is the
PostgreSQL superuser in the haman-db container). If it lacks the right to create a
database, create it by hand: deploy/sql/create_clips_db.sql.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ..config import get_settings


def main() -> None:
    settings = get_settings()
    if not settings.clips_database_url:
        print("clips: CLIPS_DATABASE_URL not set, audio clips disabled")
        return
    name = make_url(settings.clips_database_url).database
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first()
        if not exists:
            # Identifier can't be a bind parameter; quote it.
            c.execute(text('CREATE DATABASE "%s"' % name.replace('"', '""')))
            print(f"clips: created database {name}")
    admin.dispose()
    settings.clips_key()  # generates the key file once, before the workers start
    print("clips: ready")


if __name__ == "__main__":
    main()
