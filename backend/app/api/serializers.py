from app.core.database import utcnow
from app.models import (AuditEvent, Evidence, InventoryLot, Notification, Pickup, Recipient, RecoveryCase,
                        RecoveryOption, User)
from app.services import freshness
from app.services.recovery_engine import RUNG_LABELS


def iso(d):
    return d.isoformat() if d else None


def user_out(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "org_id": str(u.org_id) if u.org_id else None,
            "recipient_id": str(u.recipient_id) if u.recipient_id else None, "language": u.language,
            "is_platform_admin": u.is_platform_admin, "is_active": u.is_active}


def freshness_out(lot: InventoryLot, now=None) -> dict:
    f = freshness.assess(lot.safe_until, lot.window_minutes, now or utcnow())
    return {"remaining_minutes": f.remaining_minutes, "percent": f.percent, "state": f.state, "method": "RULE"}


def lot_out(lot: InventoryLot, now=None, open_case: dict | None = None) -> dict:
    return {
        "id": str(lot.id), "lot_code": lot.lot_code, "status": lot.status, "quantity_kg": lot.quantity_kg,
        "storage": lot.storage, "produced_at": iso(lot.produced_at), "safe_until": iso(lot.safe_until),
        "window_minutes": lot.window_minutes, "is_simulated": lot.is_simulated,
        "product": {"id": str(lot.product.id), "name": lot.product.name, "sku": lot.product.sku, "category": lot.product.category},
        "plant": {"id": str(lot.plant.id), "name": lot.plant.name, "city": lot.plant.city},
        "freshness": freshness_out(lot, now),
        "open_case": open_case,
    }


def option_out(o: RecoveryOption) -> dict:
    return {
        "rung": o.rung, "label": RUNG_LABELS[o.rung], "eligible": o.eligible, "reason": o.reason, "confidence": o.confidence,
        "p_success": o.p_success, "est_recovery_kg": o.est_recovery_kg, "method": o.method,
        "recipient_id": str(o.recipient_id) if o.recipient_id else None, "recipient_name": o.recipient_name,
        "is_recommended": o.is_recommended, "is_hedge": o.is_hedge, "factors": o.factors,
        "requires_food_safety_review": bool(o.factors.get("requires_food_safety_review")),
    }


def case_out(c: RecoveryCase, now=None) -> dict:
    return {
        "id": str(c.id), "case_number": c.case_number, "status": c.status, "selected_rung": c.selected_rung,
        "quantity_kg": c.quantity_kg, "recovered_kg": c.recovered_kg, "plan_version": c.plan_version, "replan_count": c.replan_count,
        "pickup_delay_min": c.pickup_delay_min, "handover_buffer_min": c.handover_buffer_min,
        "recipient": {"id": str(c.recipient.id), "name": c.recipient.name} if c.recipient else None,
        "lot": lot_out(c.lot, now), "created_at": iso(c.created_at), "closed_at": iso(c.closed_at),
    }


def pickup_out(p: Pickup) -> dict:
    return {
        "id": str(p.id), "case_id": str(p.case_id), "case_number": p.case.case_number, "status": p.status,
        "scheduled_for": iso(p.scheduled_for), "eta": iso(p.eta), "delay_minutes": p.delay_minutes, "delay_reason": p.delay_reason,
        "handed_over_at": iso(p.handed_over_at), "received_kg": p.received_kg,
        "logistics_user": {"id": str(p.logistics_user.id), "name": p.logistics_user.full_name} if p.logistics_user else None,
        "product": p.case.lot.product.name, "quantity_kg": p.case.quantity_kg,
        "recipient": p.case.recipient.name if p.case.recipient else None,
    }


def recipient_out(r: Recipient) -> dict:
    return {"id": str(r.id), "name": r.name, "kind": r.kind, "accepts_rungs": r.accepts_rungs, "acceptance_rate": r.acceptance_rate,
            "capacity_kg": r.capacity_kg, "distance_km": r.distance_km, "city": r.city, "phone": r.phone}


def evidence_out(e: Evidence) -> dict:
    return {"id": str(e.id), "kind": e.kind, "original_name": e.original_name, "content_type": e.content_type,
            "size_bytes": e.size_bytes, "sha256": e.sha256, "uploaded_at": iso(e.created_at)}


def audit_out(e: AuditEvent) -> dict:
    return {"id": str(e.id), "seq": e.seq, "action": e.action, "actor": e.actor_label, "resource_type": e.resource_type,
            "resource_id": e.resource_id, "summary": e.summary, "metadata": e.meta, "hash": e.hash, "prev_hash": e.prev_hash,
            "created_at": iso(e.created_at)}


def notification_out(n: Notification) -> dict:
    return {"id": str(n.id), "type": n.type, "severity": n.severity, "title": n.title, "body": n.body,
            "resource_type": n.resource_type, "resource_id": n.resource_id, "read": n.read_at is not None, "created_at": iso(n.created_at)}
