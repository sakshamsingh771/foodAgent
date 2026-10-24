"""Background worker. Runs outside the API process so requests never block on it.

Jobs: freshness recalculation (+ critical notifications), compliance-expiry notifications.
Run:  python -m app.workers.worker
"""
import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app.core import security as sec
from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.core.logging import configure_logging, log_event
from app.models import ComplianceDocument, InventoryLot, Notification, Organization
from app.services import cases, events, freshness

log = logging.getLogger("foodagent.worker")
settings = get_settings()


def recalc_freshness(db) -> int:
    changed = 0
    now = utcnow()
    for lot in db.execute(select(InventoryLot).where(InventoryLot.status.in_(("available", "in_recovery")))).unique().scalars():
        f = freshness.assess(lot.safe_until, lot.window_minutes, now)
        if f.state != lot.last_state:
            prev = lot.last_state
            cases.snapshot_freshness(db, lot, f"State changed {prev or 'unknown'} → {f.state}")
            events.publish(db, lot.org_id, "freshness.updated", {"lot_id": str(lot.id), "state": f.state})
            if f.state == freshness.LOSS_IMMINENT:
                events.notify_roles(db, lot.org_id, [sec.OPS, sec.RECOVERY], "critical_freshness", f"Loss imminent: {lot.lot_code}",
                                    f"{lot.product.name}, {lot.quantity_kg:g} kg, {f.remaining_minutes} min left", "critical", "lot", lot.id)
            changed += 1
    db.commit()
    return changed


def compliance_expiry(db) -> int:
    n, today = 0, utcnow().date()
    for d in db.execute(select(ComplianceDocument).where(ComplianceDocument.valid_until.is_not(None), ComplianceDocument.valid_until <= today + timedelta(days=30))).scalars():
        title = f"Document {'expired' if d.valid_until < today else 'expires soon'}: {d.title}"
        exists = db.execute(select(Notification.id).where(Notification.resource_id == str(d.id), Notification.created_at > utcnow() - timedelta(days=1)).limit(1)).first()
        if not exists:
            events.notify_roles(db, d.org_id, [sec.ADMIN, sec.AUDITOR], "compliance_expiry", title, f"Valid until {d.valid_until}", "warning", "document", d.id)
            n += 1
    db.commit()
    return n


def run_once() -> dict:
    with SessionLocal() as db:
        return {"freshness_changes": recalc_freshness(db), "expiry_notices": compliance_expiry(db)}


def main() -> None:
    configure_logging()
    log_event(log, "worker started", interval=settings.worker_interval_seconds)
    while True:
        try:
            log_event(log, "tick", **run_once())
        except Exception:
            log.exception("worker tick failed")
        time.sleep(settings.worker_interval_seconds)


if __name__ == "__main__":
    main()
