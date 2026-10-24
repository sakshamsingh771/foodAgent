import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser, Page, ensure_org, get_owned, paged, require
from app.api.serializers import iso, lot_out
from app.core.database import utcnow
from app.core.errors import AppError
from app.models import User
from app.models import FreshnessAssessment, InventoryLot, Plant, Product, RecoveryCase
from app.schemas import LotIn
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
