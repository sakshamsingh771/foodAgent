import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser, Page, ensure_org, get_owned, paged, require
from app.api.serializers import iso, lot_out
from app.core.database import utcnow
from app.core.errors import AppError
from app.models import User
from app.models import AuditEvent, FreshnessAssessment, InventoryLot, Plant, Product, RecoveryCase
from app.schemas import LotAdjustIn, LotIn
from app.services import audit, cases, events, freshness

router = APIRouter(tags=["inventory"])


def _org_filter(model, user):
    return [] if user.is_platform_admin else [model.org_id == user.org_id]


def open_case_map(db, lot_ids):
    if not lot_ids:
        return {}
    rows = db.execute(select(RecoveryCase.lot_id, RecoveryCase.id, RecoveryCase.case_number, RecoveryCase.status)
                      .where(RecoveryCase.lot_id.in_(lot_ids), RecoveryCase.status.in_(cases.ACTIVE_CASE))).all()
    return {r.lot_id: {"id": str(r.id), "case_number": r.case_number, "status": r.status} for r in rows}


@router.get("/lots", dependencies=[Depends(require("lots:read"))])
def list_lots(db: DB, user: CurrentUser, p: Page = Depends(), status: str | None = None, product_id: uuid.UUID | None = None,
              plant_id: uuid.UUID | None = None, urgency: str | None = Query(None, pattern="^(SAFE|ACT_SOON|LOSS_IMMINENT|AT_RISK)$"),
              q: str | None = Query(None, max_length=60), sort: str = Query("time_to_loss", pattern="^(time_to_loss|quantity|created)$")):
    """Active inventory is filtered/sorted by computed freshness; history statuses page in SQL."""
    stmt = select(InventoryLot).where(*_org_filter(InventoryLot, user))
    stmt = stmt.where(InventoryLot.status == status) if status else stmt.where(InventoryLot.status.in_(("available", "in_recovery")))
    if product_id:
        stmt = stmt.where(InventoryLot.product_id == product_id)
    if plant_id:
        stmt = stmt.where(InventoryLot.plant_id == plant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.join(Product, Product.id == InventoryLot.product_id).where(or_(InventoryLot.lot_code.ilike(like), Product.name.ilike(like)))
    now = utcnow()
    lots = db.execute(stmt.order_by(InventoryLot.safe_until).limit(2000)).unique().scalars().all()
    rows = [(l, freshness.assess(l.safe_until, l.window_minutes, now)) for l in lots]
    if urgency == "AT_RISK":
        rows = [r for r in rows if r[1].state != freshness.SAFE]
    elif urgency:
        rows = [r for r in rows if r[1].state == urgency]
    if sort == "quantity":
        rows.sort(key=lambda r: -r[0].quantity_kg)
    elif sort == "created":
        rows.sort(key=lambda r: r[0].created_at, reverse=True)
    else:
        rows.sort(key=lambda r: r[1].remaining_minutes)
    total, page_rows = len(rows), rows[p.offset: p.offset + p.page_size]
    cmap = open_case_map(db, [r[0].id for r in page_rows])
    return paged([lot_out(l, now, cmap.get(l.id)) for l, _ in page_rows], total, p)


@router.post("/lots", status_code=201)
def create_lot(body: LotIn, db: DB, user: User = Depends(require("lots:write"))):
    plant = get_owned(db, Plant, body.plant_id, user)
    product = get_owned(db, Product, body.product_id, user)
    if body.safe_until <= body.produced_at:
        raise AppError("The safe-until time must be after the production time.", "INVALID_WINDOW", 422)
    if db.execute(select(InventoryLot.id).where(InventoryLot.lot_code == body.lot_code)).first():
        raise AppError("A lot with this code already exists.", "LOT_CODE_TAKEN", 409)
    lot = InventoryLot(org_id=plant.org_id, plant_id=plant.id, product_id=product.id, lot_code=body.lot_code, quantity_kg=body.quantity_kg,
                       produced_at=body.produced_at, safe_until=body.safe_until, storage=body.storage, created_by=user.id,
                       window_minutes=int((body.safe_until - body.produced_at).total_seconds() // 60))
    db.add(lot)
    db.flush()
    cases.snapshot_freshness(db, lot, "Lot registered")
    audit.record(db, lot.org_id, user, "lot.created", "lot", lot.id, f"Lot {lot.lot_code} registered ({lot.quantity_kg:g} kg)", {"lot_code": lot.lot_code})
    events.publish(db, lot.org_id, "lot.updated", {"lot_id": str(lot.id)})
    db.commit()
    db.refresh(lot)
    return lot_out(lot)


@router.get("/lots/{lot_id}", dependencies=[Depends(require("lots:read"))])
def get_lot(lot_id: uuid.UUID, db: DB, user: CurrentUser):
    lot = get_owned(db, InventoryLot, lot_id, user)
    history = db.execute(select(FreshnessAssessment).where(FreshnessAssessment.lot_id == lot.id).order_by(FreshnessAssessment.created_at.desc()).limit(20)).scalars().all()
    return {**lot_out(lot, open_case=open_case_map(db, [lot.id]).get(lot.id)),
            "assessments": [{"at": iso(a.created_at), "remaining_minutes": a.remaining_minutes, "percent": a.percent, "state": a.state, "note": a.note, "method": a.method} for a in history]}


@router.get("/products", dependencies=[Depends(require("lots:read"))])
def products(db: DB, user: CurrentUser):
    rows = db.execute(select(Product).where(*_org_filter(Product, user)).order_by(Product.name)).scalars().all()
    return [{"id": str(p.id), "name": p.name, "sku": p.sku, "category": p.category} for p in rows]


@router.get("/plants", dependencies=[Depends(require("lots:read", "plant:read"))])
def plants(db: DB, user: CurrentUser):
    rows = db.execute(select(Plant).where(*_org_filter(Plant, user)).order_by(Plant.name)).scalars().all()
    return [{"id": str(p.id), "name": p.name, "city": p.city, "status": p.status} for p in rows]


@router.post("/lots/{lot_id}/adjust", dependencies=[Depends(require("lots:adjust"))])
def adjust_lot(lot_id: uuid.UUID, body: LotAdjustIn, db: DB, user: CurrentUser):
    """Controlled stock adjustment: reason required, never below reserved/case quantity, never <= 0, row-locked."""
    get_owned(db, InventoryLot, lot_id, user)  # 404 for other organizations
    lot = db.execute(select(InventoryLot).where(InventoryLot.id == lot_id).with_for_update()).unique().scalar_one()
    if lot.status not in ("available", "in_recovery"):
        raise AppError("Only available or in-recovery lots can be adjusted.", "LOT_NOT_ADJUSTABLE", 409)
    if body.delta_kg == 0:
        raise AppError("The adjustment must be non-zero.", "ZERO_ADJUSTMENT", 422)
    new_qty = round(lot.quantity_kg + body.delta_kg, 3)
    if new_qty <= 0:
        raise AppError("Stock can't go to zero or below. Dispose of the lot through a recovery case instead.", "NEGATIVE_STOCK", 422)
    if new_qty > 100000:
        raise AppError("Quantity exceeds the 100,000 kg limit.", "QUANTITY_TOO_LARGE", 422)
    active = db.execute(select(RecoveryCase).where(RecoveryCase.lot_id == lot.id, RecoveryCase.status.in_(cases.ACTIVE_CASE))).unique().scalars().all()
    floor = max([lot.reserved_kg or 0.0] + [c.quantity_kg for c in active])
    if body.delta_kg < 0 and new_qty < floor:
        raise AppError(f"{floor:g} kg is reserved or committed to an open recovery case; the lot can't drop below that.", "BELOW_COMMITTED", 409)
    old = lot.quantity_kg
    lot.quantity_kg = new_qty
    audit.record(db, lot.org_id, user, "lot.adjusted", "lot", lot.id, f"Lot {lot.lot_code} adjusted {old:g} → {new_qty:g} kg: {body.reason.strip()}",
                 {"lot_code": lot.lot_code, "before_kg": old, "after_kg": new_qty, "delta_kg": body.delta_kg, "reason": body.reason.strip()})
    events.publish(db, lot.org_id, "lot.updated", {"lot_id": str(lot.id)})
    db.commit()
    db.refresh(lot)
    return lot_out(lot)


@router.get("/lots/{lot_id}/history", dependencies=[Depends(require("lots:read"))])
def lot_history(lot_id: uuid.UUID, db: DB, user: CurrentUser):
    lot = get_owned(db, InventoryLot, lot_id, user)
    rows = db.execute(select(AuditEvent).where(AuditEvent.org_id == lot.org_id, AuditEvent.resource_type == "lot", AuditEvent.resource_id == str(lot.id))
                      .order_by(AuditEvent.seq.desc()).limit(100)).scalars().all()
    from app.api.serializers import audit_out
    return [audit_out(e) for e in rows]
