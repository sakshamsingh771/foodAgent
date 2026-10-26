"""Operator CLI for protected first-admin provisioning (no HTTP involved).

  python -m app.manage pending                      list organizations waiting for their first administrator
  python -m app.manage approve-admin user@acme.io   activate that pending administrator
  python -m app.manage reject-admin  user@acme.io
"""
import sys

from sqlalchemy import select

from app.core import security as sec
from app.core.database import SessionLocal, utcnow
from app.models import User
from app.services import audit


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"pending", "approve-admin", "reject-admin"}:
        print(__doc__)
        return 2
    with SessionLocal() as db:
        if argv[0] == "pending":
            for u in db.execute(select(User).where(User.status == sec.PENDING, User.requested_role == sec.ADMIN)).scalars():
                print(f"{u.email}\t{u.full_name}\t{u.created_at:%Y-%m-%d %H:%M}")
            return 0
        if len(argv) < 2:
            print(__doc__)
            return 2
        u = db.execute(select(User).where(User.email == argv[1].lower(), User.status == sec.PENDING)).scalar_one_or_none()
        if u is None or u.org_id is None:
            print("No pending administrator with that email.")
            return 1
        approve = argv[0] == "approve-admin"
        if approve:
            u.role = sec.ADMIN
        sec.set_status(u, sec.ACTIVE if approve else sec.REJECTED)
        u.decided_at, u.decision_note = utcnow(), "decided via operator CLI"
        audit.record(db, u.org_id, None, "user.approved" if approve else "user.rejected", "user", u.id,
                     f"Operator CLI {'approved' if approve else 'rejected'} {u.full_name}", actor_label="Operator CLI")
        db.commit()
        print(("Approved " if approve else "Rejected ") + u.email)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
