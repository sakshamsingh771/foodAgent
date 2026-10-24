"""Demo simulator: periodically adds a SIMULATED surplus lot to demo organizations so the live
operations screen keeps moving. Disabled unless SIMULATOR_ENABLED=true. Run: python -m app.workers.simulator"""
import logging
import random
import time
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.core.logging import configure_logging, log_event
from app.models import InventoryLot, Organization, Plant, Product
from app.services import audit, cases, events

log = logging.getLogger("foodagent.simulator")
settings = get_settings()


def tick() -> None:
    with SessionLocal() as db:
        org = db.execute(select(Organization).where(Organization.slug == "verdana-foods", Organization.is_demo.is_(True))).scalar_one_or_none()
        if not org:
            return
        plant = random.choice(db.execute(select(Plant).where(Plant.org_id == org.id)).scalars().all())
        prod = random.choice(db.execute(select(Product).where(Product.org_id == org.id)).scalars().all())
        now, window = utcnow(), prod.shelf_life_hours * 60
        remaining = random.randint(90, 600)
        lot = InventoryLot(org_id=org.id, plant_id=plant.id, product_id=prod.id, lot_code=f"SIM-{uuid.uuid4().hex[:6].upper()}", quantity_kg=random.randint(80, 400),
                           window_minutes=window, produced_at=now - timedelta(minutes=window - remaining), safe_until=now + timedelta(minutes=remaining), is_simulated=True)
        db.add(lot)
        db.flush()
        cases.snapshot_freshness(db, lot, "Simulated surplus")
        audit.record(db, org.id, None, "lot.simulated", "lot", lot.id, f"Simulated surplus lot {lot.lot_code} ({lot.quantity_kg:g} kg)", actor_label="Demo simulator")
        events.publish(db, org.id, "lot.updated", {"lot_id": str(lot.id)})
        db.commit()
        log_event(log, "simulated lot", lot=lot.lot_code)


def main() -> None:
    configure_logging()
    if not settings.simulator_enabled:
        log_event(log, "simulator disabled (set SIMULATOR_ENABLED=true); idling")
        while True:
            time.sleep(3600)
    while True:
        try:
            tick()
        except Exception:
            log.exception("simulator tick failed")
        time.sleep(settings.simulator_interval_seconds)


if __name__ == "__main__":
    main()
