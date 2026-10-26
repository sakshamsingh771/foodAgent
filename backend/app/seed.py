"""Demo data. Everything here is SIMULATED and the demo organizations are flagged is_demo=True.

Usage:  python -m app.seed [--reset]
"""
import random
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from app.core import security as sec
from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.models import (Anomaly, Base, ComplianceDocument, DemandForecast, Evidence, InventoryLot, Organization, Pickup,
                        Plant, PlantMetric, Product, Recipient, RecoveryCase, SustainabilityMetric, User)
from app.services import audit, cases, events
from app.services.cases import CO2E_RUNG_FACTOR

DEMO_PASSWORD = "FoodAgent#2026demo"
settings = get_settings()
PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")


def _user(db, email, name, role, org, **kw):
    u = User(email=email, full_name=name, role=role, org_id=org.id if org else None, password_hash=sec.hash_password(DEMO_PASSWORD), email_verified_at=utcnow(), **kw)
    db.add(u)
    return u


def reset_all(db) -> None:
    for t in reversed(Base.metadata.sorted_tables):
        db.execute(delete(t))
    db.commit()


def seed(db) -> dict:
    if db.execute(select(Organization.id).where(Organization.slug == "verdana-foods")).first():
        return {"seeded": False, "reason": "Demo data already present. Run with --reset to rebuild."}
    rng = random.Random(42)
    now = utcnow()
    today = now.date()

    verdana = Organization(name="Verdana Foods Pvt Ltd", slug="verdana-foods", type="MANUFACTURER", is_demo=True)
    sahyadri = Organization(name="Sahyadri Beverages", slug="sahyadri-beverages", type="MANUFACTURER", is_demo=True)
    db.add_all([verdana, sahyadri])
    db.flush()

    pune = Plant(org_id=verdana.id, name="Pune Bakery & Ready-Meals Plant", city="Pune", lat=18.52, lng=73.86)
    nashik = Plant(org_id=verdana.id, name="Nashik Dairy Plant", city="Nashik", lat=19.99, lng=73.79)
    kolhapur = Plant(org_id=sahyadri.id, name="Kolhapur Beverage Plant", city="Kolhapur", lat=16.70, lng=74.24)
    db.add_all([pune, nashik, kolhapur])

    def prod(org, name, sku, cat, human, feed, shelf, meals, co2):
        p = Product(org_id=org.id, name=name, sku=sku, category=cat, human_grade_eligible=human, feed_eligible=feed,
                    shelf_life_hours=shelf, meals_per_kg=meals, co2e_per_kg=co2)
        db.add(p)
        return p

    loaf = prod(verdana, "Multigrain Sandwich Loaf", "BK-101", "bakery", True, True, 72, 3.0, 1.9)
    pav = prod(verdana, "Whole Wheat Pav", "BK-102", "bakery", True, True, 48, 3.2, 1.9)
    pulao = prod(verdana, "Veg Pulao Meal Trays", "RM-201", "cooked_meals", True, True, 36, 2.2, 3.1)
    dal = prod(verdana, "Dal Tadka Meal Trays", "RM-202", "cooked_meals", True, True, 36, 2.4, 2.8)
    paneer = prod(verdana, "Paneer Blocks 1 kg", "DY-301", "dairy", True, False, 72, 2.0, 5.5)
    curd = prod(verdana, "Set Curd Cups 200 g", "DY-302", "dairy", True, False, 168, 4.0, 2.6)
    trim = prod(verdana, "Fruit Pulp Trimmings", "PR-401", "produce", False, True, 96, 0.0, 1.2)
    nectar = prod(sahyadri, "Mango Nectar Cartons 1 L", "BV-101", "beverages", True, False, 2160, 1.0, 1.4)
    db.flush()

    def rec(name, kind, rungs, rate, cap, dist, city, phone, org_type):
        org = Organization(name=name, slug=name.lower().replace(" ", "-"), type=org_type, is_demo=True)
        db.add(org)
        db.flush()
        r = Recipient(org_id=org.id, name=name, kind=kind, accepts_rungs=rungs, acceptance_rate=rate, capacity_kg=cap, distance_km=dist, city=city, phone=phone)
        db.add(r)
        return r, org

    annapurna, annapurna_org = rec("Annapurna Food Bank", "ngo", ["R1"], 0.86, 800, 9, "Pune", "+91 20 5550 0141", "NGO")
    rotighar, _ = rec("Roti Ghar Foundation", "ngo", ["R1"], 0.74, 400, 14, "Pune", "+91 20 5550 0187", "NGO")
    seva, _ = rec("Seva Kitchens Trust", "ngo", ["R1"], 0.68, 300, 22, "Pimpri-Chinchwad", "+91 20 5550 0122", "NGO")
    metro, _ = rec("Metro Institutional Foods", "buyer", ["R2"], 0.71, 1000, 18, "Pune", "+91 20 5550 0166", "BUYER")
    greenfeed, _ = rec("GreenFeed Agro Co-op", "feed", ["R3"], 0.90, 1500, 38, "Baramati", "+91 2112 555 019", "PARTNER")
    bhoomi, _ = rec("Bhoomi BioEnergy", "biogas", ["R4"], 0.97, 3000, 26, "Pune", "+91 20 5550 0133", "PARTNER")
    db.flush()

    platform = _user(db, "platform@foodagent.demo", "Platform Administrator", sec.ADMIN, None, is_platform_admin=True)
    admin = _user(db, "admin@verdanafoods.demo", "Meera Kulkarni", sec.ADMIN, verdana)
    ops = _user(db, "ops@verdanafoods.demo", "Rahul Deshmukh", sec.OPS, verdana)
    recovery = _user(db, "recovery@verdanafoods.demo", "Anita Joshi", sec.RECOVERY, verdana)
    logi = _user(db, "logistics@verdanafoods.demo", "Sanjay Pawar", sec.LOGISTICS, verdana)
    auditor = _user(db, "auditor@verdanafoods.demo", "Farah Sheikh", sec.AUDITOR, verdana)
    ngo_user = _user(db, "recipient@annapurna.demo", "Kavita Naik (Annapurna)", sec.RECIPIENT, annapurna_org, recipient_id=annapurna.id, language="hi")
    _user(db, "admin@sahyadribev.demo", "Vikram Patil", sec.ADMIN, sahyadri)
    db.flush()

    def lot(code, product, plant, kg, remaining, window, storage="chilled", org=verdana):
        l = InventoryLot(org_id=org.id, plant_id=plant.id, product_id=product.id, lot_code=code, quantity_kg=kg, window_minutes=window,
                         produced_at=now - timedelta(minutes=window - remaining), safe_until=now + timedelta(minutes=remaining), storage=storage, created_by=ops.id)
        db.add(l)
        db.flush()
        cases.snapshot_freshness(db, l, "Seeded demo lot")
        return l

    l_loaf = lot("BK-2609-01", loaf, pune, 420, 70, 4320)
    l_pulao = lot("RM-2609-07", pulao, pune, 260, 360, 2160)
    l_dal = lot("RM-2609-08", dal, pune, 180, 150, 2160)
    l_paneer = lot("DY-2609-03", paneer, nashik, 310, 1300, 4000)
    lot("DY-2609-05", curd, nashik, 220, 6000, 10080)
    l_pav = lot("BK-2609-02", pav, pune, 300, 2000, 2880, "ambient")
    lot("PR-2609-02", trim, pune, 540, 400, 5760, "ambient")
    lot("RM-2609-09", pulao, pune, 150, 1300, 2160)
    lot("BK-2609-03", loaf, pune, 380, 600, 2000)
    lot("DY-2609-06", curd, nashik, 160, 3000, 7000)
    lot("BV-2609-01", nectar, kolhapur, 900, 20000, 43200, "ambient", sahyadri)
    lot("BV-2609-02", nectar, kolhapur, 640, 600, 4000, "ambient", sahyadri)

    # --- live cases created through the real workflow (so audit/notifications/events are genuine) ---
    upload_root = Path(settings.upload_dir)
    try:
        upload_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        upload_root = None

    def evidence(case, kind, name, ctype, data):
        if upload_root is None:
            return
        import hashlib, secrets
        stored = secrets.token_hex(16) + Path(name).suffix
        (upload_root / stored).write_bytes(data)
        e = Evidence(org_id=case.org_id, case_id=case.id, uploaded_by=ops.id, kind=kind, original_name=name, stored_name=stored,
                     content_type=ctype, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        db.add(e)
        db.flush()
        audit.record(db, case.org_id, ops, "evidence.uploaded", "evidence", e.id, f"Evidence uploaded: {kind.replace('_', ' ')} ({name})", {"sha256": e.sha256}, case.id)

    csv_log = b"time,temp_c\n08:00,4.1\n09:00,4.3\n10:00,4.2\n11:00,4.6\n"
    c1 = cases.create_case(db, l_paneer, ops)                        # waiting for a manager's decision
    for kind, name, ct, data in (("photo", "paneer-lot-photo.png", "image/png", PNG_1PX), ("temperature_log", "coldroom-log.csv", "text/csv", csv_log)):
        evidence(c1, kind, name, ct, data)
    c2 = cases.create_case(db, l_pulao, ops)                         # approved, waiting for NGO
    evidence(c2, "photo", "pulao-trays.png", "image/png", PNG_1PX)
    evidence(c2, "temperature_log", "hotline-log.csv", "text/csv", csv_log)
    evidence(c2, "label", "label-proof.png", "image/png", PNG_1PX)
    cases.rescore(db, c2)
    opt = next(o for o in cases.current_options(db, c2) if o.is_recommended)
    cases.approve(db, c2, recovery, opt.rung, opt.recipient_id, "Evidence reviewed; labels and temperature logs are complete.")
    c3 = cases.create_case(db, l_pav, ops)                           # accepted + pickup scheduled
    for kind, name, ct, data in (("photo", "pav-trays.png", "image/png", PNG_1PX), ("temperature_log", "ambient-log.csv", "text/csv", csv_log), ("label", "pav-label.png", "image/png", PNG_1PX)):
        evidence(c3, kind, name, ct, data)
    cases.rescore(db, c3)
    opt3 = next(o for o in cases.current_options(db, c3) if o.is_recommended)
    cases.approve(db, c3, recovery, opt3.rung, opt3.recipient_id, "Approved for donation.")
    if opt3.recipient_id == annapurna.id:
        cases.recipient_respond(db, c3, ngo_user, True, None)
    else:
        c3.status = "accepted"
    cases.schedule_pickup(db, c3, ops, now + timedelta(minutes=40), logi.id)

    # --- demo history (clearly tagged) ---
    for i in range(1, 31):
        d = today - timedelta(days=i)
        for _ in range(rng.randint(0, 2)):
            rung = rng.choices(["R1", "R2", "R3", "R4"], [0.5, 0.15, 0.2, 0.15])[0]
            kg = round(rng.uniform(60, 420), 1)
            p = rng.choice([loaf, pav, pulao, dal, paneer, curd])
            db.add(SustainabilityMetric(org_id=verdana.id, recorded_on=d, rung=rung, kg=kg, meals=round(kg * p.meals_per_kg, 1) if rung == "R1" else 0,
                                        co2e_kg=round(kg * p.co2e_per_kg * CO2E_RUNG_FACTOR[rung], 1), source="demo_history"))
    done_n, lost_n = 0, 0
    for i in range(11):
        h = InventoryLot(org_id=verdana.id, plant_id=pune.id, product_id=rng.choice([loaf, pav, pulao]).id, lot_code=f"HX-{i + 1:03d}", quantity_kg=200,
                         window_minutes=2000, produced_at=now - timedelta(days=i + 2), safe_until=now - timedelta(days=i + 1), status="recovered" if i < 9 else "wasted")
        db.add(h)
        db.flush()
        db.add(RecoveryCase(org_id=verdana.id, lot_id=h.id, case_number=f"RC-HIST-{i + 1:03d}", status="completed" if i < 9 else "cancelled", quantity_kg=200,
                            recovered_kg=190 if i < 9 else None, selected_rung="R1" if i < 9 else None, closed_at=now - timedelta(days=i + 1)))

    # --- plant data ---
    for plant, lines in ((pune, ("Line 1", "Line 2", "Line 3")), (nashik, ("Curd line", "Paneer line"))):
        for i in range(14):
            for ln in lines:
                down = rng.choice([0, 0, 0, 12, 25, 40])
                db.add(PlantMetric(plant_id=plant.id, day=today - timedelta(days=13 - i), line=ln, production_kg=round(rng.uniform(1800, 2600), 0),
                                   oee=round(rng.uniform(0.68, 0.88), 3), energy_kwh=round(rng.uniform(900, 1500), 0), downtime_min=down))
    db.add(Anomaly(plant_id=pune.id, line="Line 2", kind="temperature_drift", severity="medium", is_simulated=True,
                   description="Proofing chamber ran 2 °C above set point for 35 min (demo record).", affected_lot_ids=[str(l_loaf.id)], detected_at=now - timedelta(hours=3)))

    # --- planning ---
    for p in (loaf, pav, pulao, paneer):
        base = {"BK-101": 2400, "BK-102": 1900, "RM-201": 1500, "DY-301": 900}[p.sku]
        for d in range(-14, 8):
            day = today + timedelta(days=d)
            p50 = round(base * (1 + 0.08 * ((day.weekday() in (4, 5)) - (day.weekday() == 6)) + rng.uniform(-0.04, 0.04)))
            actual = round(p50 * rng.uniform(0.9, 1.1)) if d < 0 else None
            db.add(DemandForecast(org_id=verdana.id, product_id=p.id, day=day, p50=p50, p80=round(p50 * 1.12), actual=actual,
                                  surplus_kg=round(max(0, rng.uniform(20, 90)) if d >= 0 else 0, 1),
                                  drivers=["Weekend demand uplift (+8%)", "Recent surplus shifted this week's production target down", "Demo series: statistical, not a trained model"] if d >= 0 else []))

    # --- compliance ---
    for title, typ, issuer, ref, days in (
        ("Food business operator licence (demo record)", "license", "Demo Regulator", "DEMO-LIC-0001", 240),
        ("Cold-chain SOP v3", "sop", "Verdana Foods QA", "SOP-CC-003", None),
        ("Donation label template, allergen declaration", "label", "Verdana Foods QA", "LBL-DON-002", 18),
        ("Third-party hygiene audit certificate (demo record)", "certificate", "Demo Auditor", "DEMO-CERT-77", -5),
    ):
        db.add(ComplianceDocument(org_id=verdana.id, title=title, doc_type=typ, issuer=issuer, reference=ref, valid_until=today + timedelta(days=days) if days is not None else None, uploaded_by=admin.id))
    events.notify_roles(db, verdana.id, [sec.ADMIN, sec.RECOVERY, sec.AUDITOR], "compliance_expiry", "Document expires soon: Donation label template", "Valid for 18 more days.", "warning")
    events.notify_roles(db, verdana.id, [sec.OPS], "system_alert", "Line 2 proofing chamber drift detected", "Check lot BK-2609-01 freshness window.", "warning")
    audit.record(db, verdana.id, admin, "demo.seeded", "system", "seed", "Demo data loaded (simulated)")
    db.commit()
    return {"seeded": True}


if __name__ == "__main__":
    with SessionLocal() as s:
        if "--reset" in sys.argv:
            reset_all(s)
        print(seed(s))
