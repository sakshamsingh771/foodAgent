"""Recovery case workflow. Side effects (DB, audit, events) live here; scoring lives in recovery_engine."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import security as sec
from app.core.database import utcnow
from app.core.errors import AppError, Conflict
from app.models import (
    Evidence,
    FreshnessAssessment,
    InventoryLot,
    Pickup,
    Recipient,
    RecoveryCase,
    RecoveryDecision,
    RecoveryOption,
    SustainabilityMetric,
    User,
)
from app.services import audit, events, freshness
from app.services import recovery_engine as eng

ACTIVE_CASE = ("pending_approval", "awaiting_recipient", "accepted", "pickup_scheduled", "in_transit")
PICKUP_FLOW = {
    "pending": {"assigned", "scheduled", "cancelled"},
    "assigned": {"scheduled", "cancelled"},
    "scheduled": {"in_transit", "cancelled"},
    "in_transit": {"arrived", "cancelled"},
    "arrived": {"handed_over"},
    "handed_over": {"completed"},
}
CO2E_RUNG_FACTOR = {"R1": 1.0, "R2": 0.9, "R3": 0.6, "R4": 0.25}  # illustrative, see ASSUMPTIONS.md
REQUIRED_EVIDENCE_KINDS = {"photo", "temperature_log", "label"}


def evidence_score(db: Session, case_id) -> float:
    kinds = set(db.execute(select(Evidence.kind).where(Evidence.case_id == case_id)).scalars().all())
    return round(len(kinds & REQUIRED_EVIDENCE_KINDS) / len(REQUIRED_EVIDENCE_KINDS), 2)


def lot_input(db: Session, lot: InventoryLot, case_id=None, now: datetime | None = None) -> eng.LotInput:
    now = now or utcnow()
    f = freshness.assess(lot.safe_until, lot.window_minutes, now)
    return eng.LotInput(
        quantity_kg=lot.quantity_kg, remaining_minutes=f.remaining_minutes, freshness_percent=f.percent,
        human_grade_eligible=lot.product.human_grade_eligible, feed_eligible=lot.product.feed_eligible,
        evidence_score=evidence_score(db, case_id) if case_id else 0.0,
    )


def recipient_inputs(db: Session) -> list[eng.RecipientInput]:
    rows = db.execute(select(Recipient).where(Recipient.status == "active")).scalars().all()
    return [
        eng.RecipientInput(str(r.id), r.name, r.kind, list(r.accepts_rungs), r.acceptance_rate, r.distance_km, r.capacity_kg)
        for r in rows
    ]


def _constraints(case: RecoveryCase) -> eng.Constraints:
    return eng.Constraints(case.pickup_delay_min, case.handover_buffer_min, list(case.excluded_rungs), list(case.excluded_recipients))


def _persist_plan(db: Session, case: RecoveryCase, options: list[eng.RungOption]) -> None:
    for o in options:
        db.add(RecoveryOption(
            case_id=case.id, plan_version=case.plan_version, rung=o.rung, eligible=o.eligible, reason=o.reason,
            confidence=o.confidence, p_success=o.p_success, est_recovery_kg=o.est_recovery_kg,
            recipient_id=uuid.UUID(o.recipient_id) if o.recipient_id else None, recipient_name=o.recipient_name,
            method=o.method, is_recommended=o.is_recommended, is_hedge=o.is_hedge,
            factors={**o.factors, "requires_food_safety_review": o.requires_food_safety_review},
        ))
    db.flush()


def _next_case_number(db: Session) -> str:
    n = db.execute(select(func.count()).select_from(RecoveryCase)).scalar_one() + 1
    return f"RC-{utcnow():%y%m}-{n:04d}"


def create_case(db: Session, lot: InventoryLot, actor: User | None) -> RecoveryCase:
    if lot.status not in ("available",):
        raise Conflict("This lot is already in recovery or closed.", "LOT_NOT_AVAILABLE")
    active = db.execute(select(RecoveryCase.id).where(RecoveryCase.lot_id == lot.id, RecoveryCase.status.in_(ACTIVE_CASE))).first()
    if active:
        raise Conflict("This lot already has an open recovery case.", "CASE_ALREADY_OPEN")
    case = RecoveryCase(
        org_id=lot.org_id, lot_id=lot.id, case_number=_next_case_number(db), status="pending_approval",
        quantity_kg=lot.quantity_kg, created_by=actor.id if actor else None,
    )
    db.add(case)
    db.flush()
    lot.status = "in_recovery"
    options = eng.plan(lot_input(db, lot, case.id), recipient_inputs(db), _constraints(case))
    _persist_plan(db, case, options)
    audit.record(db, lot.org_id, actor, "recovery_case.created", "recovery_case", case.id,
                 f"Recovery case {case.case_number} opened for lot {lot.lot_code}", {"lot": lot.lot_code}, case.id)
    rec = next((o for o in options if o.is_recommended), None)
    audit.record(db, lot.org_id, None, "recovery.recommended", "recovery_case", case.id,
                 f"{rec.rung} recommended ({rec.method})" if rec else "No eligible pathway found",
                 {"rung": rec.rung if rec else None, "p_success": rec.p_success if rec else None}, case.id, actor_label="Recovery engine (rule-based)")
    events.publish(db, lot.org_id, "recovery.created", {"case_id": str(case.id), "lot_id": str(lot.id)})
    events.notify_roles(db, lot.org_id, [sec.RECOVERY, sec.ADMIN], "recovery_approval",
                        f"Approval needed: {case.case_number}", f"{lot.product.name}, {lot.quantity_kg:g} kg", "warning", "recovery_case", case.id)
    return case


def replan(db: Session, case: RecoveryCase, actor: User | None, reason: str, exclude_rung: str | None = None,
           exclude_recipient: str | None = None, actor_label: str | None = None) -> RecoveryCase:
    if case.status in ("completed", "cancelled", "handed_over"):
        raise Conflict("This case is closed and can't be replanned.", "CASE_CLOSED")
    from app.services import allocations as _alloc
    if _alloc.has_live(db, case.id):
        raise Conflict("This case uses multi-recipient allocations. Reject or cancel an allocation to replan it.", "USE_ALLOCATION_REPLAN")
    if exclude_rung and exclude_rung not in case.excluded_rungs:
        case.excluded_rungs = [*case.excluded_rungs, exclude_rung]
    if exclude_recipient and exclude_recipient not in case.excluded_recipients:
        case.excluded_recipients = [*case.excluded_recipients, exclude_recipient]
    case.plan_version += 1
    case.replan_count += 1
    case.status = "pending_approval"
    case.selected_rung = None
    case.recipient_id = None
    lot = case.lot
    options = eng.plan(lot_input(db, lot, case.id), recipient_inputs(db), _constraints(case))
    _persist_plan(db, case, options)
    db.add(RecoveryDecision(case_id=case.id, decided_by=actor.id if actor else None, decision="replan", note=reason))
    rec = next((o for o in options if o.is_recommended), None)
    audit.record(db, case.org_id, actor, "recovery.replanned", "recovery_case", case.id,
                 f"Replanned: {reason}. " + (f"New recommendation {rec.rung}." if rec else "No eligible pathway remains."),
                 {"reason": reason, "plan_version": case.plan_version, "excluded_rungs": case.excluded_rungs}, case.id, actor_label=actor_label)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    events.notify_roles(db, case.org_id, [sec.RECOVERY, sec.ADMIN], "recovery_approval",
                        f"Replan needs approval: {case.case_number}", reason, "warning", "recovery_case", case.id)
    return case


def rescore(db: Session, case: RecoveryCase) -> None:
    """Re-score the current plan version in place (e.g. after new evidence). Exclusions are unchanged."""
    db.execute(delete(RecoveryOption).where(RecoveryOption.case_id == case.id, RecoveryOption.plan_version == case.plan_version))
    _persist_plan(db, case, eng.plan(lot_input(db, case.lot, case.id), recipient_inputs(db), _constraints(case)))


def current_options(db: Session, case: RecoveryCase) -> list[RecoveryOption]:
    return list(db.execute(select(RecoveryOption).where(RecoveryOption.case_id == case.id, RecoveryOption.plan_version == case.plan_version)
                           .order_by(RecoveryOption.rung)).scalars().all())


def approve(db: Session, case: RecoveryCase, actor: User, rung: str, recipient_id: uuid.UUID | None, note: str) -> RecoveryCase:
    if case.status != "pending_approval":
        raise Conflict("This case isn't waiting for approval.", "CASE_NOT_PENDING")
    from app.services import allocations as _alloc
    if _alloc.has_live(db, case.id):
        raise Conflict("This case already has multi-recipient allocations. Approve them instead.", "USE_ALLOCATION_APPROVE")
    opt = next((o for o in current_options(db, case) if o.rung == rung), None)
    if not opt or not opt.eligible:
        raise Conflict(f"{rung} isn't an eligible option for this case right now.", "RUNG_NOT_ELIGIBLE")
    rid = recipient_id or opt.recipient_id
    if rid is None:
        raise AppError("Choose a recipient to continue.", "RECIPIENT_REQUIRED", 422)
    recipient = db.get(Recipient, rid)
    if not recipient or rung not in recipient.accepts_rungs or str(rid) in case.excluded_recipients:
        raise Conflict("That recipient can't take this pathway.", "RECIPIENT_NOT_ELIGIBLE")
    case.selected_rung, case.recipient_id, case.status = rung, rid, "awaiting_recipient"
    db.add(RecoveryDecision(case_id=case.id, decided_by=actor.id, decision="approved", rung=rung, recipient_id=rid, note=note))
    audit.record(db, case.org_id, actor, "recovery.approved", "recovery_case", case.id,
                 f"{actor.full_name} approved {rung} with {recipient.name}", {"rung": rung, "recipient": recipient.name, "note": note}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    events.publish(db, case.org_id, "recovery.assigned", {"case_id": str(case.id)}, recipient_id=rid)
    events.notify_recipient_users(db, rid, "recipient_offer", f"New lot offered: {case.lot.product.name}",
                                  f"{case.quantity_kg:g} kg available for pickup", "recovery_case", case.id)
    return case


def reject(db: Session, case: RecoveryCase, actor: User, note: str) -> RecoveryCase:
    if case.status != "pending_approval":
        raise Conflict("This case isn't waiting for approval.", "CASE_NOT_PENDING")
    from app.services import allocations as _alloc
    _alloc.release_all(db, case, actor, "plan rejected")
    case.status, case.closed_at = "rejected", utcnow()
    case.lot.status = "available"
    db.add(RecoveryDecision(case_id=case.id, decided_by=actor.id, decision="rejected", note=note))
    audit.record(db, case.org_id, actor, "recovery.rejected", "recovery_case", case.id, f"{actor.full_name} rejected the plan", {"note": note}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return case


def recipient_respond(db: Session, case: RecoveryCase, actor: User, accept: bool, reason: str | None) -> RecoveryCase:
    if case.status != "awaiting_recipient" or case.recipient_id != actor.recipient_id:
        raise Conflict("This offer is no longer open to you.", "OFFER_NOT_OPEN")
    name = case.recipient.name
    if accept:
        case.status = "accepted"
        db.add(RecoveryDecision(case_id=case.id, decided_by=actor.id, decision="recipient_accepted", rung=case.selected_rung, recipient_id=case.recipient_id))
        audit.record(db, case.org_id, actor, "recipient.accepted", "recovery_case", case.id, f"{name} accepted the lot", {}, case.id)
        events.publish(db, case.org_id, "recipient.accepted", {"case_id": str(case.id)})
        events.notify_roles(db, case.org_id, [sec.OPS, sec.RECOVERY, sec.LOGISTICS], "recipient_response",
                            f"{name} accepted {case.case_number}", "Schedule a pickup.", "info", "recovery_case", case.id)
        return case
    declined_id = str(case.recipient_id)
    db.add(RecoveryDecision(case_id=case.id, decided_by=actor.id, decision="recipient_declined", rung=case.selected_rung,
                            recipient_id=case.recipient_id, note=reason or ""))
    audit.record(db, case.org_id, actor, "recipient.declined", "recovery_case", case.id,
                 f"{name} declined" + (f": {reason}" if reason else ""), {"reason": reason}, case.id)
    events.notify_roles(db, case.org_id, [sec.OPS, sec.RECOVERY], "recipient_response", f"{name} declined {case.case_number}", reason or "", "warning", "recovery_case", case.id)
    return replan(db, case, actor, f"{name} declined" + (f" ({reason})" if reason else ""), exclude_recipient=declined_id)


def _require_single_recipient(case: RecoveryCase) -> None:
    """The pickup workflow models ONE recipient. Multi-recipient cases are fulfilled per allocation
    (POST /allocations/{id}/transport and /handover), which keeps reservations, metrics and audit consistent."""
    if case.recipient_id is None:
        raise Conflict("This case uses multi-recipient allocations. Use allocation transport and handover instead.", "USE_ALLOCATION_HANDOVER")


def schedule_pickup(db: Session, case: RecoveryCase, actor: User, scheduled_for: datetime, logistics_user_id: uuid.UUID | None) -> Pickup:
    _require_single_recipient(case)
    if case.status != "accepted":
        raise Conflict("A pickup can be scheduled once the recipient has accepted.", "CASE_NOT_ACCEPTED")
    lu: User | None = None
    if logistics_user_id:
        lu = db.get(User, logistics_user_id)
        if not lu or lu.org_id != case.org_id or lu.role != sec.LOGISTICS:
            raise AppError("Choose a logistics user from your organization.", "INVALID_LOGISTICS_USER", 422)
    p = Pickup(org_id=case.org_id, case_id=case.id, status="scheduled", logistics_user_id=logistics_user_id,
               scheduled_for=scheduled_for, eta=scheduled_for)
    db.add(p)
    case.status = "pickup_scheduled"
    db.flush()
    audit.record(db, case.org_id, actor, "pickup.scheduled", "pickup", p.id, f"Pickup scheduled for {scheduled_for:%H:%M}", {"scheduled_for": scheduled_for}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    events.publish(db, case.org_id, "pickup.scheduled", {"case_id": str(case.id), "pickup_id": str(p.id)}, recipient_id=case.recipient_id)
    if lu is not None:
        events.add_notification(db, lu, case.org_id, "pickup_assigned", f"Pickup assigned: {case.case_number}", f"{case.lot.product.name}, {case.quantity_kg:g} kg", "info", "pickup", p.id)
    return p


def advance_pickup(db: Session, pickup: Pickup, actor: User, status: str) -> Pickup:
    if status not in PICKUP_FLOW.get(pickup.status, set()):
        raise Conflict(f"A pickup that is {pickup.status.replace('_', ' ')} can't move to {status.replace('_', ' ')}.", "INVALID_PICKUP_TRANSITION")
    if status in ("handed_over", "completed"):
        raise AppError("Use handover confirmation to finish a pickup.", "USE_HANDOVER", 422)
    pickup.status = status
    case = pickup.case
    if status == "in_transit":
        case.status = "in_transit"
    if status == "cancelled":
        case.status = "accepted"
    audit.record(db, pickup.org_id, actor, f"pickup.{status}", "pickup", pickup.id, f"Pickup is now {status.replace('_', ' ')}", {}, case.id)
    events.publish(db, pickup.org_id, "recovery.updated", {"case_id": str(case.id)})
    events.publish(db, pickup.org_id, "pickup.updated", {"pickup_id": str(pickup.id), "status": status}, recipient_id=case.recipient_id)
    return pickup


def delay_pickup(db: Session, pickup: Pickup, actor: User | None, minutes: int, reason: str, actor_label: str | None = None) -> Pickup:
    if pickup.status in ("handed_over", "completed", "cancelled"):
        raise Conflict("This pickup is already finished.", "PICKUP_CLOSED")
    pickup.delay_minutes += minutes
    pickup.delay_reason = reason[:200]
    pickup.eta = (pickup.eta or pickup.scheduled_for) + timedelta(minutes=minutes)
    case = pickup.case
    case.pickup_delay_min += minutes
    f = freshness.assess(case.lot.safe_until, case.lot.window_minutes, utcnow())
    audit.record(db, pickup.org_id, actor, "pickup.delayed", "pickup", pickup.id, f"Pickup delayed by {minutes} min: {reason}",
                 {"minutes": minutes, "remaining_minutes": f.remaining_minutes}, case.id, actor_label=actor_label)
    events.publish(db, pickup.org_id, "pickup.delayed", {"pickup_id": str(pickup.id), "case_id": str(case.id), "minutes": minutes})
    events.notify_roles(db, pickup.org_id, [sec.OPS, sec.RECOVERY], "pickup_delay", f"Pickup delayed {minutes} min: {case.case_number}", reason,
                        "critical" if f.state == freshness.LOSS_IMMINENT else "warning", "pickup", pickup.id)
    return pickup


def confirm_handover(db: Session, pickup: Pickup, actor: User, received_kg: float | None) -> Pickup:
    case = pickup.case
    _require_single_recipient(case)
    if pickup.status != "arrived":
        raise Conflict("Handover can be confirmed once the pickup has arrived.", "PICKUP_NOT_ARRIVED")
    kg = received_kg if received_kg is not None else case.quantity_kg
    if kg <= 0 or kg > case.quantity_kg * 1.001:
        raise AppError(f"Received quantity must be between 0 and {case.quantity_kg:g} kg.", "INVALID_QUANTITY", 422)
    now = utcnow()
    pickup.status, pickup.handed_over_at, pickup.received_kg, pickup.confirmed_by = "completed", now, kg, actor.id
    case.status, case.recovered_kg, case.closed_at = "completed", kg, now
    case.lot.status = "recovered"
    prod, rung = case.lot.product, case.selected_rung
    meals = round(kg * prod.meals_per_kg, 1) if rung == "R1" else 0.0
    co2e = round(kg * prod.co2e_per_kg * CO2E_RUNG_FACTOR[rung], 1)
    db.add(SustainabilityMetric(org_id=case.org_id, case_id=case.id, recorded_on=now.date(), rung=rung, kg=kg, meals=meals, co2e_kg=co2e, source="recovery"))
    audit.record(db, case.org_id, actor, "handover.confirmed", "pickup", pickup.id, f"Handover confirmed: {kg:g} kg to {case.recipient.name}", {"received_kg": kg}, case.id)
    audit.record(db, case.org_id, actor, "case.completed", "recovery_case", case.id, f"{case.case_number} completed via {rung}", {"rung": rung, "co2e_kg": co2e, "meals": meals}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    events.publish(db, case.org_id, "lot.updated", {"lot_id": str(case.lot_id)})
    events.notify_roles(db, case.org_id, [sec.OPS, sec.RECOVERY], "recovery_complete", f"Recovered: {case.case_number}", f"{kg:g} kg via {rung}", "info", "recovery_case", case.id)
    return pickup


def cancel_case(db: Session, case: RecoveryCase, actor: User, note: str) -> RecoveryCase:
    if case.status in ("completed", "cancelled", "rejected"):
        raise Conflict("This case is already closed.", "CASE_CLOSED")
    from app.services import allocations as _alloc
    _alloc.release_all(db, case, actor, "case closed without recovery")
    case.status, case.closed_at = "cancelled", utcnow()
    case.lot.status = "available"
    for p in db.execute(select(Pickup).where(Pickup.case_id == case.id, Pickup.status.in_(("pending", "assigned", "scheduled", "in_transit", "arrived")))).scalars():
        p.status = "cancelled"
    audit.record(db, case.org_id, actor, "case.cancelled", "recovery_case", case.id, f"{case.case_number} closed without recovery", {"note": note}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return case


def snapshot_freshness(db: Session, lot: InventoryLot, note: str = "") -> freshness.Freshness:
    f = freshness.assess(lot.safe_until, lot.window_minutes, utcnow())
    db.add(FreshnessAssessment(lot_id=lot.id, remaining_minutes=f.remaining_minutes, percent=f.percent, state=f.state, note=note))
    lot.last_state = f.state
    return f
