"""Remove an admin's 2FA enrolment — for an admin who lost their authenticator.

Needs shell access to the server on purpose; there is deliberately no API for it.
    docker exec haman-api python -m app.jobs.reset_admin_2fa admin@example.com
The admin can enrol again afterwards. The reset is written to the audit log.
"""
import sys

from ..database import SessionLocal
from ..models import AdminTotp, User
from ..services.admin_security import audit


def main(email: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"no user with email {email}")
            return 1
        row = db.get(AdminTotp, user.id)
        if row is None:
            print("that user has no 2FA enrolment; nothing to do")
            return 0
        db.delete(row)
        audit(db, None, "2fa.reset_by_shell", None, "user", user.id, {"email": email})
        db.commit()
    print(f"2FA reset for {email}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.jobs.reset_admin_2fa <email>")
    sys.exit(main(sys.argv[1]))
