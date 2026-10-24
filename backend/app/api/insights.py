import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, require
from app.api.serializers import audit_out, iso
from app.core.database import utcnow
from app.models import (Anomaly, AuditEvent, DemandForecast, InventoryLot, Pickup, Plant, PlantMetric, Product,
                        RecoveryCase, SustainabilityMetric)
from app.services import cases, freshness
from app.services.recovery_engine import RUNG_LABELS, RUNGS

router = APIRouter(tags=["insights"])


def _org(model, user):
    return [] if user.is_platform_admin else [model.org_id == user.org_id]


@router.get("/dashboard/summary", dependencies=[Depends(require("dashboard:read"))])
def dashboard(db: DB, user: CurrentUser):
    now = utcnow()
    lots = db.execute(select(InventoryLot).where(*_org(InventoryLot, user), InventoryLot.status.in_(("available", "in_recovery")))).unique().scalars().all()
    risk = [(l, freshness.assess(l.safe_until, l.window_minutes, now)) for l in lots]
    risk = [r for r in risk if r[1].state != freshness.SAFE]
    today, since = now.date(), now.date() - timedelta(days=29)
    m = _org(SustainabilityMetric, user)
    kg_today = db.execute(select(func.coalesce(func.sum(SustainabilityMetric.kg), 0)).where(*m, SustainabilityMetric.recorded_on == today)).scalar_one()
    meals_30 = db.execute(select(func.coalesce(func.sum(SustainabilityMetric.meals), 0)).where(*m, SustainabilityMetric.recorded_on >= since)).scalar_one()
    co2_30 = db.execute(select(func.coalesce(func.sum(SustainabilityMetric.co2e_kg), 0)).where(*m, SustainabilityMetric.recorded_on >= since)).scalar_one()
    c = _org(RecoveryCase, user)
    count = lambda *w: db.execute(select(func.count()).select_from(RecoveryCase).where(*c, *w)).scalar_one()
    done, failed = count(RecoveryCase.status == "completed"), count(RecoveryCase.status.in_(("cancelled", "rejected")))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pickups_today = db.execute(select(func.count()).select_from(Pickup).where(*_org(Pickup, user), Pickup.scheduled_for >= start, Pickup.scheduled_for < start + timedelta(days=1), Pickup.status != "cancelled")).scalar_one()
    trend_rows = db.execute(select(SustainabilityMetric.recorded_on, func.sum(SustainabilityMetric.kg)).where(*m, SustainabilityMetric.recorded_on >= today - timedelta(days=13)).group_by(SustainabilityMetric.recorded_on)).all()
    tm = {r[0]: float(r[1]) for r in trend_rows}
    recent = db.execute(select(AuditEvent).where(*_org(AuditEvent, user)).order_by(AuditEvent.created_at.desc()).limit(8)).scalars().all()
    return {
        "kpis": {
            "kg_at_risk": round(sum(l.quantity_kg for l, _ in risk), 1), "kg_recovered_today": round(float(kg_today), 1),
            "meals_recovered_30d": round(float(meals_30)), "co2e_avoided_kg_30d": round(float(co2_30)),
            "active_cases": count(RecoveryCase.status.in_(cases.ACTIVE_CASE)), "pending_approvals": count(RecoveryCase.status == "pending_approval"),
            "pickups_today": pickups_today, "recovery_success_rate": round(done / (done + failed) * 100) if (done + failed) else None,
            "lots_at_risk": len(risk), "loss_imminent": sum(1 for _, f in risk if f.state == freshness.LOSS_IMMINENT),
        },
        "trend": [{"day": (today - timedelta(days=13 - i)).isoformat(), "kg": round(tm.get(today - timedelta(days=13 - i), 0), 1)} for i in range(14)],
        "recent_activity": [audit_out(e) for e in recent],
        "generated_at": iso(now),
    }


@router.get("/sustainability/summary", dependencies=[Depends(require("sustainability:read"))])
def sustainability(db: DB, user: CurrentUser, days: int = Query(30, ge=7, le=365)):
    since = utcnow().date() - timedelta(days=days - 1)
    rows = db.execute(select(SustainabilityMetric).where(*_org(SustainabilityMetric, user), SustainabilityMetric.recorded_on >= since)).scalars().all()
    by_rung = {r: {"rung": r, "label": RUNG_LABELS[r], "kg": 0.0, "meals": 0.0, "co2e_kg": 0.0} for r in RUNGS}
    weekly: dict[str, dict] = {}
    for r in rows:
        b = by_rung[r.rung]
        b["kg"] += r.kg; b["meals"] += r.meals; b["co2e_kg"] += r.co2e_kg
        wk = (r.recorded_on - timedelta(days=r.recorded_on.weekday())).isoformat()
        w = weekly.setdefault(wk, {"week": wk, "kg": 0.0, "co2e_kg": 0.0, "meals": 0.0})
        w["kg"] += r.kg; w["co2e_kg"] += r.co2e_kg; w["meals"] += r.meals
    rnd = lambda d: {k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items()}
    return {
        "days": days, "totals": {"kg": round(sum(r.kg for r in rows), 1), "meals": round(sum(r.meals for r in rows)), "co2e_kg": round(sum(r.co2e_kg for r in rows), 1)},
        "by_rung": [rnd(b) for b in by_rung.values()], "weekly": [rnd(w) for w in sorted(weekly.values(), key=lambda x: x["week"])],
        "includes_demo_history": any(r.source == "demo_history" for r in rows),
        "method_note": "Meals and CO₂e use illustrative conversion factors per product and rung (see ASSUMPTIONS.md). They are estimates, not audited figures.",
    }


@router.get("/sustainability/export.csv", dependencies=[Depends(require("sustainability:read"))])
def export_sustainability(db: DB, user: CurrentUser):
    rows = db.execute(select(SustainabilityMetric).where(*_org(SustainabilityMetric, user)).order_by(SustainabilityMetric.recorded_on)).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "rung", "kg", "meals_est", "co2e_kg_est", "source"])
    for r in rows:
        w.writerow([r.recorded_on, r.rung, r.kg, r.meals, r.co2e_kg, r.source])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=foodagent-sustainability.csv"})


@router.get("/plant/overview", dependencies=[Depends(require("plant:read"))])
def plant_overview(db: DB, user: CurrentUser, plant_id: str | None = None):
    plants = db.execute(select(Plant).where(*_org(Plant, user)).order_by(Plant.name)).scalars().all()
    if not plants:
        return {"plant": None, "metrics": [], "anomalies": [], "lines": []}
    plant = next((p for p in plants if str(p.id) == plant_id), plants[0])
    since = utcnow().date() - timedelta(days=13)
    metrics = db.execute(select(PlantMetric).where(PlantMetric.plant_id == plant.id, PlantMetric.day >= since).order_by(PlantMetric.day)).scalars().all()
    anomalies = db.execute(select(Anomaly).where(Anomaly.plant_id == plant.id).order_by(Anomaly.detected_at.desc()).limit(10)).scalars().all()
    daily: dict = {}
    for m in metrics:
        d = daily.setdefault(m.day, {"day": m.day.isoformat(), "production_kg": 0.0, "energy_kwh": 0.0, "downtime_min": 0, "_oee": []})
        d["production_kg"] += m.production_kg; d["energy_kwh"] += m.energy_kwh; d["downtime_min"] += m.downtime_min; d["_oee"].append(m.oee)
    series = [{**{k: v for k, v in d.items() if k != "_oee"}, "oee": round(sum(d["_oee"]) / len(d["_oee"]) * 100, 1)} for d in daily.values()]
    today_lines = [{"line": m.line, "oee": round(m.oee * 100, 1), "downtime_min": m.downtime_min, "production_kg": m.production_kg} for m in metrics if m.day == utcnow().date()]
    lots = db.execute(select(InventoryLot).where(InventoryLot.plant_id == plant.id, InventoryLot.status.in_(("available", "in_recovery")))).unique().scalars().all()
    now = utcnow()
    at_risk = [l for l in lots if freshness.assess(l.safe_until, l.window_minutes, now).state != freshness.SAFE]
    return {
        "plant": {"id": str(plant.id), "name": plant.name, "city": plant.city}, "series": series, "lines": today_lines,
        "anomalies": [{"id": str(a.id), "line": a.line, "kind": a.kind, "severity": a.severity, "description": a.description, "detected_at": iso(a.detected_at), "resolved": a.resolved_at is not None, "simulated": a.is_simulated, "affected_lots": len(a.affected_lot_ids)} for a in anomalies],
        "lots_at_risk": len(at_risk), "kg_at_risk": round(sum(l.quantity_kg for l in at_risk), 1),
        "note": "Demo plant data is simulated.",
    }


@router.get("/planning/forecast", dependencies=[Depends(require("planning:read"))])
def planning(db: DB, user: CurrentUser, product_id: str | None = None):
    with_forecast = select(DemandForecast.product_id).distinct()
    prods = db.execute(select(Product).where(*_org(Product, user), Product.id.in_(with_forecast)).order_by(Product.name)).scalars().all()
    if not prods:
        return {"product": None, "products": [], "series": [], "backtest": {"days": 0, "mape_pct": None, "actual_within_p80_pct": None}, "why_changed": [], "method": "STATISTICAL", "note": "No forecast data yet.", "recovery_adjusted_production_kg": 0}
    prod = next((p for p in prods if str(p.id) == product_id), prods[0])
    rows = db.execute(select(DemandForecast).where(DemandForecast.product_id == prod.id).order_by(DemandForecast.day)).scalars().all()
    today = utcnow().date()
    hist = [r for r in rows if r.day < today and r.actual is not None]
    mape = round(sum(abs(r.actual - r.p50) / r.actual for r in hist if r.actual) / len(hist) * 100, 1) if hist else None
    within = round(sum(1 for r in hist if r.actual <= r.p80) / len(hist) * 100) if hist else None
    future = [r for r in rows if r.day >= today]
    drivers = future[0].drivers if future else []
    return {
        "product": {"id": str(prod.id), "name": prod.name}, "products": [{"id": str(p.id), "name": p.name} for p in prods],
        "series": [{"day": r.day.isoformat(), "p50": r.p50, "p80": r.p80, "actual": r.actual, "surplus_kg": r.surplus_kg, "forecast": r.day >= today} for r in rows],
        "backtest": {"days": len(hist), "mape_pct": mape, "actual_within_p80_pct": within},
        "why_changed": drivers, "method": "STATISTICAL",
        "note": "Forecasts in this demo are seeded statistical series. Backtest figures are computed from the stored history above and are not a claim about a trained ML model.",
        "recovery_adjusted_production_kg": round(sum(r.surplus_kg for r in future[:7]), 1),
    }


@router.get("/audit", dependencies=[Depends(require("audit:read"))])
def audit_log(db: DB, user: CurrentUser, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), action: str | None = None):
    stmt = select(AuditEvent).where(*_org(AuditEvent, user))
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditEvent.seq.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [audit_out(e) for e in rows], "total": total, "page": page, "page_size": page_size, "pages": max(1, -(-total // page_size))}


@router.get("/audit/verify", dependencies=[Depends(require("audit:read"))])
def audit_verify(db: DB, user: CurrentUser):
    from app.services import audit as a
    return a.verify_chain(db, user.org_id) | {"method": "SHA-256 hash chain (tamper-evident)"}


@router.get("/audit/export.csv", dependencies=[Depends(require("audit:read"))])
def audit_export(db: DB, user: CurrentUser):
    rows = db.execute(select(AuditEvent).where(*_org(AuditEvent, user)).order_by(AuditEvent.seq)).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["seq", "timestamp", "actor", "action", "resource_type", "resource_id", "summary", "hash"])
    for e in rows:
        w.writerow([e.seq, e.created_at.isoformat(), e.actor_label, e.action, e.resource_type, e.resource_id, e.summary, e.hash])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=foodagent-audit.csv"})
