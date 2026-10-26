"""Role-scoped reports, CSV exports and the admin overview. All queries are organization-scoped."""
import csv
import io
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, require
from app.core import security as sec
from app.core.errors import AppError
from app.core.database import utcnow
from app.models import AuditEvent, Evidence, InventoryLot, Pickup, RecoveryCase, User
from app.services import audit

router = APIRouter(tags=["reports"])
LATE = ("pending", "assigned", "scheduled", "in_transit", "arrived")


def _org(model, user):
    return [] if user.is_platform_admin else [model.org_id == user.org_id]


def _org_id(user: User):
    """Audit events need a concrete organization; platform accounts without one can't export."""
    if user.org_id is None:
        raise AppError("Select an organization account to run this report.", "ORG_REQUIRED", 422)
    return user.org_id


def _csv(name: str, header: list[str], rows) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        # Neutralise spreadsheet formula injection in user-supplied text.
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in "=+-@" else c for c in r])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={name}"})


def _exceptions(db, user) -> dict:
    now = utcnow()
    cases = db.execute(select(RecoveryCase).where(*_org(RecoveryCase, user))).unique().scalars().all()
    with_ev = {r[0] for r in db.execute(select(Evidence.case_id).where(*_org(Evidence, user)).distinct()).all()}
    missing = [c for c in cases if c.id not in with_ev]
    stuck = [c for c in cases if c.status == "pending_approval" and (now - c.created_at) > timedelta(hours=4)]
    overdue = db.execute(select(Pickup).where(*_org(Pickup, user), Pickup.status.in_(LATE), Pickup.scheduled_for < now)).unique().scalars().all()
    failed = db.execute(select(Pickup).where(*_org(Pickup, user), Pickup.status.in_(("failed", "cancelled")))).unique().scalars().all()
    ref = lambda c: {"id": str(c.id), "case_number": c.case_number, "status": c.status, "quantity_kg": c.quantity_kg}
    pref = lambda p: {"id": str(p.id), "case_number": p.case.case_number, "status": p.status, "scheduled_for": p.scheduled_for.isoformat(), "delay_minutes": p.delay_minutes}
    return {"missing_evidence": [ref(c) for c in missing], "stale_pending_approval": [ref(c) for c in stuck],
            "overdue_pickups": [pref(p) for p in overdue], "failed_pickups": [pref(p) for p in failed]}


@router.get("/reports/exceptions", dependencies=[Depends(require("reports:export"))])
def exceptions(db: DB, user: CurrentUser):
    return _exceptions(db, user)


@router.get("/reports/cases.csv", dependencies=[Depends(require("reports:export"))])
def cases_csv(db: DB, user: CurrentUser):
    rows = db.execute(select(RecoveryCase).where(*_org(RecoveryCase, user)).order_by(RecoveryCase.created_at.desc())).unique().scalars().all()
    ev: dict = {cid: n for cid, n in db.execute(select(Evidence.case_id, func.count()).where(*_org(Evidence, user)).group_by(Evidence.case_id)).all()}
    audit.record(db, _org_id(user), user, "report.exported", "report", "cases", f"{user.full_name} exported the case report", {"rows": len(rows)})
    db.commit()
    return _csv("foodagent-cases.csv", ["case_number", "status", "lot_code", "rung", "quantity_kg", "recovered_kg", "recipient", "evidence_count", "created_at"],
                [[c.case_number, c.status, c.lot.lot_code, c.selected_rung or "", c.quantity_kg, c.recovered_kg if c.recovered_kg is not None else "",
                  c.recipient.name if c.recipient else "", ev.get(c.id, 0), c.created_at.isoformat()] for c in rows])


@router.get("/reports/inventory.csv", dependencies=[Depends(require("reports:export"))])
def inventory_csv(db: DB, user: CurrentUser):
    rows = db.execute(select(InventoryLot).where(*_org(InventoryLot, user)).order_by(InventoryLot.safe_until)).unique().scalars().all()
    audit.record(db, _org_id(user), user, "report.exported", "report", "inventory", f"{user.full_name} exported the inventory report", {"rows": len(rows)})
    db.commit()
    return _csv("foodagent-inventory.csv", ["lot_code", "product", "status", "quantity_kg", "reserved_kg", "storage", "produced_at", "safe_until"],
                [[l.lot_code, l.product.name, l.status, l.quantity_kg, l.reserved_kg, l.storage, l.produced_at.isoformat(), l.safe_until.isoformat()] for l in rows])


@router.get("/reports/pickups.csv", dependencies=[Depends(require("reports:export"))])
def pickups_csv(db: DB, user: CurrentUser):
    rows = db.execute(select(Pickup).where(*_org(Pickup, user)).order_by(Pickup.scheduled_for.desc())).unique().scalars().all()
    audit.record(db, _org_id(user), user, "report.exported", "report", "pickups", f"{user.full_name} exported the logistics report", {"rows": len(rows)})
    db.commit()
    return _csv("foodagent-pickups.csv", ["case_number", "status", "scheduled_for", "delay_minutes", "handed_over_at", "received_kg"],
                [[p.case.case_number, p.status, p.scheduled_for.isoformat(), p.delay_minutes, p.handed_over_at.isoformat() if p.handed_over_at else "", p.received_kg if p.received_kg is not None else ""] for p in rows])


@router.get("/reports/exceptions.csv", dependencies=[Depends(require("reports:export"))])
def exceptions_csv(db: DB, user: CurrentUser):
    ex = _exceptions(db, user)
    rows = [[kind, i.get("case_number"), i.get("status"), i.get("quantity_kg", i.get("delay_minutes", ""))] for kind, items in ex.items() for i in items]
    return _csv("foodagent-exceptions.csv", ["exception", "case_number", "status", "value"], rows)


@router.get("/admin/overview", dependencies=[Depends(require("admin:overview"))])
def admin_overview(db: DB, user: CurrentUser):
    users = db.execute(select(User.role, User.is_active, func.count()).where(*_org(User, user)).group_by(User.role, User.is_active)).all()
    by_role: dict = {}
    for role, active, n in users:
        d = by_role.setdefault(role, {"active": 0, "inactive": 0})
        d["active" if active else "inactive"] += n
    pending = db.execute(select(func.count()).select_from(RecoveryCase).where(*_org(RecoveryCase, user), RecoveryCase.status == "pending_approval")).scalar_one()
    sec_events = db.execute(select(AuditEvent).where(*_org(AuditEvent, user), AuditEvent.action.like("user.%")).order_by(AuditEvent.created_at.desc()).limit(10)).scalars().all()
    ex = _exceptions(db, user)
    pending_users = db.execute(select(func.count()).select_from(User).where(*_org(User, user), User.status == "PENDING")).scalar_one()
    return {"users_by_role": by_role, "pending_approvals": pending, "pending_users": pending_users,
            "exception_counts": {k: len(v) for k, v in ex.items()},
            "recent_security_events": [{"seq": e.seq, "action": e.action, "summary": e.summary, "actor": e.actor_label, "created_at": e.created_at.isoformat()} for e in sec_events]}
