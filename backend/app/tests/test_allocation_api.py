"""Integration tests: DB transactions, atomic reservation, idempotency, RBAC, audit, simulation purity."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core import security as sec
from app.core.database import SessionLocal, utcnow
from app.core.errors import AppError, Conflict
from app.models import (Allocation, AuditEvent, Evidence, EventOutbox, InventoryLot, Notification, Plant, Product, Recipient,
                        RecoveryCase, SustainabilityMetric, User)
from app.services import allocations as svc
from app.services import audit, cases
from app.tests.conftest import auth, client  # noqa: F401

P = "/api/v1"
VERDANA = "admin@verdanafoods.demo"
RECOVERY = "recovery@verdanafoods.demo"
OPS = "ops@verdanafoods.demo"
LOGI = "logistics@verdanafoods.demo"
NGO = "recipient@annapurna.demo"


def setup_case(kg=120.0, remaining=600, caps=(50, 40, 30), evidence=True, sku="BK-101"):
    """Real lot + real case through the existing workflow. Caps shape the three NGO recipients."""
    with SessionLocal() as db:
        org_admin = db.execute(select(User).where(User.email == VERDANA)).scalar_one()
        plant = db.execute(select(Plant).where(Plant.org_id == org_admin.org_id).order_by(Plant.name)).scalars().first()
        prod = db.execute(select(Product).where(Product.sku == sku, Product.org_id == org_admin.org_id)).scalar_one()
        now = utcnow()
        lot = InventoryLot(org_id=org_admin.org_id, plant_id=plant.id, product_id=prod.id, lot_code=f"T-{uuid.uuid4().hex[:8]}", quantity_kg=kg,
                           window_minutes=4000, produced_at=now - timedelta(minutes=4000 - remaining), safe_until=now + timedelta(minutes=remaining))
        db.add(lot)
        db.flush()
        rec = {r.name: r for r in db.execute(select(Recipient)).scalars()}
        for name, cap in zip(("Annapurna Food Bank", "Roti Ghar Foundation", "Seva Kitchens Trust"), caps):
            rec[name].capacity_kg = cap
        case = cases.create_case(db, lot, org_admin)
        if evidence:
            for k in ("photo", "temperature_log", "label"):
                db.add(Evidence(org_id=case.org_id, case_id=case.id, kind=k, original_name=f"{k}.txt", stored_name=uuid.uuid4().hex, content_type="text/plain", size_bytes=1, sha256="0" * 64))
        db.commit()
        return str(case.id), str(lot.id)


def recipient_user(name_prefix: str, email: str):
    with SessionLocal() as db:
        r = db.execute(select(Recipient).where(Recipient.name.like(f"{name_prefix}%"))).scalar_one()
        u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not u:
            org = db.execute(select(User).where(User.email == VERDANA)).scalar_one().org_id
            db.add(User(email=email, full_name=name_prefix, role=sec.RECIPIENT, org_id=org, recipient_id=r.id, password_hash=sec.hash_password("FoodAgent#2026demo")))
            db.commit()


def invariants(lot_id):
    with SessionLocal() as db:
        lot = db.get(InventoryLot, uuid.UUID(lot_id))
        rows = db.execute(select(Allocation).where(Allocation.lot_id == lot.id)).scalars().all()
        held = sum((a.received_kg if a.status == "completed" else a.quantity_kg) for a in rows if a.status in ("proposed", "offered", "accepted", "completed"))
        assert lot.reserved_kg == pytest.approx(held), (lot.reserved_kg, held)
        assert 0 <= lot.reserved_kg <= lot.quantity_kg + 1e-6
        live = [(a.case_id, a.recipient_id) for a in rows if a.status in ("proposed", "offered", "accepted")]
        assert len(live) == len(set(live))
        return lot.reserved_kg


def commit(client, case_id, who=RECOVERY, **kw):
    return client.post(f"{P}/recovery-cases/{case_id}/allocation/commit", json={"confirm": True, **kw}, headers=auth(client, who))


def offered(client, case_id):
    c = commit(client, case_id)
    assert c.status_code == 201, c.text
    r = client.post(f"{P}/recovery-cases/{case_id}/allocation/approve", json={}, headers=auth(client, RECOVERY))
    assert r.status_code == 200
    return r.json()["summary"]["allocations"]


def respond(client, who, alloc_id, **body):
    return client.post(f"{P}/recipient/allocations/{alloc_id}/respond", json=body, headers=auth(client, who))


def test_multi_recipient_commit_reserves_exactly_the_lot(client):
    case_id, lot_id = setup_case()
    r = commit(client, case_id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan"]["allocated_kg"] == 120 and body["summary"]["unallocated_kg"] == 0
    assert sorted(a["quantity_kg"] for a in body["summary"]["allocations"]) == [30, 40, 50]
    assert invariants(lot_id) == 120
    again = commit(client, case_id)  # nothing left to plan, no double allocation
    assert again.status_code == 409 and again.json()["error"]["code"] == "NO_FEASIBLE_ALLOCATION"
    assert invariants(lot_id) == 120


def test_preview_and_simulation_have_no_side_effects(client):
    case_id, lot_id = setup_case()
    h = auth(client, RECOVERY)
    with SessionLocal() as db:
        before = (db.scalar(select(func.count()).select_from(Allocation)), db.scalar(select(func.count()).select_from(AuditEvent)),
                  db.scalar(select(func.count()).select_from(EventOutbox)), db.scalar(select(func.count()).select_from(Notification)))
    assert client.post(f"{P}/recovery-cases/{case_id}/allocation/plan", json={}, headers=h).json()["plan"]["allocated_kg"] == 120
    cmp = client.post(f"{P}/recovery-cases/{case_id}/allocation/compare", json={}, headers=h).json()
    assert cmp["simulated"] and len(cmp["strategies"]) == 5
    with SessionLocal() as db:
        rid = str(db.execute(select(Recipient.id).where(Recipient.name.like("Annapurna%"))).scalar_one())
    for body in ({"scenario": "recipient_rejection", "recipient_id": rid}, {"scenario": "capacity_reduction", "recipient_id": rid, "capacity_kg": 10},
                 {"scenario": "vehicle_delay", "delay_minutes": 90}, {"scenario": "missing_evidence"}, {"scenario": "no_feasible_option"}):
        s = client.post(f"{P}/recovery-cases/{case_id}/allocation/simulate", json=body, headers=h)
        assert s.status_code == 200 and s.json()["simulated"] is True
        assert s.json()["before"]["allocated_kg"] >= s.json()["after"]["allocated_kg"]
    assert client.post(f"{P}/recovery-cases/{case_id}/allocation/simulate", json={"scenario": "no_feasible_option"}, headers=h).json()["after"]["status"] in ("infeasible", "blocked")
    with SessionLocal() as db:
        after = (db.scalar(select(func.count()).select_from(Allocation)), db.scalar(select(func.count()).select_from(AuditEvent)),
                 db.scalar(select(func.count()).select_from(EventOutbox)), db.scalar(select(func.count()).select_from(Notification)))
    assert before == after and invariants(lot_id) == 0


def test_commit_requires_explicit_confirmation(client):
    case_id, lot_id = setup_case()
    r = client.post(f"{P}/recovery-cases/{case_id}/allocation/commit", json={}, headers=auth(client, RECOVERY))
    assert r.status_code == 422 and invariants(lot_id) == 0


def test_rbac(client):
    case_id, _ = setup_case()
    assert commit(client, case_id, who=OPS).status_code == 403
    assert commit(client, case_id, who=LOGI).status_code == 403
    assert commit(client, case_id, who=NGO).status_code == 403
    assert client.post(f"{P}/recovery-cases/{case_id}/allocation/plan", json={}, headers=auth(client, LOGI)).status_code == 200
    assert client.post(f"{P}/recovery-cases/{case_id}/allocation/plan", json={}).status_code == 401
    assert client.post(f"{P}/recovery-cases/{case_id}/allocation/plan", json={}, headers=auth(client, "admin@sahyadribev.demo")).status_code == 404  # other org


def test_rejection_releases_only_that_slice_and_replans_it(client):
    case_id, lot_id = setup_case(caps=(50, 40, 30))
    allocs = offered(client, case_id)
    annapurna = next(a for a in allocs if a["recipient_name"].startswith("Annapurna"))
    assert respond(client, NGO, annapurna["id"], accept=True).json()["status"] == "accepted"  # confirmed slice must survive
    recipient_user("Roti Ghar", "roti@demo.test")
    roti = next(a for a in allocs if a["recipient_name"].startswith("Roti"))
    r = respond(client, "roti@demo.test", roti["id"], accept=False, reason="Kitchen closed")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["released_kg"] == 40 and out["status"] == "rejected"
    summary = client.get(f"{P}/recovery-cases/{case_id}/allocations", headers=auth(client, RECOVERY)).json()
    by = {a["recipient_name"]: a for a in summary["allocations"]}
    assert by["Annapurna Food Bank"]["status"] == "accepted" and by["Annapurna Food Bank"]["quantity_kg"] == 50
    assert by["Roti Ghar Foundation"]["status"] == "rejected" and by["Roti Ghar Foundation"]["response_reason"] == "Kitchen closed"
    assert roti["recipient_id"] in summary["excluded_recipients"]
    # the 40 kg went to non-excluded recipients that still have capacity, never back to Roti Ghar
    new = [a for a in summary["allocations"] if a["status"] == "proposed"]
    assert all(a["recipient_name"] != "Roti Ghar Foundation" for a in new)
    assert sum(a["quantity_kg"] for a in new) == pytest.approx(40)
    assert summary["unallocated_kg"] == 0
    invariants(lot_id)
    with SessionLocal() as db:
        actions = [e.action for e in db.execute(select(AuditEvent).where(AuditEvent.case_id == uuid.UUID(case_id)).order_by(AuditEvent.seq)).scalars()]
        assert {"allocation.created", "allocation.offered", "recipient.accepted", "allocation.rejected", "recovery.plan_recalculated"} <= set(actions)
        assert audit.verify_chain(db, db.get(RecoveryCase, uuid.UUID(case_id)).org_id)["valid"]


def test_partial_acceptance_redistributes_remainder(client):
    case_id, lot_id = setup_case(caps=(120, 0, 0))
    allocs = offered(client, case_id)
    assert len(allocs) == 1 and allocs[0]["quantity_kg"] == 120
    out = respond(client, NGO, allocs[0]["id"], accept=True, accepted_kg=70).json()
    assert out["status"] == "accepted" and out["released_kg"] == 50
    s = client.get(f"{P}/recovery-cases/{case_id}/allocations", headers=auth(client, RECOVERY)).json()
    mine = next(a for a in s["allocations"] if a["recipient_name"].startswith("Annapurna"))
    assert mine["quantity_kg"] == 70
    invariants(lot_id)


def test_duplicate_rejection_is_idempotent(client):
    case_id, lot_id = setup_case()
    allocs = offered(client, case_id)
    a = next(x for x in allocs if x["recipient_name"].startswith("Annapurna"))
    first = respond(client, NGO, a["id"], accept=False, reason="no capacity").json()
    second = respond(client, NGO, a["id"], accept=False, reason="no capacity").json()
    assert first["duplicate"] is False and first["released_kg"] == 50
    assert second["duplicate"] is True and second["released_kg"] == 0
    invariants(lot_id)
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "allocation.rejected", AuditEvent.case_id == uuid.UUID(case_id)))
        assert n == 1


def test_concurrent_rejections_release_once(client):
    c = client
    case_id, lot_id = setup_case()
    allocs = offered(c, case_id)
    a = next(x for x in allocs if x["recipient_name"].startswith("Annapurna"))

    def go(_):
        with SessionLocal() as db:
            alloc = db.get(Allocation, uuid.UUID(a["id"]))
            user = db.execute(select(User).where(User.email == NGO)).scalar_one()
            try:
                out = svc.respond(db, alloc, user, False, "race")
                db.commit()
                return out
            except Exception as e:  # SQLite writer contention surfaces as OperationalError
                db.rollback()
                return {"error": type(e).__name__}

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(go, range(6)))
    won = [r for r in results if r.get("duplicate") is False]
    assert len(won) <= 1
    with SessionLocal() as db:
        al = db.get(Allocation, uuid.UUID(a["id"]))
        assert al.status in ("rejected", "offered")
    invariants(lot_id)


def test_concurrent_commits_never_double_allocate(client):
    case_id, lot_id = setup_case(kg=100, caps=(500, 500, 500))

    def go(i):
        with SessionLocal() as db:
            case = db.get(RecoveryCase, uuid.UUID(case_id))
            user = db.execute(select(User).where(User.email == RECOVERY)).scalar_one()
            try:
                svc.commit_plan(db, case, user, ["max_recovery", "fastest", "lowest_risk", "lowest_distance"][i % 4])
                db.commit()
                return "ok"
            except (Conflict, AppError) as e:
                db.rollback()
                return e.code if hasattr(e, "code") else "conflict"
            except Exception as e:
                db.rollback()
                return type(e).__name__

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(go, range(8)))
    assert "ok" in results
    reserved = invariants(lot_id)  # reserved <= quantity and == sum of live allocations, one live slice per recipient
    assert reserved <= 100 + 1e-6


def test_atomic_reserve_refuses_oversubscription(client):
    _, lot_id = setup_case(kg=100)
    with SessionLocal() as db:
        svc.reserve(db, uuid.UUID(lot_id), 60)
        with pytest.raises(Conflict):
            svc.reserve(db, uuid.UUID(lot_id), 60)
        db.commit()
    assert invariants.__name__  # reserved stays 60
    with SessionLocal() as db:
        assert db.get(InventoryLot, uuid.UUID(lot_id)).reserved_kg == 60
        with pytest.raises(Conflict):
            svc.release(db, uuid.UUID(lot_id), 80)  # never release more than is reserved


def test_transport_failure_reassigns_only_affected_slice(client):
    case_id, lot_id = setup_case(caps=(50, 40, 30))
    allocs = offered(client, case_id)
    a = next(x for x in allocs if x["recipient_name"].startswith("Annapurna"))
    respond(client, NGO, a["id"], accept=True)
    r = client.post(f"{P}/allocations/{a['id']}/transport", json={"kind": "failure", "reason": "Vehicle breakdown"}, headers=auth(client, LOGI))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "failed" and out["released_kg"] == 50
    assert "No alternative transport is modelled" in out["note"]
    s = client.get(f"{P}/recovery-cases/{case_id}/allocations", headers=auth(client, RECOVERY)).json()
    others = [x for x in s["allocations"] if not x["recipient_name"].startswith("Annapurna") and x["status"] == "offered"]
    assert sum(x["quantity_kg"] for x in others) == 70  # untouched
    invariants(lot_id)


def test_delay_within_deadline_keeps_plan_and_breaching_delay_replans(client):
    case_id, lot_id = setup_case(caps=(120, 0, 0), remaining=400)
    allocs = offered(client, case_id)
    a = allocs[0]
    respond(client, NGO, a["id"], accept=True)
    ok = client.post(f"{P}/allocations/{a['id']}/transport", json={"kind": "delay", "minutes": 30, "reason": "traffic"}, headers=auth(client, LOGI)).json()
    assert ok["outcome"] == "still_feasible"
    late = client.post(f"{P}/allocations/{a['id']}/transport", json={"kind": "delay", "minutes": 480, "reason": "breakdown"}, headers=auth(client, LOGI)).json()
    assert late["status"] == "failed" and late["released_kg"] == 120
    assert late["outcome"] == "needs_human" and late["requires_human_intervention"] is True  # nothing else feasible: no invented route
    s = client.get(f"{P}/recovery-cases/{case_id}/allocations", headers=auth(client, RECOVERY)).json()
    assert s["unallocated_kg"] == 120
    invariants(lot_id)


def test_missing_evidence_blocks_commit(client):
    case_id, lot_id = setup_case(evidence=False, caps=(50, 40, 30))
    r = commit(client, case_id)
    # human-consumption pathways stay blocked without evidence; only feed/biogas may be proposed
    assert r.status_code == 201
    assert {a["rung"] for a in r.json()["summary"]["allocations"]} <= {"R3", "R4"}
    assert any(x["code"] == "EVIDENCE_MISSING" for x in r.json()["plan"]["rejected"])
    invariants(lot_id)
    with SessionLocal() as db:  # and with no feed/biogas partner at all the lot is blocked, never auto-approved
        for rc in db.execute(select(Recipient).where(Recipient.kind.in_(("feed", "biogas", "buyer")))).scalars():
            rc.status = "inactive"
        db.commit()
    case2, lot2 = setup_case(evidence=False)
    r2 = commit(client, case2)
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "NO_FEASIBLE_ALLOCATION"
    assert invariants(lot2) == 0


def test_full_handover_completes_case_and_records_impact(client):
    case_id, lot_id = setup_case(caps=(120, 0, 0))
    a = offered(client, case_id)[0]
    assert client.post(f"{P}/allocations/{a['id']}/handover", headers=auth(client, LOGI)).status_code == 409  # not accepted yet
    respond(client, NGO, a["id"], accept=True)
    h = client.post(f"{P}/allocations/{a['id']}/handover", headers=auth(client, LOGI)).json()
    assert h["case_status"] == "completed" and h["recovered_kg"] == 120
    dup = client.post(f"{P}/allocations/{a['id']}/handover", headers=auth(client, LOGI)).json()
    assert dup["duplicate"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SustainabilityMetric).where(SustainabilityMetric.case_id == uuid.UUID(case_id))) == 1
        assert db.get(InventoryLot, uuid.UUID(lot_id)).status == "recovered"
    invariants(lot_id)


def test_short_handover_does_not_claim_completion(client):
    case_id, lot_id = setup_case(caps=(120, 0, 0))
    a = offered(client, case_id)[0]
    respond(client, NGO, a["id"], accept=True)
    h = client.post(f"{P}/allocations/{a['id']}/handover?received_kg=90", headers=auth(client, LOGI)).json()
    assert h["case_status"] != "completed" and h["shortfall_kg"] == 30 and "not recovered" in h["next_action"]
    invariants(lot_id)


def test_cancelling_case_releases_allocations(client):
    case_id, lot_id = setup_case()
    commit(client, case_id)
    assert invariants(lot_id) == 120
    assert client.post(f"{P}/recovery-cases/{case_id}/cancel", json={"note": "stop"}, headers=auth(client, RECOVERY)).status_code == 200
    assert invariants(lot_id) == 0


def test_single_recipient_workflow_blocked_when_allocations_live(client):
    case_id, _ = setup_case()
    commit(client, case_id)
    r = client.post(f"{P}/recovery-cases/{case_id}/replan", json={"reason": "manual"}, headers=auth(client, RECOVERY))
    assert r.status_code == 409 and r.json()["error"]["code"] == "USE_ALLOCATION_REPLAN"


def test_manual_cancel_requires_reason_and_is_audited(client):
    case_id, lot_id = setup_case()
    allocs = commit(client, case_id).json()["summary"]["allocations"]
    aid = allocs[0]["id"]
    assert client.post(f"{P}/allocations/{aid}/cancel", json={}, headers=auth(client, RECOVERY)).status_code == 422
    r = client.post(f"{P}/allocations/{aid}/cancel", json={"reason": "Manager override"}, headers=auth(client, RECOVERY))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    invariants(lot_id)


def test_other_recipient_cannot_respond_to_someone_elses_offer(client):
    case_id, _ = setup_case()
    allocs = offered(client, case_id)
    roti = next(a for a in allocs if a["recipient_name"].startswith("Roti"))
    assert respond(client, NGO, roti["id"], accept=True).status_code == 404
