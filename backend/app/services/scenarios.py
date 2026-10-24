"""Scenario control: each scenario previews impact, requires confirmation, mutates simulated state,
emits events + audit, and can be reverted from a recorded snapshot."""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy import DateTime as SADateTime
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Session

from app.core.database import UTCDateTime, utcnow
from app.core.errors import AppError, Conflict, NotFound
from app.models import (Anomaly, InventoryLot, Pickup, PlantMetric, Plant, Recipient, RecoveryCase, RecoveryOption, ScenarioRun, User)
from app.services import audit, cases, events, freshness
from app.services import recovery_engine as eng
from app.core import security as sec

CATALOG = [
    {"kind": "rider_cancels", "title": "Rider cancels", "target": "case", "description": "The assigned pickup is cancelled and the case is replanned with extra delay."},
    {"kind": "ngo_declines", "title": "NGO declines", "target": "case", "description": "The assigned recipient declines the offer; the engine replans without them."},
    {"kind": "freezer_failure", "title": "Freezer failure", "target": "lot", "description": "A cold-chain failure shortens the lot's remaining recovery window by 60%."},
    {"kind": "line_breakdown", "title": "Line breakdown", "target": "plant", "description": "A production line stops: downtime is logged, nearby lots lose window and surplus appears."},
    {"kind": "late_pickup", "title": "Late pickup", "target": "case", "description": "The active pickup slips by 60 minutes."},
]
KINDS = {c["kind"]: c for c in CATALOG}
_OPEN_PICKUP = ("pending", "assigned", "scheduled", "in_transit")


def _ser(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, dict)):
        return v
    return v


def _snap(changes: list, obj, *fields):
    changes.append({"model": type(obj).__name__, "id": str(obj.id), "old": {f: _ser(getattr(obj, f)) for f in fields}})


MODELS = {"InventoryLot": InventoryLot, "Pickup": Pickup, "RecoveryCase": RecoveryCase, "PlantMetric": PlantMetric, "Anomaly": Anomaly}


def _restore_value(model, field, value):
    col = model.__table__.columns[field]
    if value is None:
        return None
    if isinstance(col.type, (SADateTime, UTCDateTime)):
        return datetime.fromisoformat(value)
    if isinstance(col.type, SAUuid):
        return uuid.UUID(value)
    return value


def _load_target(db: Session, kind: str, target_id: str, org_id):
    target = KINDS[kind]["target"]
    try:
        tid = uuid.UUID(target_id)
    except ValueError:
        raise NotFound("Scenario target not found.", "TARGET_NOT_FOUND")
    model = {"case": RecoveryCase, "lot": InventoryLot, "plant": Plant}[target]
    obj = db.get(model, tid)
    if not obj or obj.org_id != org_id:
        raise NotFound("Scenario target not found.", "TARGET_NOT_FOUND")
    return obj


def _case_prob(db, case, delay_extra=0):
    c = eng.Constraints(case.pickup_delay_min + delay_extra, case.handover_buffer_min, list(case.excluded_rungs), list(case.excluded_recipients))
    opts = eng.plan(cases.lot_input(db, case.lot, case.id), cases.recipient_inputs(db), c)
    rec = next((o for o in opts if o.is_recommended), None)
    return (rec.rung, rec.p_success) if rec else (None, 0.0)


def preview(db: Session, kind: str, target_id: str, org_id) -> dict:
    if kind not in KINDS:
        raise NotFound("Unknown scenario.", "SCENARIO_NOT_FOUND")
    t = _load_target(db, kind, target_id, org_id)
    now = utcnow()
    effects: list[str] = []
    if kind in ("rider_cancels", "late_pickup", "ngo_declines"):
        extra = {"rider_cancels": 45, "late_pickup": 60, "ngo_declines": 0}[kind]
        before = _case_prob(db, t)
        after = _case_prob(db, t, extra) if kind != "ngo_declines" else _case_prob(db, _Shadow(t, str(t.recipient_id)))
        effects.append(f"Current plan: {before[0] or 'none'} at {round(before[1]*100)}% modelled success.")
        effects.append(f"After the event: {after[0] or 'no eligible pathway'} at {round(after[1]*100)}% modelled success.")
        if kind != "ngo_declines" and not any(p.status in _OPEN_PICKUP for p in _pickups(db, t)):
            effects.append("This case has no active pickup yet, so applying it will be refused.")
        if kind == "ngo_declines" and not t.recipient_id:
            effects.append("This case has no assigned recipient yet, so applying it will be refused.")
    elif kind == "freezer_failure":
        f = freshness.assess(t.safe_until, t.window_minutes, now)
        new_rem = int(f.remaining_minutes * 0.4)
        effects.append(f"{t.lot_code}: remaining window {f.remaining_minutes} min → about {new_rem} min.")
        effects.append("Any open recovery case for this lot is replanned.")
    elif kind == "line_breakdown":
        n = len(db.execute(select(InventoryLot.id).where(InventoryLot.plant_id == t.id, InventoryLot.status == "available")).all())
        effects.append(f"{n} available lot(s) at {t.name} lose 25% of their remaining window.")
        effects.append("About 180 min of downtime is logged and a surplus lot is created.")
    return {"kind": kind, "title": KINDS[kind]["title"], "requires_confirmation": True, "simulated": True, "effects": effects}


class _Shadow:
    """Read-only view of a case with one recipient excluded, for previews."""
    def __init__(self, case, rid):
        self._c, self.excluded_recipients = case, [*case.excluded_recipients, rid]

    def __getattr__(self, n):
        return getattr(self._c, n)


def _pickups(db, case):
    return db.execute(select(Pickup).where(Pickup.case_id == case.id)).scalars().all()


def apply(db: Session, kind: str, target_id: str, actor: User) -> ScenarioRun:
    if kind not in KINDS:
        raise NotFound("Unknown scenario.", "SCENARIO_NOT_FOUND")
    org_id = actor.org_id
    t = _load_target(db, kind, target_id, org_id)
    impact = preview(db, kind, target_id, org_id)
    changes: list = []
    created: list = []
    label = f"Scenario: {KINDS[kind]['title']}"
    now = utcnow()

    if kind in ("rider_cancels", "late_pickup"):
        pk = next((p for p in _pickups(db, t) if p.status in _OPEN_PICKUP), None)
        if not pk:
            raise Conflict("This case has no active pickup to disrupt.", "NO_ACTIVE_PICKUP")
        _snap(changes, pk, "status", "eta", "delay_minutes", "delay_reason")
        _snap(changes, t, "status", "selected_rung", "recipient_id", "plan_version", "replan_count", "pickup_delay_min", "excluded_rungs", "excluded_recipients")
        if kind == "late_pickup":
            cases.delay_pickup(db, pk, actor, 60, "Simulated: vehicle held up in traffic", actor_label=label)
        else:
            pk.status = "cancelled"
            t.pickup_delay_min += 45
            audit.record(db, org_id, actor, "pickup.cancelled", "pickup", pk.id, "Rider cancelled the pickup (simulated)", {}, t.id, actor_label=label)
            events.publish(db, org_id, "pickup.delayed", {"pickup_id": str(pk.id), "case_id": str(t.id)})
            cases.replan(db, t, actor, "Rider cancelled", actor_label=label)
    elif kind == "ngo_declines":
        if not t.recipient_id or t.status not in ("awaiting_recipient", "accepted", "pickup_scheduled"):
            raise Conflict("This case has no assigned recipient to decline.", "NO_RECIPIENT")
        _snap(changes, t, "status", "selected_rung", "recipient_id", "plan_version", "replan_count", "pickup_delay_min", "excluded_rungs", "excluded_recipients")
        for pk in _pickups(db, t):
            if pk.status in _OPEN_PICKUP:
                _snap(changes, pk, "status")
                pk.status = "cancelled"
        name = t.recipient.name
        cases.replan(db, t, actor, f"{name} declined (simulated)", exclude_recipient=str(t.recipient_id), actor_label=label)
    elif kind == "freezer_failure":
        _snap(changes, t, "safe_until", "last_state")
        remaining = max((t.safe_until - now).total_seconds(), 0)
        t.safe_until = now + timedelta(seconds=remaining * 0.4)
        db.add(Anomaly(plant_id=t.plant_id, line="Cold store", kind="freezer_failure", severity="high", is_simulated=True,
                       description=f"Cold-chain excursion affecting lot {t.lot_code} (simulated).", affected_lot_ids=[str(t.id)]))
        cases.snapshot_freshness(db, t, "Scenario: freezer failure")
        events.publish(db, org_id, "freshness.updated", {"lot_id": str(t.id)})
        events.notify_roles(db, org_id, [sec.OPS, sec.RECOVERY], "critical_freshness", f"Cold-chain failure: {t.lot_code}", "Recovery window cut by 60% (simulated).", "critical", "lot", t.id)
        open_case = db.execute(select(RecoveryCase).where(RecoveryCase.lot_id == t.id, RecoveryCase.status.in_(cases.ACTIVE_CASE))).scalar_one_or_none()
        if open_case:
            _snap(changes, open_case, "status", "selected_rung", "recipient_id", "plan_version", "replan_count", "pickup_delay_min", "excluded_rungs", "excluded_recipients")
            cases.replan(db, open_case, actor, "Freezer failure shortened the window", actor_label=label)
    elif kind == "line_breakdown":
        affected = []
        for lot in db.execute(select(InventoryLot).where(InventoryLot.plant_id == t.id, InventoryLot.status == "available")).scalars():
            _snap(changes, lot, "safe_until")
            lot.safe_until = now + timedelta(seconds=max((lot.safe_until - now).total_seconds(), 0) * 0.75)
            affected.append(str(lot.id))
        anomaly = Anomaly(plant_id=t.id, line="Line 2", kind="line_breakdown", severity="high", is_simulated=True,
                          description="Line 2 stopped: production delayed, freshness windows shortened (simulated).", affected_lot_ids=affected)
        db.add(anomaly)
        db.flush()
        created.append({"model": "Anomaly", "id": str(anomaly.id)})
        prod = db.execute(select(InventoryLot.product_id).where(InventoryLot.plant_id == t.id).limit(1)).scalar_one_or_none()
        if prod:
            lot = InventoryLot(org_id=org_id, plant_id=t.id, product_id=prod, lot_code=f"SIM-{uuid.uuid4().hex[:6].upper()}", quantity_kg=140,
                               produced_at=now - timedelta(hours=3), safe_until=now + timedelta(hours=4), window_minutes=720, storage="chilled", is_simulated=True, created_by=actor.id)
            db.add(lot)
            db.flush()
            created.append({"model": "InventoryLot", "id": str(lot.id)})
        pm = db.execute(select(PlantMetric).where(PlantMetric.plant_id == t.id, PlantMetric.day == now.date(), PlantMetric.line == "Line 2")).scalar_one_or_none()
        if pm:
            _snap(changes, pm, "downtime_min", "oee")
            pm.downtime_min += 180
            pm.oee = max(0.3, pm.oee - 0.12)
        events.publish(db, org_id, "lot.updated", {"plant_id": str(t.id)})
        events.notify_roles(db, org_id, [sec.OPS, sec.RECOVERY], "system_alert", f"Line breakdown at {t.name}", "Freshness windows shortened for nearby lots (simulated).", "critical", "plant", t.id)

    run = ScenarioRun(org_id=org_id, kind=kind, target_type=KINDS[kind]["target"], target_id=str(t.id), status="active", impact=impact,
                      changes=changes, created=created, created_by=actor.id)
    db.add(run)
    db.flush()
    audit.record(db, org_id, actor, "scenario.triggered", "scenario", run.id, f"{KINDS[kind]['title']} triggered (simulated)", {"kind": kind, "target": str(t.id)})
    events.publish(db, org_id, "scenario.triggered", {"kind": kind, "run_id": str(run.id)})
    return run


def reset(db: Session, actor: User) -> int:
    runs = db.execute(select(ScenarioRun).where(ScenarioRun.org_id == actor.org_id, ScenarioRun.status == "active").order_by(ScenarioRun.created_at.desc())).scalars().all()
    for run in runs:
        for ch in reversed(run.changes):
            model = MODELS[ch["model"]]
            obj = db.get(model, uuid.UUID(ch["id"]))
            if obj:
                for f, v in ch["old"].items():
                    setattr(obj, f, _restore_value(model, f, v))
                if ch["model"] == "RecoveryCase":
                    db.flush()
                    db.execute(delete(RecoveryOption).where(RecoveryOption.case_id == obj.id, RecoveryOption.plan_version > obj.plan_version))
        for cr in run.created:
            obj = db.get(MODELS[cr["model"]], uuid.UUID(cr["id"]))
            if obj is None:
                continue
            if cr["model"] == "InventoryLot":
                obj.status = "cancelled"
            else:
                db.delete(obj)
        run.status, run.reverted_at = "reverted", utcnow()
    audit.record(db, actor.org_id, actor, "scenario.reset", "scenario", "all", f"Scenario state reset ({len(runs)} run(s) reverted)", {"reverted": len(runs)})
    events.publish(db, actor.org_id, "scenario.triggered", {"kind": "reset"})
    return len(runs)
