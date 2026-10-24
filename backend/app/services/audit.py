"""Tamper-evident audit log: each organization has a SHA-256 hash chain.

Editing or deleting any past row breaks every later hash, which `verify_chain` detects.
This is a hash chain stored in PostgreSQL. It is not a blockchain.
"""
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import AuditEvent, User

GENESIS = "0" * 64


def _digest(prev_hash, org_id, seq, actor_id, action, rtype, rid, case_id, summary, meta, created_at) -> str:
    body = json.dumps(
        [prev_hash, str(org_id), seq, str(actor_id) if actor_id else None, action, rtype, rid,
         str(case_id) if case_id else None, summary, meta, created_at.isoformat(timespec="microseconds")],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def record(
    db: Session, org_id: uuid.UUID, actor: User | None, action: str, resource_type: str,
    resource_id, summary: str = "", meta: dict | None = None, case_id: uuid.UUID | None = None,
    actor_label: str | None = None,
) -> AuditEvent:
    last = db.execute(
        select(AuditEvent).where(AuditEvent.org_id == org_id).order_by(AuditEvent.seq.desc()).limit(1).with_for_update()
    ).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    meta = json.loads(json.dumps(meta or {}, default=str))
    now = utcnow()
    label = actor_label or (f"{actor.full_name} ({actor.role})" if actor else "System")
    h = _digest(prev, org_id, seq, actor.id if actor else None, action, resource_type, str(resource_id), case_id, summary, meta, now)
    ev = AuditEvent(
        org_id=org_id, seq=seq, actor_id=actor.id if actor else None, actor_label=label, action=action,
        resource_type=resource_type, resource_id=str(resource_id), case_id=case_id, summary=summary,
        meta=meta, prev_hash=prev, hash=h, created_at=now,
    )
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, org_id: uuid.UUID) -> dict:
    rows = db.execute(select(AuditEvent).where(AuditEvent.org_id == org_id).order_by(AuditEvent.seq)).scalars().all()
    prev = GENESIS
    for i, e in enumerate(rows, start=1):
        expect = _digest(prev, e.org_id, e.seq, e.actor_id, e.action, e.resource_type, e.resource_id, e.case_id, e.summary, e.meta, e.created_at)
        if e.seq != i or e.prev_hash != prev or e.hash != expect:
            return {"valid": False, "checked": i, "first_invalid_seq": e.seq, "head": None}
        prev = e.hash
    return {"valid": True, "checked": len(rows), "first_invalid_seq": None, "head": prev if rows else None}
