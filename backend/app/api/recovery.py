import hashlib
import secrets
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser, Page, get_owned, paged, require
from app.api.serializers import (
    audit_out,
    case_out,
    evidence_out,
    iso,
    option_out,
    pickup_out,
)
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError, Conflict, NotFound
from app.models import (
    AuditEvent,
    Evidence,
    InventoryLot,
    Pickup,
    RecoveryCase,
    RecoveryDecision,
    User,
)
from app.schemas import ApproveIn, CaseCreateIn, NoteIn, ReplanIn, SimulateIn
from app.services import audit, cases
from app.services import recovery_engine as eng

router = APIRouter(prefix="/recovery-cases", tags=["recovery"])
settings = get_settings()

ALLOWED_UPLOADS = {
    ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"}, ".png": {"image/png"}, ".pdf": {"application/pdf"},
    ".csv": {"text/csv", "application/vnd.ms-excel", "text/plain"}, ".txt": {"text/plain"},
}
MAGIC = {".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG", ".pdf": b"%PDF"}
EVIDENCE_KINDS = {"photo", "temperature_log", "label", "lab_report", "other"}


async def store_upload(file: UploadFile) -> tuple[str, str, str, int, str]:
    """Validate extension, content type, size and magic bytes. The user's filename is never used on disk."""
    original = Path(file.filename or "upload").name[:200]
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise AppError("This file type isn't supported. Use JPG, PNG, PDF, CSV or TXT.", "UNSUPPORTED_FILE_TYPE", 422)
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_UPLOADS[ext]:
        raise AppError("The file's content type doesn't match its extension.", "CONTENT_TYPE_MISMATCH", 422)
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(f"Files must be {settings.max_upload_mb} MB or smaller.", "FILE_TOO_LARGE", 413)
    if not data:
        raise AppError("This file is empty.", "EMPTY_FILE", 422)
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        raise AppError("The file contents don't look like a valid " + ext.strip(".").upper() + ".", "INVALID_FILE_CONTENT", 422)
    stored = secrets.token_hex(16) + ext
    root = Path(settings.upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / stored).write_bytes(data)
    return original, stored, ctype, len(data), hashlib.sha256(data).hexdigest()


def _case(db, case_id, user) -> RecoveryCase:
    return get_owned(db, RecoveryCase, case_id, user)


@router.get("", dependencies=[Depends(require("cases:read"))])
def list_cases(db: DB, user: CurrentUser, p: Page = Depends(), status: str | None = None, rung: str | None = Query(None, pattern="^R[1-4]$"),
               q: str | None = Query(None, max_length=60), sort: str = Query("urgency", pattern="^(urgency|created)$"), active: bool | None = None):
    stmt = select(RecoveryCase).join(InventoryLot, InventoryLot.id == RecoveryCase.lot_id)
    if not user.is_platform_admin:
        stmt = stmt.where(RecoveryCase.org_id == user.org_id)
    if status:
        stmt = stmt.where(RecoveryCase.status == status)
    if active:
        stmt = stmt.where(RecoveryCase.status.in_(cases.ACTIVE_CASE))
    if rung:
        stmt = stmt.where(RecoveryCase.selected_rung == rung)
    if q:
        stmt = stmt.where(or_(RecoveryCase.case_number.ilike(f"%{q}%"), InventoryLot.lot_code.ilike(f"%{q}%")))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(InventoryLot.safe_until if sort == "urgency" else RecoveryCase.created_at.desc())
    rows = db.execute(stmt.offset(p.offset).limit(p.page_size)).unique().scalars().all()
    now = utcnow()
    return paged([case_out(c, now) for c in rows], total, p)


@router.post("", status_code=201)
def create(body: CaseCreateIn, db: DB, user: User = Depends(require("cases:create"))):
    lot = get_owned(db, InventoryLot, body.lot_id, user)
    case = cases.create_case(db, lot, user)
    db.commit()
    return case_out(case)


@router.get("/{case_id}", dependencies=[Depends(require("cases:read"))])
def detail(case_id: uuid.UUID, db: DB, user: CurrentUser):
    c = _case(db, case_id, user)
    now = utcnow()
    pickups = db.execute(select(Pickup).where(Pickup.case_id == c.id).order_by(Pickup.created_at)).unique().scalars().all()
    ev = db.execute(select(Evidence).where(Evidence.case_id == c.id).order_by(Evidence.created_at)).scalars().all()
    decisions = db.execute(select(RecoveryDecision).where(RecoveryDecision.case_id == c.id).order_by(RecoveryDecision.created_at)).scalars().all()
    timeline = db.execute(select(AuditEvent).where(AuditEvent.case_id == c.id).order_by(AuditEvent.seq)).scalars().all()
    return {
        **case_out(c, now),
        "options": [option_out(o) for o in cases.current_options(db, c)],
        "evidence": [evidence_out(e) for e in ev], "evidence_score": cases.evidence_score(db, c.id),
        "required_evidence": sorted(cases.REQUIRED_EVIDENCE_KINDS),
        "pickups": [pickup_out(p) for p in pickups],
        "decisions": [{"decision": d.decision, "rung": d.rung, "note": d.note, "at": iso(d.created_at)} for d in decisions],
        "timeline": [audit_out(e) for e in timeline],
        "excluded_rungs": c.excluded_rungs,
        "disclaimer": "foodAgent provides decision support and workflow assistance. It does not certify food as safe for human consumption; a person must approve.",
    }


@router.post("/{case_id}/approve")
def approve(case_id: uuid.UUID, body: ApproveIn, db: DB, user: User = Depends(require("cases:approve"))):
    c = cases.approve(db, _case(db, case_id, user), user, body.rung, body.recipient_id, body.note)
    db.commit()
    return case_out(c)


@router.post("/{case_id}/reject")
def reject(case_id: uuid.UUID, body: NoteIn, db: DB, user: User = Depends(require("cases:approve"))):
    c = cases.reject(db, _case(db, case_id, user), user, body.note)
    db.commit()
    return case_out(c)


@router.post("/{case_id}/replan")
def replan(case_id: uuid.UUID, body: ReplanIn, db: DB, user: User = Depends(require("cases:approve"))):
    c = cases.replan(db, _case(db, case_id, user), user, body.reason, exclude_rung=body.exclude_rung)
    db.commit()
    return case_out(c)


@router.post("/{case_id}/cancel")
def cancel(case_id: uuid.UUID, body: NoteIn, db: DB, user: User = Depends(require("cases:close"))):
    c = cases.cancel_case(db, _case(db, case_id, user), user, body.note)
    db.commit()
    return case_out(c)


@router.post("/{case_id}/simulate")
def simulate(case_id: uuid.UUID, body: SimulateIn, db: DB, user: User = Depends(require("simulate"))):
    c = _case(db, case_id, user)
    sim = eng.simulate(cases.lot_input(db, c.lot, c.id), cases.recipient_inputs(db), pickup_delay_min=body.pickup_delay_min,
                       acceptance_prob=body.acceptance_prob, handover_buffer_min=body.handover_buffer_min,
                       remaining_minutes=body.remaining_minutes, now=utcnow())
    def o(x):
        return None if x is None else {"rung": x.rung, "label": eng.RUNG_LABELS[x.rung], "p_success": x.p_success, "est_recovery_kg": x.est_recovery_kg}
    return {"simulated": True, "method": "SIMULATED", "p_success": sim["p_success"], "recommended": o(sim["recommended"]), "hedge": o(sim["hedge"]),
            "deadline": iso(sim["deadline"]), "expected_recovery_kg": sim["expected_recovery_kg"],
            "options": [{**(o(x) or {}), "eligible": x.eligible, "reason": x.reason} for x in sim["options"]],
            "note": "Modelled from the inputs you set. Not a guaranteed outcome."}


@router.post("/{case_id}/evidence", status_code=201)
async def upload_evidence(case_id: uuid.UUID, db: DB, file: UploadFile = File(...), kind: str = Form("photo"),
                          user: User = Depends(require("evidence:write"))):
    c = _case(db, case_id, user)
    if kind not in EVIDENCE_KINDS:
        raise AppError("Choose a valid evidence type.", "INVALID_EVIDENCE_KIND", 422)
    if c.status in ("completed", "cancelled", "rejected"):
        raise Conflict("Evidence can't be added to a closed case.", "CASE_CLOSED")
    original, stored, ctype, size, digest = await store_upload(file)
    ev = Evidence(org_id=c.org_id, case_id=c.id, uploaded_by=user.id, kind=kind, original_name=original, stored_name=stored,
                  content_type=ctype, size_bytes=size, sha256=digest)
    db.add(ev)
    db.flush()
    audit.record(db, c.org_id, user, "evidence.uploaded", "evidence", ev.id, f"Evidence uploaded: {kind.replace('_', ' ')} ({original})", {"sha256": digest, "size": size}, c.id)
    if c.status == "pending_approval":
        cases.rescore(db, c)
    db.commit()
    return evidence_out(ev)


@router.get("/{case_id}/evidence/{evidence_id}/file", dependencies=[Depends(require("evidence:read"))])
def download_evidence(case_id: uuid.UUID, evidence_id: uuid.UUID, db: DB, user: CurrentUser):
    c = _case(db, case_id, user)
    ev = db.get(Evidence, evidence_id)
    if not ev or ev.case_id != c.id:
        raise NotFound("We couldn't find that file.", "NOT_FOUND")
    path = Path(settings.upload_dir) / ev.stored_name
    if not path.exists():
        raise NotFound("This file is no longer available.", "FILE_MISSING")
    return FileResponse(path, media_type=ev.content_type, filename=ev.original_name, headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": f'attachment; filename="{ev.stored_name}"'})
