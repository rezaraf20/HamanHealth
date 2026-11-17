"""Delete audit-log rows older than AUDIT_RETENTION_DAYS (default 730).

The table is append-only: a trigger rejects every DELETE unless the transaction has set
haman.audit_purge, which only this job does.

Run monthly, e.g. from the host's crontab:
    30 4 1 * *  docker exec haman-api python -m app.jobs.purge_audit_log
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text

from ..config import get_settings
from ..database import SessionLocal
from ..models import AdminAuditLog


def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().audit_retention_days)
    with SessionLocal() as db:
        db.execute(text("SET LOCAL haman.audit_purge = 'on'"))
        deleted = db.execute(delete(AdminAuditLog).where(AdminAuditLog.at < cutoff)).rowcount
        db.commit()
    print(f"purged {deleted} audit rows older than {cutoff:%Y-%m-%d}")


if __name__ == "__main__":
    main()
