"""Multi-recipient allocation endpoints (extends the recovery-case workflow)."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_owned, require
from app.core.errors import AppError, NotFound
from app.models import ACTIVE_ALLOCATION, Allocation, RecoveryCase, User
from app.schemas import (AllocCommitIn, AllocPlanIn, AllocReasonIn, AllocRespondIn, AllocSimIn, TransportEventIn)
from app.services import allocation as alg
from app.services import allocations as svc

router = APIRouter(tags=["allocations"])


def _case(db, case_id, user) -> RecoveryCase:
    return get_owned(db, RecoveryCase, case_id, user)


def _alloc(db, alloc_id, user) -> Allocation:
    return get_owned(db, Allocation, alloc_id, user)


@router.get("/allocations/active", dependencies=[Depends(require("pickups:read"))])
def active_allocations(db: DB, user: CurrentUser):
    """Offered/accepted multi-recipient allocations in the caller's organization (logistics worklist)."""
    stmt = select(Allocation).where(Allocation.status.in_(("offered", "accepted"))).order_by(Allocation.eta, Allocation.id).limit(100)
    if not user.is_platform_admin:
        stmt = stmt.where(Allocation.org_id == user.org_id)
    out = []
    for a in db.execute(stmt).scalars().all():
        c = db.get(RecoveryCase, a.case_id)
        out.append({"id": str(a.id), "case_id": str(a.case_id), "case_number": c.case_number if c else None, "recipient_name": a.recipient.name, "rung": a.rung,
                    "quantity_kg": a.quantity_kg, "status": a.status, "eta": a.eta.isoformat() if a.eta else None, "delay_minutes": a.delay_minutes})
    return out


@router.get("/recovery-cases/{case_id}/allocations", dependencies=[Depends(require("cases:read"))])
def list_allocations(case_id: uuid.UUID, db: DB, user: CurrentUser):
    return svc.summary(db, _case(db, case_id, user))


@router.post("/recovery-cases/{case_id}/allocation/plan", dependencies=[Depends(require("cases:read"))])
def plan_preview(case_id: uuid.UUID, body: AllocPlanIn, db: DB, user: CurrentUser):
    """Read-only preview. Creates nothing."""
    out = svc.preview(db, _case(db, case_id, user), body.strategy, body.allow_split)
    return {"simulated": False, "preview": True, "plan": out, "strategies": list(alg.STRATEGIES)}


@router.post("/recovery-cases/{case_id}/allocation/compare", dependencies=[Depends(require("simulate"))])
def compare(case_id: uuid.UUID, db: DB, user: CurrentUser):
    return svc.compare(db, _case(db, case_id, user))


@router.post("/recovery-cases/{case_id}/allocation/simulate", dependencies=[Depends(require("simulate"))])
def simulate(case_id: uuid.UUID, body: AllocSimIn, db: DB, user: CurrentUser):
    return svc.simulate(db, _case(db, case_id, user), body.scenario, recipient_id=body.recipient_id, capacity_kg=body.capacity_kg,
                        delay_minutes=body.delay_minutes, strategy=body.strategy)


@router.post("/recovery-cases/{case_id}/allocation/commit", status_code=201)
def commit(case_id: uuid.UUID, body: AllocCommitIn, db: DB, user: User = Depends(require("cases:approve"))):
    if not body.confirm:
        raise AppError("Committing reserves food quantity. Send confirm=true to proceed.", "CONFIRM_REQUIRED", 422)
    c = _case(db, case_id, user)
    out = svc.commit_plan(db, c, user, body.strategy, body.allow_split, body.note)
    db.commit()
    return {"allocation_ids": [str(i) for i in out["allocations"]], "plan": out["plan"], "summary": svc.summary(db, c)}


@router.post("/recovery-cases/{case_id}/allocation/approve")
def approve(case_id: uuid.UUID, body: AllocReasonIn, db: DB, user: User = Depends(require("cases:approve"))):
    c = _case(db, case_id, user)
    done = svc.approve_proposed(db, c, user, body.reason)
    db.commit()
    return {"offered": len(done), "summary": svc.summary(db, c)}


@router.post("/allocations/{alloc_id}/cancel")
def cancel(alloc_id: uuid.UUID, body: AllocReasonIn, db: DB, user: User = Depends(require("cases:approve"))):
    a = _alloc(db, alloc_id, user)
    if not body.reason.strip():
        raise AppError("A reason is required for a manual override.", "REASON_REQUIRED", 422)
    out = svc.cancel_allocation(db, a, user, body.reason)
    db.commit()
    return out


@router.post("/allocations/{alloc_id}/transport")
def transport(alloc_id: uuid.UUID, body: TransportEventIn, db: DB, user: User = Depends(require("pickups:write"))):
    a = _alloc(db, alloc_id, user)
    if body.kind == "delay" and body.minutes < 5:
        raise AppError("A delay must be at least 5 minutes.", "INVALID_MINUTES", 422)
    out = svc.report_transport(db, a, user, body.kind, body.minutes, body.reason)
    db.commit()
    return out


@router.post("/allocations/{alloc_id}/handover")
def handover(alloc_id: uuid.UUID, db: DB, received_kg: float | None = None, user: User = Depends(require("pickups:write"))):
    a = _alloc(db, alloc_id, user)
    out = svc.complete(db, a, user, received_kg)
    db.commit()
    return out


# ------------------------------------------------------------------ recipient side
@router.get("/recipient/allocations", dependencies=[Depends(require("recipient:inbox"))])
def recipient_inbox(db: DB, user: CurrentUser):
    rows = db.execute(select(Allocation).where(Allocation.recipient_id == user.recipient_id, Allocation.status.in_(("offered", "accepted")))
                      .order_by(Allocation.created_at)).scalars().all()
    return [{"id": str(a.id), "case_id": str(a.case_id), "quantity_kg": a.quantity_kg, "rung": a.rung, "status": a.status,
             "eta": a.eta.isoformat() if a.eta else None} for a in rows]


@router.post("/recipient/allocations/{alloc_id}/respond", dependencies=[Depends(require("recipient:respond"))])
def recipient_respond(alloc_id: uuid.UUID, body: AllocRespondIn, db: DB, user: CurrentUser):
    a = db.get(Allocation, alloc_id)
    if a is None or a.recipient_id != user.recipient_id:
        raise NotFound("We couldn't find that offer.", "NOT_FOUND")
    out = svc.respond(db, a, user, body.accept, body.reason, body.accepted_kg)
    db.commit()
    return out
