import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Page, get_owned, paged, require
from app.api.serializers import freshness_out, iso, pickup_out, recipient_out
from app.core import security as sec
from app.core.errors import Forbidden, NotFound
from app.models import Pickup, Recipient, RecoveryCase, User
from app.schemas import (
    DelayIn,
    HandoverIn,
    PickupIn,
    PickupStatusIn,
    RecipientResponseIn,
)
from app.services import cases

router = APIRouter(tags=["logistics"])


@router.get("/recipients", dependencies=[Depends(require("recipients:read"))])
def directory(db: DB):
    rows = db.execute(select(Recipient).where(Recipient.status == "active").order_by(Recipient.name)).scalars().all()
    return [recipient_out(r) for r in rows]


@router.get("/users/logistics", dependencies=[Depends(require("pickups:schedule"))])
def logistics_users(db: DB, user: CurrentUser):
    rows = db.execute(select(User).where(User.org_id == user.org_id, User.role == sec.LOGISTICS, User.is_active.is_(True))).scalars().all()
    return [{"id": str(u.id), "name": u.full_name} for u in rows]


@router.get("/pickups", dependencies=[Depends(require("pickups:read"))])
def list_pickups(db: DB, user: CurrentUser, p: Page = Depends(), status: str | None = None, active: bool | None = None):
    stmt = select(Pickup)
    if not user.is_platform_admin:
        stmt = stmt.where(Pickup.org_id == user.org_id)
    if user.role == sec.LOGISTICS:
        stmt = stmt.where((Pickup.logistics_user_id == user.id) | (Pickup.logistics_user_id.is_(None)))
    if status:
        stmt = stmt.where(Pickup.status == status)
    if active:
        stmt = stmt.where(Pickup.status.in_(("pending", "assigned", "scheduled", "in_transit", "arrived")))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Pickup.scheduled_for).offset(p.offset).limit(p.page_size)).unique().scalars().all()
    return paged([pickup_out(x) for x in rows], total, p)


@router.post("/recovery-cases/{case_id}/pickup", status_code=201, dependencies=[Depends(require("pickups:schedule"))])
def schedule(case_id: uuid.UUID, body: PickupIn, db: DB, user: User = Depends(require("pickups:write"))):
    case = get_owned(db, RecoveryCase, case_id, user)
    p = cases.schedule_pickup(db, case, user, body.scheduled_for, body.logistics_user_id)
    db.commit()
    return pickup_out(p)


def _pickup(db, pid, user) -> Pickup:
    p = get_owned(db, Pickup, pid, user)
    if user.role == sec.LOGISTICS and p.logistics_user_id not in (None, user.id):
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    return p


@router.patch("/pickups/{pickup_id}/status")
def set_status(pickup_id: uuid.UUID, body: PickupStatusIn, db: DB, user: User = Depends(require("pickups:write"))):
    p = cases.advance_pickup(db, _pickup(db, pickup_id, user), user, body.status)
    db.commit()
    return pickup_out(p)


@router.post("/pickups/{pickup_id}/delay")
def delay(pickup_id: uuid.UUID, body: DelayIn, db: DB, user: User = Depends(require("pickups:write"))):
    p = cases.delay_pickup(db, _pickup(db, pickup_id, user), user, body.minutes, body.reason)
    db.commit()
    return pickup_out(p)


@router.post("/pickups/{pickup_id}/handover")
def handover(pickup_id: uuid.UUID, body: HandoverIn, db: DB, user: CurrentUser):
    """Logistics/ops confirm handover; a recipient may confirm only for their own case."""
    granted = sec.ROLE_PERMS.get(user.role, set())
    p = db.get(Pickup, pickup_id)
    if not p:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    if "pickups:write" in granted:
        p = _pickup(db, pickup_id, user)
    elif "pickups:handover_own" in granted and p.case.recipient_id == user.recipient_id and user.recipient_id:
        pass
    else:
        raise Forbidden("Your role doesn't have access to this action.", "FORBIDDEN_ROLE")
    cases.confirm_handover(db, p, user, body.received_kg)
    db.commit()
    return pickup_out(p)


# ---- Recipient experience ------------------------------------------------------
def _recipient_view(c: RecoveryCase, pickups: list[Pickup]) -> dict:
    return {
        "id": str(c.id), "case_number": c.case_number, "status": c.status, "rung": c.selected_rung,
        "product": c.lot.product.name, "category": c.lot.product.category, "quantity_kg": c.quantity_kg,
        "storage": c.lot.storage, "plant_city": c.lot.plant.city, "safe_until": iso(c.lot.safe_until),
        "freshness": freshness_out(c.lot), "pickup": pickup_out(pickups[-1]) if pickups else None,
        "note": "foodAgent supports your decision. Please apply your own food-safety checks on receipt.",
    }


@router.get("/recipient/cases", dependencies=[Depends(require("recipient:inbox"))])
def inbox(db: DB, user: CurrentUser, status: str | None = Query(None)):
    if not user.recipient_id:
        return []
    stmt = select(RecoveryCase).where(RecoveryCase.recipient_id == user.recipient_id, RecoveryCase.status.in_(
        ("awaiting_recipient", "accepted", "pickup_scheduled", "in_transit", "completed")))
    if status:
        stmt = stmt.where(RecoveryCase.status == status)
    rows = db.execute(stmt.order_by(RecoveryCase.created_at.desc()).limit(100)).unique().scalars().all()
    out = []
    for c in rows:
        pk = db.execute(select(Pickup).where(Pickup.case_id == c.id).order_by(Pickup.created_at)).unique().scalars().all()
        out.append(_recipient_view(c, pk))
    return out


@router.post("/recipient/cases/{case_id}/respond", dependencies=[Depends(require("recipient:respond"))])
def respond(case_id: uuid.UUID, body: RecipientResponseIn, db: DB, user: CurrentUser):
    case = db.get(RecoveryCase, case_id)
    if not case or case.recipient_id != user.recipient_id or not user.recipient_id:
        raise NotFound("We couldn't find that offer.", "NOT_FOUND")
    if not body.accept and not (body.reason and body.reason.strip()):
        from app.core.errors import AppError
        raise AppError("Please tell us why you can't take this lot.", "REASON_REQUIRED", 422)
    cases.recipient_respond(db, case, user, body.accept, body.reason)
    db.commit()
    return {"ok": True, "status": case.status}
