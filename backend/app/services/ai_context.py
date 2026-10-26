"""Builds the minimal, organization-scoped, sanitized context sent to Gemini.

Every query filters on the caller's org_id taken from the authenticated user (never from the request).
No emails, phones, user names, password hashes, tokens or free-form notes beyond short truncated reasons are included.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError
from app.models import Allocation, InventoryLot, Pickup, Recipient, RecoveryCase, User
from app.services import allocations as alloc_svc
from app.services import freshness
from app.services.cases import ACTIVE_CASE

CLOSED_LOT = ("recovered", "closed", "expired", "discarded", "consumed")


def _t(v, n=120):
    return (v or "")[:n]


def _iso(d):
    return d.isoformat(timespec="minutes") if d else None


def _org(user: User):
    if user.org_id is None:
        raise AppError("The AI assistant works within an organization.", "ORG_REQUIRED", 422)
    return user.org_id


def lots(db: Session, org_id, now, limit=12):
    rows = db.execute(select(InventoryLot).where(InventoryLot.org_id == org_id, InventoryLot.status.notin_(CLOSED_LOT), InventoryLot.quantity_kg > 0)
                      .order_by(InventoryLot.safe_until).limit(limit)).scalars().all()
    out = []
    for l in rows:
        f = freshness.assess(l.safe_until, l.window_minutes, now)
        out.append({"lot_code": l.lot_code, "product": l.product.name, "category": l.product.category, "quantity_kg": l.quantity_kg,
                    "reserved_kg": l.reserved_kg, "storage": l.storage, "status": l.status, "remaining_minutes": f.remaining_minutes,
                    "freshness_state": f.state})
    return out


def cases(db: Session, org_id, limit=12):
    rows = db.execute(select(RecoveryCase).where(RecoveryCase.org_id == org_id, RecoveryCase.status.in_(ACTIVE_CASE))
                      .order_by(RecoveryCase.created_at.desc()).limit(limit)).scalars().all()
    return [{"case_number": c.case_number, "status": c.status, "selected_rung": c.selected_rung, "quantity_kg": c.quantity_kg,
             "replan_count": c.replan_count, "excluded_recipient_count": len(c.excluded_recipients or []),
             "excluded_rungs": list(c.excluded_rungs or [])} for c in rows]


def recipients(db: Session, org_id, limit=12):
    rows = db.execute(select(Recipient).where(Recipient.org_id == org_id, Recipient.status == "active").order_by(Recipient.name).limit(limit)).scalars().all()
    return [{"name": r.name, "kind": r.kind, "accepts_rungs": list(r.accepts_rungs or []), "capacity_kg": r.capacity_kg,
             "current_load_kg": alloc_svc.recipient_load(db, r.id), "distance_km": r.distance_km, "historical_acceptance_rate": r.acceptance_rate} for r in rows]


def allocations(db: Session, org_id, only_problems=False, limit=20):
    q = select(Allocation).where(Allocation.org_id == org_id)
    if only_problems:
        q = q.where((Allocation.status.in_(("rejected", "failed", "cancelled", "released"))) | (Allocation.delay_minutes > 0))
    rows = db.execute(q.order_by(Allocation.updated_at.desc()).limit(limit)).scalars().all()
    case_numbers = {c.id: c.case_number for c in db.execute(select(RecoveryCase).where(RecoveryCase.id.in_([a.case_id for a in rows] or [None]))).scalars()}
    return [{"case_number": case_numbers.get(a.case_id), "recipient": a.recipient.name, "rung": a.rung, "quantity_kg": a.quantity_kg, "status": a.status,
             "plan_version": a.plan_version, "strategy": a.strategy, "delay_minutes": a.delay_minutes, "eta": _iso(a.eta),
             "optimizer_reason": _t(a.why), "recorded_response_reason": _t(a.response_reason)} for a in rows]


def pickups(db: Session, org_id, limit=15):
    rows = db.execute(select(Pickup).where(Pickup.org_id == org_id, (Pickup.delay_minutes > 0) | (Pickup.status == "cancelled"))
                      .order_by(Pickup.updated_at.desc()).limit(limit)).scalars().all()
    nums = {c.id: c.case_number for c in db.execute(select(RecoveryCase).where(RecoveryCase.id.in_([p.case_id for p in rows] or [None]))).scalars()}
    return [{"case_number": nums.get(p.case_id), "status": p.status, "delay_minutes": p.delay_minutes, "recorded_delay_reason": _t(p.delay_reason, 100),
             "scheduled_for": _iso(p.scheduled_for)} for p in rows]


def metrics(db: Session, org_id, days: int, now):
    since = now - timedelta(days=days)
    by_status: dict[str, int] = {}
    for row in db.execute(
        select(RecoveryCase.status, func.count())
        .where(RecoveryCase.org_id == org_id, RecoveryCase.created_at >= since)
        .group_by(RecoveryCase.status)
    ).all():
        by_status[str(row[0])] = int(row[1])
    recovered = db.execute(select(func.coalesce(func.sum(RecoveryCase.recovered_kg), 0.0)).where(RecoveryCase.org_id == org_id, RecoveryCase.created_at >= since)).scalar_one()
    alloc_by: dict[str, int] = {}
    for row in db.execute(
        select(Allocation.status, func.count())
        .where(Allocation.org_id == org_id, Allocation.created_at >= since)
        .group_by(Allocation.status)
    ).all():
        alloc_by[str(row[0])] = int(row[1])
    delayed = db.execute(select(func.count()).select_from(Pickup).where(Pickup.org_id == org_id, Pickup.created_at >= since, Pickup.delay_minutes > 0)).scalar_one()
    return {"window_days": days, "cases_created_by_status": by_status, "recovered_kg_recorded_on_cases": float(recovered or 0.0),
            "allocations_by_status": alloc_by, "pickups_with_recorded_delay": delayed}


PARTS = {
    "recommendations": ("lots", "cases", "recipients", "allocations"),
    "failures": ("allocations_problems", "pickups", "cases"),
    "summary": ("metrics", "allocations_problems"),
    "chat": ("lots", "cases", "recipients", "allocations", "pickups", "metrics"),
}


def build(db: Session, user: User, kind: str, days: int = 7) -> dict:
    org_id, now = _org(user), utcnow()
    ctx: dict = {"generated_at": _iso(now), "scope": "your organization only"}
    for part in PARTS[kind]:
        if part == "lots": ctx["surplus_lots_by_expiry"] = lots(db, org_id, now)
        elif part == "cases": ctx["active_recovery_cases"] = cases(db, org_id)
        elif part == "recipients": ctx["active_recipients"] = recipients(db, org_id)
        elif part == "allocations": ctx["recent_allocations"] = allocations(db, org_id)
        elif part == "allocations_problems": ctx["rejected_failed_or_delayed_allocations"] = allocations(db, org_id, only_problems=True)
        elif part == "pickups": ctx["delayed_or_cancelled_pickups"] = pickups(db, org_id)
        elif part == "metrics": ctx["measured_metrics"] = metrics(db, org_id, days, now)
    return ctx


def allowed_references(ctx) -> set[str]:
    """Identifiers Gemini may cite: only those present in the data we sent."""
    found: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("case_number", "lot_code", "name", "recipient", "recipient_name") and isinstance(v, str):
                    found.add(v)
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)
    walk(ctx)
    return found
