"""Allocation workflow: persistence, atomic quantity reservation, rejection / transport-failure replanning.

Concurrency model
-----------------
* Quantity is reserved with ONE conditional UPDATE on the lot row
      UPDATE inventory_lots SET reserved_kg = reserved_kg + :kg WHERE id = :id AND reserved_kg + :kg <= quantity_kg
  The database serialises writers on that row, so two simultaneous requests can never reserve the same kg
  (rowcount 0 -> AllocationConflict). Works identically on PostgreSQL and SQLite. A CHECK constraint backs it up.
* Every allocation state change is a conditional UPDATE ... WHERE status IN (<allowed>) AND version = :v.
  Exactly one caller wins the transition; duplicates / retries see rowcount 0 and become idempotent no-ops, so a
  rejection delivered twice releases the quantity once.
* A partial unique index allows only one live allocation per (case, recipient).
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import case as sa_case
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import security as sec
from app.core.database import utcnow
from app.core.errors import AppError, Conflict
from app.models import (
    ACTIVE_ALLOCATION,
    Allocation,
    InventoryLot,
    Recipient,
    RecoveryCase,
    SustainabilityMetric,
    User,
)
from app.services import allocation as alg
from app.services import audit, cases, events, freshness
from app.services.cases import CO2E_RUNG_FACTOR

EPS = alg.EPS
MAX_AUTO_REPLANS = 5  # loop guard: after this many allocation replans a human must intervene
ENGINE_LABEL = "Allocation engine (rule-based, deterministic)"


# ---------------------------------------------------------------- inputs
def recipient_load(db: Session, recipient_id) -> float:
    """kg currently committed to a recipient across every case (live allocations only)."""
    return float(db.execute(select(func.coalesce(func.sum(Allocation.quantity_kg), 0.0))
                            .where(Allocation.recipient_id == recipient_id, Allocation.status.in_(ACTIVE_ALLOCATION))).scalar_one())


def candidates(db: Session, capacity_overrides: dict[str, float] | None = None) -> list[alg.Candidate]:
    capacity_overrides = capacity_overrides or {}
    out = []
    for r in db.execute(select(Recipient).where(Recipient.status == "active").order_by(Recipient.name)).scalars():
        cap = capacity_overrides.get(str(r.id), r.capacity_kg)
        out.append(alg.Candidate(str(r.id), r.name, list(r.accepts_rungs), r.acceptance_rate, r.distance_km,
                                 max(cap - recipient_load(db, r.id), 0.0)))
    return out


def live_recipient_ids(db: Session, case_id) -> list[str]:
    return [str(x) for x in db.execute(select(Allocation.recipient_id).where(Allocation.case_id == case_id, Allocation.status.in_(ACTIVE_ALLOCATION))).scalars()]


def alloc_lot(db: Session, case: RecoveryCase, remaining_minutes: int | None = None, evidence_score: float | None = None) -> alg.AllocLot:
    lot = db.get(InventoryLot, case.lot_id)
    db.refresh(lot)
    li = cases.lot_input(db, lot, case.id)
    return alg.AllocLot(
        quantity_kg=lot.quantity_kg, remaining_minutes=li.remaining_minutes if remaining_minutes is None else remaining_minutes,
        freshness_percent=li.freshness_percent, human_grade_eligible=li.human_grade_eligible, feed_eligible=li.feed_eligible,
        evidence_score=li.evidence_score if evidence_score is None else evidence_score, already_reserved_kg=min(lot.reserved_kg or 0.0, lot.quantity_kg),
    )


def _constraints(case: RecoveryCase, extra_excluded=(), extra_delay: int = 0, allow_split: bool = True) -> alg.AllocConstraints:
    return alg.AllocConstraints(case.pickup_delay_min + extra_delay, case.handover_buffer_min, list(case.excluded_rungs),
                                sorted(set(case.excluded_recipients) | set(extra_excluded)), allow_split)


# ---------------------------------------------------------------- preview / simulation (read-only)
def preview(db: Session, case: RecoveryCase, strategy: str = "max_recovery", allow_split: bool = True) -> dict:
    """Pure read: never writes. Excludes recipients that already hold a live slice of this case."""
    plan = alg.optimize(alloc_lot(db, case), candidates(db), _constraints(case, live_recipient_ids(db, case.id), allow_split=allow_split), strategy)
    return plan.to_dict()


def compare(db: Session, case: RecoveryCase) -> dict:
    lot, cands, cons = alloc_lot(db, case), candidates(db), _constraints(case, live_recipient_ids(db, case.id))
    plans = alg.compare_strategies(lot, cands, cons)
    return {"simulated": True, "label": "Estimates from stored data and fixed heuristics; nothing was created, reserved or sent.",
            "strategies": [{"strategy": p.strategy, "label": alg.STRATEGY_LABELS[p.strategy], **p.to_dict()} for p in plans],
            "baseline_single_recipient": alg.baseline_plan(lot, cands, cons)}


SCENARIOS = ("none", "recipient_rejection", "capacity_reduction", "vehicle_delay", "missing_evidence", "no_feasible_option")


def simulate(db: Session, case: RecoveryCase, kind: str, *, recipient_id: str | None = None, capacity_kg: float | None = None,
             delay_minutes: int = 0, strategy: str = "max_recovery") -> dict:
    """Before/after what-if. Read-only by construction: no flush, no add, no events."""
    if kind not in SCENARIOS:
        raise AppError("Unknown scenario.", "UNKNOWN_SCENARIO", 422)
    lot, cands = alloc_lot(db, case), candidates(db)
    live = live_recipient_ids(db, case.id)
    before = alg.optimize(lot, cands, _constraints(case, live), strategy)
    after_lot, after_cands, extra_ex, delay = lot, cands, list(live), 0
    changes = []
    if kind == "recipient_rejection":
        if not recipient_id:
            raise AppError("Choose a recipient to simulate a rejection.", "RECIPIENT_REQUIRED", 422)
        extra_ex.append(recipient_id)
        changes.append(f"Recipient {recipient_id} rejects the lot.")
    elif kind == "capacity_reduction":
        if not recipient_id or capacity_kg is None:
            raise AppError("Choose a recipient and a new capacity.", "CAPACITY_REQUIRED", 422)
        after_cands = [alg.Candidate(c.id, c.name, c.accepts_rungs, c.acceptance_rate, c.distance_km, min(c.remaining_capacity_kg, max(capacity_kg, 0.0))) if c.id == recipient_id else c for c in cands]
        changes.append(f"Recipient capacity reduced to {capacity_kg:g} kg.")
    elif kind == "vehicle_delay":
        delay = max(delay_minutes, 0)
        changes.append(f"Pickup delayed by {delay} min.")
    elif kind == "missing_evidence":
        after_lot = alg.AllocLot(**{**lot.__dict__, "evidence_score": 0.0})
        changes.append("Condition evidence is missing.")
    elif kind == "no_feasible_option":
        after_lot = alg.AllocLot(**{**lot.__dict__, "remaining_minutes": 0})
        changes.append("Remaining safe time is zero.")
    after = alg.optimize(after_lot, after_cands, _constraints(case, extra_ex, delay), strategy)
    delta = {"allocated_kg": round(after.allocated_kg - before.allocated_kg, 6), "unallocated_kg": round(after.unallocated_kg - before.unallocated_kg, 6)}
    return {"simulated": True, "scenario": kind, "changes": changes, "before": before.to_dict(), "after": after.to_dict(), "delta": delta,
            "note": "Simulation only. No donation, notification, reservation or transport booking was made."}


# ---------------------------------------------------------------- atomic quantity reservation
def reserve(db: Session, lot_id, kg: float) -> None:
    res = db.execute(update(InventoryLot).where(InventoryLot.id == lot_id, InventoryLot.reserved_kg + kg <= InventoryLot.quantity_kg + EPS)
                     .values(reserved_kg=InventoryLot.reserved_kg + kg).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise Conflict("That quantity was just allocated elsewhere. Refresh and plan again.", "ALLOCATION_CONFLICT")


def release(db: Session, lot_id, kg: float) -> None:
    new = InventoryLot.reserved_kg - kg
    res = db.execute(update(InventoryLot).where(InventoryLot.id == lot_id, InventoryLot.reserved_kg >= kg - EPS)
                     .values(reserved_kg=sa_case((new < 0, 0.0), else_=new)).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise Conflict("Reserved quantity is inconsistent; refusing to release more than is reserved.", "RESERVATION_INVARIANT")


def _transition(db: Session, alloc: Allocation, to: str, allowed: tuple[str, ...], **values) -> bool:
    """Compare-and-set. True only for the single caller that performed the transition."""
    res = db.execute(update(Allocation).where(Allocation.id == alloc.id, Allocation.status.in_(allowed), Allocation.version == alloc.version)
                     .values(status=to, version=Allocation.version + 1, updated_at=utcnow(), **values).execution_options(synchronize_session=False))
    if res.rowcount == 1:
        db.refresh(alloc)
        return True
    db.refresh(alloc)
    return False


# ---------------------------------------------------------------- commit a plan
def _sync_case_status(db: Session, case: RecoveryCase) -> None:
    rows = db.execute(select(Allocation.status).where(Allocation.case_id == case.id, Allocation.status.in_(ACTIVE_ALLOCATION))).scalars().all()
    if case.status in ("completed", "cancelled", "rejected"):
        return
    if "proposed" in rows:
        case.status = "pending_approval"
    elif "offered" in rows:
        case.status = "awaiting_recipient"
    elif "accepted" in rows:
        case.status = "accepted"
    else:
        case.status = "pending_approval"


def _create_lines(db: Session, case: RecoveryCase, plan: alg.AllocationPlan, actor: User | None, label: str | None) -> list[Allocation]:
    created = []
    now = utcnow()
    for ln in plan.lines:
        reserve(db, case.lot_id, ln.quantity_kg)
        a = Allocation(org_id=case.org_id, case_id=case.id, lot_id=case.lot_id, recipient_id=uuid.UUID(ln.recipient_id), rung=ln.rung,
                       quantity_kg=ln.quantity_kg, status="proposed", plan_version=case.plan_version, strategy=plan.strategy,
                       engine_version=plan.engine_version, needed_minutes=ln.needed_minutes, why=ln.why[:300],
                       eta=now + timedelta(minutes=ln.needed_minutes))
        db.add(a)
        try:
            db.flush()
        except Exception as e:  # unique live-recipient index
            raise Conflict("That recipient already holds a live allocation for this case.", "DUPLICATE_ALLOCATION") from e
        audit.record(db, case.org_id, actor, "allocation.created", "allocation", a.id,
                     f"{ln.quantity_kg:g} kg proposed to {ln.recipient_name} via {ln.rung}",
                     {"kg": ln.quantity_kg, "rung": ln.rung, "strategy": plan.strategy, "engine": plan.engine_version}, case.id, actor_label=None if actor else label)
        created.append(a)
    return created


def commit_plan(db: Session, case: RecoveryCase, actor: User, strategy: str = "max_recovery", allow_split: bool = True, note: str = "") -> dict:
    if case.status in ("completed", "cancelled", "rejected"):
        raise Conflict("This case is closed.", "CASE_CLOSED")
    if case.recipient_id is not None and case.status != "pending_approval":
        raise Conflict("This case already follows the single-recipient workflow.", "CASE_SINGLE_RECIPIENT")
    plan = alg.optimize(alloc_lot(db, case), candidates(db), _constraints(case, live_recipient_ids(db, case.id), allow_split=allow_split), strategy)
    if not plan.lines:
        audit.record(db, case.org_id, None, "allocation.infeasible", "recovery_case", case.id, "No feasible allocation could be created",
                     {"warnings": plan.warnings}, case.id, actor_label=ENGINE_LABEL)
        raise Conflict("No safe, feasible allocation exists. " + (plan.explanation or ""), "NO_FEASIBLE_ALLOCATION")
    created = _create_lines(db, case, plan, actor, None)
    case.status = "pending_approval"
    audit.record(db, case.org_id, actor, "allocation.plan_committed", "recovery_case", case.id,
                 f"{len(created)} allocation(s) proposed ({plan.allocated_kg:g} kg, {plan.unallocated_kg:g} kg unallocated)",
                 {"strategy": strategy, "note": note}, case.id)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return {"allocations": [a.id for a in created], "plan": plan.to_dict()}


def approve_proposed(db: Session, case: RecoveryCase, actor: User, note: str = "") -> list[Allocation]:
    """Human approval step: proposed -> offered, recipients notified. Idempotent."""
    rows = db.execute(select(Allocation).where(Allocation.case_id == case.id, Allocation.status == "proposed")).scalars().all()
    done = []
    for a in rows:
        if _transition(db, a, "offered", ("proposed",)):
            done.append(a)
            audit.record(db, case.org_id, actor, "allocation.offered", "allocation", a.id,
                         f"{actor.full_name} approved {a.quantity_kg:g} kg for {a.recipient.name}", {"note": note}, case.id)
            events.publish(db, case.org_id, "recovery.assigned", {"case_id": str(case.id), "allocation_id": str(a.id)}, recipient_id=a.recipient_id)
            events.notify_recipient_users(db, a.recipient_id, "recipient_offer", f"New lot offered: {case.lot.product.name}",
                                          f"{a.quantity_kg:g} kg available for pickup", "allocation", a.id)
    _sync_case_status(db, case)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return done


# ---------------------------------------------------------------- replanning of released quantity
def replan_released(db: Session, case: RecoveryCase, actor: User | None, reason: str, *, extra_excluded=(), extra_delay: int = 0) -> dict:
    """Re-run the optimizer for ONLY the unreserved quantity. Confirmed/in-progress slices are never touched."""
    db.refresh(db.get(InventoryLot, case.lot_id))
    if case.replan_count >= MAX_AUTO_REPLANS:
        audit.record(db, case.org_id, None, "allocation.replan_limit", "recovery_case", case.id,
                     f"Automatic replanning stopped after {case.replan_count} attempts; human intervention required", {"reason": reason}, case.id, actor_label=ENGINE_LABEL)
        events.notify_roles(db, case.org_id, [sec.RECOVERY, sec.ADMIN], "recovery_attention", f"Human intervention needed: {case.case_number}", reason, "critical", "recovery_case", case.id)
        return {"replanned": False, "requires_human_intervention": True, "plan": None, "reason": "REPLAN_LIMIT"}
    case.replan_count += 1
    case.plan_version += 1
    plan = alg.optimize(alloc_lot(db, case), candidates(db), _constraints(case, [*live_recipient_ids(db, case.id), *extra_excluded], extra_delay))
    created = _create_lines(db, case, plan, actor, ENGINE_LABEL)
    human = plan.status in ("infeasible", "blocked", "partial")
    audit.record(db, case.org_id, actor, "recovery.plan_recalculated", "recovery_case", case.id,
                 f"Replanned after: {reason}. {plan.explanation}"[:300], {"status": plan.status, "new_allocations": len(created), "unallocated_kg": plan.unallocated_kg}, case.id,
                 actor_label=None if actor else ENGINE_LABEL)
    if human:
        events.notify_roles(db, case.org_id, [sec.RECOVERY, sec.ADMIN], "recovery_attention",
                            f"{'No feasible option' if not created else 'Partial replan'}: {case.case_number}", plan.explanation[:290], "critical" if not created else "warning", "recovery_case", case.id)
    if created:
        events.notify_roles(db, case.org_id, [sec.RECOVERY, sec.ADMIN], "recovery_approval", f"Replan needs approval: {case.case_number}", reason[:290], "warning", "recovery_case", case.id)
    _sync_case_status(db, case)
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return {"replanned": True, "requires_human_intervention": human, "plan": plan.to_dict(), "new_allocations": [a.id for a in created]}


# ---------------------------------------------------------------- recipient response
def respond(db: Session, alloc: Allocation, actor: User, accept: bool, reason: str | None = None, accepted_kg: float | None = None) -> dict:
    if actor.recipient_id != alloc.recipient_id:
        raise Conflict("This offer is not addressed to you.", "OFFER_NOT_OPEN")
    case = db.get(RecoveryCase, alloc.case_id)
    name = alloc.recipient.name
    if alloc.status in ("rejected", "cancelled", "failed") and not accept:
        return {"duplicate": True, "status": alloc.status, "released_kg": 0.0}
    if alloc.status == "accepted" and accept:
        return {"duplicate": True, "status": "accepted", "released_kg": 0.0}
    if accept:
        if alloc.status != "offered":
            raise Conflict("This offer is no longer open.", "OFFER_NOT_OPEN")
        original = alloc.quantity_kg
        take = original if accepted_kg is None else accepted_kg
        if take <= 0 or take > original + EPS:
            raise AppError(f"Accepted quantity must be between 0 and {original:g} kg.", "INVALID_QUANTITY", 422)
        extra = {"responded_at": utcnow(), "quantity_kg": take} if take < original - EPS else {"responded_at": utcnow()}
        if not _transition(db, alloc, "accepted", ("offered",), **extra):
            return {"duplicate": True, "status": alloc.status, "released_kg": 0.0}
        audit.record(db, case.org_id, actor, "recipient.accepted", "allocation", alloc.id, f"{name} accepted {take:g} kg", {"kg": take, "offered_kg": original}, case.id)
        result = {"duplicate": False, "status": "accepted", "released_kg": 0.0}
        if take < original - EPS:
            release(db, case.lot_id, original - take)
            result["released_kg"] = round(original - take, 6)
            audit.record(db, case.org_id, actor, "recipient.partial_accept", "allocation", alloc.id, f"{name} accepted {take:g} of {original:g} kg", {}, case.id)
            result["replan"] = replan_released(db, case, actor, f"{name} accepted only {take:g} of {original:g} kg")
        else:
            events.notify_roles(db, case.org_id, [sec.OPS, sec.RECOVERY, sec.LOGISTICS], "recipient_response", f"{name} accepted {case.case_number}", "Schedule a pickup.", "info", "allocation", alloc.id)
        _sync_case_status(db, case)
        events.publish(db, case.org_id, "recipient.accepted", {"case_id": str(case.id)})
        return result
    return _reject(db, case, alloc, actor, reason or "", ("offered", "accepted"), f"{name} rejected")


def _reject(db: Session, case: RecoveryCase, alloc: Allocation, actor: User | None, reason: str, allowed: tuple[str, ...], label: str, to: str = "rejected", extra_delay: int = 0, exclude_recipient: bool = True) -> dict:
    qty = alloc.quantity_kg
    if not _transition(db, alloc, to, allowed, responded_at=utcnow(), response_reason=reason[:300]):
        return {"duplicate": True, "status": alloc.status, "released_kg": 0.0}  # lost the race / duplicate delivery -> no double release
    release(db, case.lot_id, qty)
    if exclude_recipient and str(alloc.recipient_id) not in case.excluded_recipients:
        case.excluded_recipients = [*case.excluded_recipients, str(alloc.recipient_id)]
    audit.record(db, case.org_id, actor, f"allocation.{to}", "allocation", alloc.id, f"{label}: {qty:g} kg released" + (f" ({reason})" if reason else ""),
                 {"kg": qty, "reason": reason}, case.id)
    events.notify_roles(db, case.org_id, [sec.OPS, sec.RECOVERY], "recipient_response", f"{alloc.recipient.name} {to} {case.case_number}", reason[:290], "warning", "allocation", alloc.id)
    out = replan_released(db, case, actor, f"{label}" + (f" ({reason})" if reason else ""), extra_excluded=[str(alloc.recipient_id)], extra_delay=extra_delay)
    return {"duplicate": False, "status": to, "released_kg": qty, "replan": out}


def cancel_allocation(db: Session, alloc: Allocation, actor: User, reason: str) -> dict:
    case = db.get(RecoveryCase, alloc.case_id)
    return _reject(db, case, alloc, actor, reason, ACTIVE_ALLOCATION, f"{actor.full_name} cancelled the allocation to {alloc.recipient.name}", "cancelled", exclude_recipient=False)


# ---------------------------------------------------------------- transport delay / failure
def report_transport(db: Session, alloc: Allocation, actor: User, kind: str, minutes: int, reason: str) -> dict:
    """delay: keep the slice if the deadline still holds, otherwise re-plan only that slice.
    failure: release only the affected slice and re-plan it. No alternative vehicle is modelled, so none is claimed."""
    if kind not in ("delay", "failure"):
        raise AppError("Kind must be 'delay' or 'failure'.", "INVALID_KIND", 422)
    if alloc.status not in ("offered", "accepted"):
        raise Conflict("Only an offered or accepted allocation can have a transport event.", "ALLOCATION_NOT_ACTIVE")
    case = db.get(RecoveryCase, alloc.case_id)
    lot = db.get(InventoryLot, alloc.lot_id)
    f = freshness.assess(lot.safe_until, lot.window_minutes, utcnow())
    if kind == "delay":
        needed = alloc.needed_minutes + minutes + alloc.delay_minutes
        margin = f.remaining_minutes - needed
        audit.record(db, case.org_id, actor, "transport.delayed", "allocation", alloc.id, f"Transport delayed {minutes} min: {reason}"[:300],
                     {"minutes": minutes, "margin_minutes": margin, "remaining_minutes": f.remaining_minutes}, case.id)
        if margin >= 0:
            db.execute(update(Allocation).where(Allocation.id == alloc.id).values(delay_minutes=Allocation.delay_minutes + minutes, eta=(alloc.eta or utcnow()) + timedelta(minutes=minutes), version=Allocation.version + 1).execution_options(synchronize_session=False))
            db.refresh(alloc)
            events.publish(db, case.org_id, "pickup.delayed", {"case_id": str(case.id), "minutes": minutes})
            return {"outcome": "still_feasible", "margin_minutes": margin, "requires_human_intervention": False,
                    "note": "ETA updated from the engine's heuristic; no routing data was used."}
    audit.record(db, case.org_id, actor, "transport.failed" if kind == "failure" else "transport.deadline_breach", "allocation", alloc.id,
                 (f"Transport failure: {reason}" if kind == "failure" else f"Delay of {minutes} min breaks the deadline: {reason}")[:300], {"kg": alloc.quantity_kg}, case.id)
    out = _reject(db, case, alloc, actor, reason, ("offered", "accepted"), "Transport failed" if kind == "failure" else "Delay breaks deadline", "failed",
                  extra_delay=minutes if kind == "delay" else 0, exclude_recipient=False)
    out["outcome"] = "replanned" if (out.get("replan") or {}).get("new_allocations") else "needs_human"
    out["requires_human_intervention"] = bool((out.get("replan") or {}).get("requires_human_intervention", True))
    out["note"] = "No alternative transport is modelled; only other recipients were evaluated."
    return out


# ---------------------------------------------------------------- handover
def complete(db: Session, alloc: Allocation, actor: User, received_kg: float | None) -> dict:
    case = db.get(RecoveryCase, alloc.case_id)
    if alloc.status == "completed":
        return {"duplicate": True, "status": "completed", "case_status": case.status}
    if alloc.status != "accepted":
        raise Conflict("Handover can be confirmed only for an accepted allocation.", "ALLOCATION_NOT_ACCEPTED")
    kg = alloc.quantity_kg if received_kg is None else received_kg
    if kg <= 0 or kg > alloc.quantity_kg + EPS:
        raise AppError(f"Received quantity must be between 0 and {alloc.quantity_kg:g} kg.", "INVALID_QUANTITY", 422)
    shortfall = round(alloc.quantity_kg - kg, 6)
    if not _transition(db, alloc, "completed", ("accepted",), completed_at=utcnow(), received_kg=kg):
        return {"duplicate": True, "status": alloc.status, "case_status": case.status}
    if shortfall > EPS:
        release(db, case.lot_id, shortfall)
    prod = case.lot.product
    meals = round(kg * prod.meals_per_kg, 1) if alloc.rung == "R1" else 0.0
    co2e = round(kg * prod.co2e_per_kg * CO2E_RUNG_FACTOR[alloc.rung], 1)
    db.add(SustainabilityMetric(org_id=case.org_id, case_id=case.id, recorded_on=utcnow().date(), rung=alloc.rung, kg=kg, meals=meals, co2e_kg=co2e, source="recovery"))
    audit.record(db, case.org_id, actor, "handover.confirmed", "allocation", alloc.id, f"Handover confirmed: {kg:g} kg to {alloc.recipient.name}" + (f" ({shortfall:g} kg short)" if shortfall > EPS else ""),
                 {"received_kg": kg, "shortfall_kg": shortfall}, case.id)
    recovered = float(db.execute(select(func.coalesce(func.sum(Allocation.received_kg), 0.0)).where(Allocation.case_id == case.id, Allocation.status == "completed")).scalar_one())
    live = db.execute(select(func.count()).select_from(Allocation).where(Allocation.case_id == case.id, Allocation.status.in_(ACTIVE_ALLOCATION))).scalar_one()
    case.recovered_kg = recovered
    lot = db.get(InventoryLot, case.lot_id)
    db.refresh(lot)
    result = {"duplicate": False, "status": "completed", "recovered_kg": recovered, "shortfall_kg": shortfall}
    if live == 0 and recovered >= lot.quantity_kg - 0.001 * lot.quantity_kg:
        case.status, case.closed_at = "completed", utcnow()
        lot.status = "recovered"
        audit.record(db, case.org_id, actor, "case.completed", "recovery_case", case.id, f"{case.case_number} completed: {recovered:g} kg recovered across allocations", {"recovered_kg": recovered}, case.id)
        events.publish(db, case.org_id, "lot.updated", {"lot_id": str(case.lot_id)})
    elif live == 0:
        result["next_action"] = f"{round(lot.quantity_kg - recovered, 3):g} kg not recovered. Replan the remainder or close the case."
    else:
        _sync_case_status(db, case)
    result["case_status"] = case.status
    events.publish(db, case.org_id, "recovery.updated", {"case_id": str(case.id)})
    return result


# ---------------------------------------------------------------- hooks used by the single-recipient workflow
def release_all(db: Session, case: RecoveryCase, actor: User | None, reason: str) -> float:
    """Used when a case is rejected / cancelled: free every live slice exactly once."""
    freed = 0.0
    for a in db.execute(select(Allocation).where(Allocation.case_id == case.id, Allocation.status.in_(ACTIVE_ALLOCATION))).scalars().all():
        qty = a.quantity_kg
        if _transition(db, a, "cancelled", ACTIVE_ALLOCATION, responded_at=utcnow(), response_reason=reason[:300]):
            release(db, case.lot_id, qty)
            freed += qty
            audit.record(db, case.org_id, actor, "allocation.cancelled", "allocation", a.id, f"Allocation to {a.recipient.name} cancelled: {reason}"[:300], {"kg": qty}, case.id)
    return freed


def has_live(db: Session, case_id) -> bool:
    return db.execute(select(Allocation.id).where(Allocation.case_id == case_id, Allocation.status.in_(ACTIVE_ALLOCATION)).limit(1)).first() is not None


def summary(db: Session, case: RecoveryCase) -> dict:
    lot = db.get(InventoryLot, case.lot_id)
    db.refresh(lot)
    rows = db.execute(select(Allocation).where(Allocation.case_id == case.id).order_by(Allocation.created_at, Allocation.id)).scalars().all()
    by: dict[str, float] = {}
    for a in rows:
        by[a.status] = round(by.get(a.status, 0.0) + a.quantity_kg, 6)
    return {
        "case_id": str(case.id), "lot_quantity_kg": lot.quantity_kg, "reserved_kg": round(lot.reserved_kg or 0.0, 6),
        "unallocated_kg": round(max(lot.quantity_kg - (lot.reserved_kg or 0.0), 0.0), 6), "kg_by_status": by,
        "remaining_minutes": freshness.assess(lot.safe_until, lot.window_minutes, utcnow()).remaining_minutes,
        "plan_version": case.plan_version, "replan_count": case.replan_count, "excluded_recipients": list(case.excluded_recipients),
        "allocations": [{
            "id": str(a.id), "recipient_id": str(a.recipient_id), "recipient_name": a.recipient.name, "rung": a.rung, "quantity_kg": a.quantity_kg,
            "status": a.status, "plan_version": a.plan_version, "strategy": a.strategy, "engine_version": a.engine_version, "why": a.why,
            "eta": a.eta.isoformat() if a.eta else None, "delay_minutes": a.delay_minutes, "response_reason": a.response_reason,
            "received_kg": a.received_kg, "recipient_capacity_kg": a.recipient.capacity_kg, "recipient_remaining_kg": round(max(a.recipient.capacity_kg - recipient_load(db, a.recipient_id), 0.0), 6),
        } for a in rows],
    }
