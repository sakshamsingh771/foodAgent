import asyncio
import json
import uuid
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, or_, select, update

from app.api.deps import DB, CurrentUser, Page, current_user, get_owned, paged, require
from app.api.recovery import store_upload
from app.api.serializers import iso, notification_out, user_out
from app.core import security as sec
from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.core.errors import AppError, Conflict, NotFound
from app.models import (ComplianceDocument, EventOutbox, InventoryLot, Notification, Organization, Product, Recipient,
                        RecoveryCase, ScenarioRun, User)
from app.schemas import ScenarioApplyIn, ScenarioIn, UserCreateIn
from app.services import audit, scenarios

settings = get_settings()
router = APIRouter()


def _org(model, user):
    return [] if user.is_platform_admin else [model.org_id == user.org_id]


# ---- Compliance documents -----------------------------------------------------
def _doc_out(d: ComplianceDocument) -> dict:
    today = utcnow().date()
    if d.valid_until is None:
        status = "no_expiry"
    elif d.valid_until < today:
        status = "expired"
    elif d.valid_until <= today + timedelta(days=30):
        status = "expiring_soon"
    else:
        status = "valid"
    return {"id": str(d.id), "title": d.title, "doc_type": d.doc_type, "issuer": d.issuer, "reference": d.reference,
            "valid_until": d.valid_until.isoformat() if d.valid_until else None, "status": status, "has_file": bool(d.stored_name),
            "original_name": d.original_name, "size_bytes": d.size_bytes}


@router.get("/compliance/documents", tags=["compliance"], dependencies=[Depends(require("compliance:read"))])
def documents(db: DB, user: CurrentUser):
    rows = db.execute(select(ComplianceDocument).where(*_org(ComplianceDocument, user)).order_by(ComplianceDocument.valid_until.asc().nulls_last())).scalars().all()
    return [_doc_out(d) for d in rows]


@router.post("/compliance/documents", status_code=201, tags=["compliance"])
async def add_document(db: DB, title: str = Form(..., min_length=2, max_length=200), doc_type: str = Form(...), issuer: str = Form("", max_length=160),
                       reference: str = Form("", max_length=80), valid_until: date | None = Form(None), file: UploadFile | None = File(None),
                       user: User = Depends(require("compliance:write"))):
    if doc_type not in {"license", "label", "certificate", "sop", "other"}:
        raise AppError("Choose a valid document type.", "INVALID_DOC_TYPE", 422)
    d = ComplianceDocument(org_id=user.org_id, title=title.strip(), doc_type=doc_type, issuer=issuer, reference=reference, valid_until=valid_until, uploaded_by=user.id)
    if file is not None and file.filename:
        d.original_name, d.stored_name, d.content_type, d.size_bytes, _ = await store_upload(file)
    db.add(d)
    db.flush()
    audit.record(db, user.org_id, user, "compliance.document_added", "document", d.id, f"Document added: {d.title}", {"type": doc_type})
    db.commit()
    return _doc_out(d)


@router.get("/compliance/documents/{doc_id}/file", tags=["compliance"], dependencies=[Depends(require("compliance:read"))])
def doc_file(doc_id: uuid.UUID, db: DB, user: CurrentUser):
    d = get_owned(db, ComplianceDocument, doc_id, user)
    if not d.stored_name or not (Path(settings.upload_dir) / d.stored_name).exists():
        raise NotFound("No file is attached to this document.", "FILE_MISSING")
    return FileResponse(Path(settings.upload_dir) / d.stored_name, media_type=d.content_type, filename=d.original_name,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": f'attachment; filename="{d.stored_name}"'})


# ---- Scenarios ------------------------------------------------------------------
@router.get("/scenarios/catalog", tags=["scenarios"], dependencies=[Depends(require("scenarios:read"))])
def catalog(db: DB, user: CurrentUser):
    runs = db.execute(select(ScenarioRun).where(ScenarioRun.org_id == user.org_id).order_by(ScenarioRun.created_at.desc()).limit(10)).scalars().all()
    return {"scenarios": scenarios.CATALOG, "runs": [{"id": str(r.id), "kind": r.kind, "status": r.status, "at": iso(r.created_at), "effects": r.impact.get("effects", [])} for r in runs],
            "disclaimer": "Scenarios change simulated state only. Every run is audited and can be reset."}


@router.get("/scenarios/targets", tags=["scenarios"], dependencies=[Depends(require("scenarios:read"))])
def targets(db: DB, user: CurrentUser):
    from app.models import Plant
    cs = db.execute(select(RecoveryCase).where(RecoveryCase.org_id == user.org_id, RecoveryCase.status.in_(("awaiting_recipient", "accepted", "pickup_scheduled", "in_transit", "pending_approval"))).limit(50)).unique().scalars().all()
    lots = db.execute(select(InventoryLot).where(InventoryLot.org_id == user.org_id, InventoryLot.status.in_(("available", "in_recovery"))).order_by(InventoryLot.safe_until).limit(50)).unique().scalars().all()
    plants = db.execute(select(Plant).where(Plant.org_id == user.org_id)).scalars().all()
    return {"case": [{"id": str(c.id), "label": f"{c.case_number} · {c.lot.product.name} · {c.status.replace('_', ' ')}"} for c in cs],
            "lot": [{"id": str(l.id), "label": f"{l.lot_code} · {l.product.name} · {l.quantity_kg:g} kg"} for l in lots],
            "plant": [{"id": str(p.id), "label": f"{p.name}, {p.city}"} for p in plants]}


@router.post("/scenarios/preview", tags=["scenarios"], dependencies=[Depends(require("scenarios:read"))])
def scenario_preview(body: ScenarioIn, db: DB, user: CurrentUser):
    return scenarios.preview(db, body.kind, body.target_id, user.org_id)


@router.post("/scenarios/apply", tags=["scenarios"], status_code=201)
def scenario_apply(body: ScenarioApplyIn, db: DB, user: User = Depends(require("scenarios:run"))):
    if not body.confirm:
        raise AppError("Confirm the scenario to apply it.", "CONFIRMATION_REQUIRED", 422)
    run = scenarios.apply(db, body.kind, body.target_id, user)
    db.commit()
    return {"id": str(run.id), "kind": run.kind, "status": run.status, "effects": run.impact.get("effects", [])}


@router.post("/scenarios/reset", tags=["scenarios"])
def scenario_reset(db: DB, user: User = Depends(require("scenarios:run"))):
    n = scenarios.reset(db, user)
    db.commit()
    return {"reverted": n}


# ---- Notifications --------------------------------------------------------------
@router.get("/notifications", tags=["notifications"])
def list_notifications(db: DB, user: CurrentUser, p: Page = Depends(), unread: bool = False):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    unread_count = db.execute(select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))).scalar_one()
    rows = db.execute(stmt.order_by(Notification.created_at.desc()).offset(p.offset).limit(p.page_size)).scalars().all()
    return {**paged([notification_out(n) for n in rows], total, p), "unread": unread_count}


@router.post("/notifications/read-all", tags=["notifications"])
def read_all(db: DB, user: CurrentUser):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"ok": True}


@router.post("/notifications/{nid}/read", tags=["notifications"])
def read_one(nid: uuid.UUID, db: DB, user: CurrentUser):
    n = db.get(Notification, nid)
    if not n or n.user_id != user.id:
        raise NotFound("We couldn't find that notification.", "NOT_FOUND")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return notification_out(n)


# ---- Server-Sent Events -----------------------------------------------------------
@router.get("/events/stream", tags=["events"])
async def stream(request: Request, user: CurrentUser, last_id: int | None = Query(None)):
    """SSE feed backed by the event_outbox table so API and worker processes share one stream.
    Clients authenticate with the Authorization header (fetch streaming), never a URL token."""
    org_id, recipient_id, uid = user.org_id, user.recipient_id, str(user.id)
    with SessionLocal() as s:
        start = last_id if last_id is not None else (s.execute(select(func.coalesce(func.max(EventOutbox.id), 0))).scalar_one())

    async def gen():
        cursor = start
        yield "retry: 3000\n\n"
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as s:
                rows = s.execute(select(EventOutbox).where(EventOutbox.id > cursor).order_by(EventOutbox.id).limit(100)).scalars().all()
            for r in rows:
                cursor = r.id
                visible = (r.org_id == org_id and r.recipient_id is None) or (recipient_id and r.recipient_id == recipient_id) or user.is_platform_admin
                if r.type == "notification.created" and r.payload.get("user_id") != uid:
                    visible = False
                if visible and not (user.role == sec.RECIPIENT and r.recipient_id != recipient_id):
                    yield f"id: {r.id}\nevent: {r.type}\ndata: {json.dumps(r.payload)}\n\n"
                    idle = 0
            idle += 1
            if idle >= 15:
                yield ": keep-alive\n\n"
                idle = 0
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- Search -------------------------------------------------------------------------
@router.get("/search", tags=["search"])
def search(db: DB, user: CurrentUser, q: str = Query(min_length=2, max_length=60)):
    if user.role == sec.RECIPIENT:
        return {"results": []}
    like, out = f"%{q.strip()}%", []
    org = lambda m: _org(m, user)
    for l in db.execute(select(InventoryLot).join(Product, Product.id == InventoryLot.product_id).where(*org(InventoryLot), or_(InventoryLot.lot_code.ilike(like), Product.name.ilike(like))).limit(5)).unique().scalars():
        out.append({"type": "lot", "id": str(l.id), "title": l.lot_code, "subtitle": f"{l.product.name} · {l.quantity_kg:g} kg", "href": "/inventory"})
    for c in db.execute(select(RecoveryCase).where(*org(RecoveryCase), RecoveryCase.case_number.ilike(like)).limit(5)).unique().scalars():
        out.append({"type": "case", "id": str(c.id), "title": c.case_number, "subtitle": f"{c.lot.product.name} · {c.status.replace('_', ' ')}", "href": f"/recovery/{c.id}"})
    for r in db.execute(select(Recipient).where(Recipient.name.ilike(like)).limit(5)).scalars():
        out.append({"type": "recipient", "id": str(r.id), "title": r.name, "subtitle": f"{r.kind} · {r.city}", "href": "/recipients"})
    for p in db.execute(select(Product).where(*org(Product), Product.name.ilike(like)).limit(5)).scalars():
        out.append({"type": "product", "id": str(p.id), "title": p.name, "subtitle": p.category, "href": "/inventory"})
    for d in db.execute(select(ComplianceDocument).where(*org(ComplianceDocument), ComplianceDocument.title.ilike(like)).limit(5)).scalars():
        out.append({"type": "document", "id": str(d.id), "title": d.title, "subtitle": d.doc_type, "href": "/compliance"})
    return {"results": out}


# ---- Users / org -----------------------------------------------------------------------
@router.get("/users", tags=["users"], dependencies=[Depends(require("users:manage"))])
def users(db: DB, user: CurrentUser):
    rows = db.execute(select(User).where(*_org(User, user)).order_by(User.full_name)).scalars().all()
    return [user_out(u) for u in rows]


@router.post("/users", tags=["users"], status_code=201)
def create_user(body: UserCreateIn, db: DB, user: User = Depends(require("users:manage"))):
    problem = sec.validate_password_strength(body.password)
    if problem:
        raise AppError(problem, "WEAK_PASSWORD", 422)
    if db.execute(select(User.id).where(User.email == body.email)).first():
        raise Conflict("An account with this email already exists.", "EMAIL_TAKEN")
    u = User(email=body.email, full_name=body.full_name.strip(), password_hash=sec.hash_password(body.password), role=body.role, org_id=user.org_id, created_by=user.id)
    db.add(u)
    db.flush()
    audit.record(db, user.org_id, user, "user.created", "user", u.id, f"{user.full_name} added {u.full_name} as {u.role}")
    db.commit()
    return user_out(u)


@router.get("/organizations/current", tags=["users"])
def current_org(db: DB, user: CurrentUser):
    org = db.get(Organization, user.org_id) if user.org_id else None
    return {"id": str(org.id), "name": org.name, "type": org.type, "is_demo": org.is_demo} if org else None
