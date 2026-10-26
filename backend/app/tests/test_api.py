from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.database import SessionLocal
from app.models import AuditEvent
from app.seed import DEMO_PASSWORD
from app.tests.conftest import auth, login

API = "/api/v1"
ADMIN, OPS, REC = "admin@verdanafoods.demo", "ops@verdanafoods.demo", "recovery@verdanafoods.demo"
LOGI, AUD, NGO = "logistics@verdanafoods.demo", "auditor@verdanafoods.demo", "recipient@annapurna.demo"
OTHER = "admin@sahyadribev.demo"


def get(client, who, path, **kw):
    return client.get(API + path, headers=auth(client, who), **kw)


def post(client, who, path, json=None, **kw):
    return client.post(API + path, headers=auth(client, who), json=json, **kw)


# ---------------- auth ----------------
def test_login_me_refresh_logout(client):
    tokens = login(client, ADMIN)
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=h).json()["role"] == "ADMIN"
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    # refresh tokens rotate: the old one no longer works
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    new = r.json()
    assert client.post(f"{API}/auth/logout", json={"refresh_token": new["refresh_token"]}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_bad_login_and_no_token(client):
    r = client.post(f"{API}/auth/login", json={"email": ADMIN, "password": "wrong-password1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "request_id" in r.json()["error"]
    assert client.get(f"{API}/lots").status_code == 401
    assert client.get(f"{API}/lots", headers={"Authorization": "Bearer junk"}).json()["error"]["code"] == "TOKEN_INVALID"


def test_register_creates_org_and_validates(client):
    weak = client.post(f"{API}/auth/register", json={"organization_name": "Test Bakery Co", "full_name": "A B", "email": "x@y.io", "password": "short"})
    assert weak.status_code == 422
    nodigit = client.post(f"{API}/auth/register", json={"organization_name": "Test Bakery Co", "full_name": "A B", "email": "x@y.io", "password": "onlyletterslong"})
    assert nodigit.json()["error"]["code"] == "WEAK_PASSWORD"
    ok = client.post(f"{API}/auth/register", json={"organization_name": "Lakeside Kitchens", "full_name": "Isha Rao", "email": "isha@lakeside.io", "password": "Strong#Pass123"})
    # public sign-up never yields an immediate administrator: it waits for protected approval
    assert ok.status_code == 201 and ok.json()["status"] == "PENDING" and ok.json()["session"] is None
    dup = client.post(f"{API}/auth/register", json={"organization_name": "Lakeside Kitchens", "full_name": "Isha Rao", "email": "isha@lakeside.io", "password": "Strong#Pass123"})
    assert dup.status_code == 409


def test_password_is_hashed(client):
    from app.models import User
    with SessionLocal() as s:
        h = s.execute(select(User.password_hash).where(User.email == ADMIN)).scalar_one()
    assert h.startswith("$2") and DEMO_PASSWORD not in h


def test_all_demo_roles_resolve_and_restricted_operations_are_denied(client):
    expected = {
        ADMIN: "ADMIN", OPS: "OPERATIONS_MANAGER", REC: "RECOVERY_MANAGER",
        LOGI: "LOGISTICS", AUD: "AUDITOR", NGO: "RECIPIENT",
    }
    for email, role in expected.items():
        assert client.get(f"{API}/auth/me", headers=auth(client, email)).json()["role"] == role

    lot_id = get(client, OPS, "/lots").json()["items"][0]["id"]
    case_id = get(client, REC, "/recovery-cases").json()["items"][0]["id"]
    assert post(client, REC, "/lots", {}).status_code == 403
    assert post(client, AUD, f"/recovery-cases/{case_id}/approve", {"rung": "R1"}).status_code == 403
    assert post(client, OPS, f"/recovery-cases/{case_id}/approve", {"rung": "R1"}).status_code == 403
    assert post(client, LOGI, f"/recovery-cases/{case_id}/pickup", {}).status_code == 403
    assert post(client, NGO, f"/recovery-cases/{case_id}/cancel", {}).status_code == 403
    assert get(client, NGO, f"/lots/{lot_id}").status_code == 403


def test_seed_is_repeatable_without_duplicate_demo_accounts(client):
    from app.models import Organization, User
    from app.seed import seed

    with SessionLocal() as s:
        result = seed(s)
        assert result["seeded"] is False
        assert s.query(Organization).filter(Organization.slug == "verdana-foods").count() == 1
        assert s.query(User).filter(User.email == ADMIN).count() == 1


# ---------------- RBAC + org isolation ----------------
def test_role_permissions_enforced_on_backend(client):
    lots = get(client, OPS, "/lots").json()["items"]
    lot = lots[0]["id"]
    assert post(client, AUD, "/recovery-cases", {"lot_id": lot}).status_code == 403          # auditor read-only
    assert post(client, LOGI, "/recovery-cases", {"lot_id": lot}).status_code == 403
    assert get(client, NGO, "/lots").status_code == 403                                      # recipient has no inventory access
    assert get(client, NGO, "/audit").status_code == 403
    assert get(client, OPS, "/audit").status_code == 403                                     # ops can't read audit trail
    assert get(client, AUD, "/audit").status_code == 200
    cases = get(client, REC, "/recovery-cases?status=pending_approval").json()["items"]
    cid = cases[0]["id"]
    assert post(client, OPS, f"/recovery-cases/{cid}/approve", {"rung": "R1"}).status_code == 403   # ops can't approve
    assert post(client, LOGI, "/scenarios/apply", {"kind": "late_pickup", "target_id": cid, "confirm": True}).status_code == 403


def test_organization_isolation(client):
    mine = get(client, ADMIN, "/lots?page_size=100").json()["items"]
    theirs = get(client, OTHER, "/lots?page_size=100").json()["items"]
    assert mine and theirs
    assert not {l["id"] for l in mine} & {l["id"] for l in theirs}
    assert all(l["product"]["sku"].startswith("BV") for l in theirs)
    # direct access to another org's records is a 404, not data
    assert get(client, OTHER, f"/lots/{mine[0]['id']}").status_code == 404
    case_id = get(client, ADMIN, "/recovery-cases").json()["items"][0]["id"]
    assert get(client, OTHER, f"/recovery-cases/{case_id}").status_code == 404
    assert post(client, OTHER, f"/recovery-cases/{case_id}/cancel", {}).status_code == 404
    assert all(e["actor"] for e in get(client, OTHER, "/audit").json()["items"])
    assert get(client, OTHER, "/dashboard/summary").json()["kpis"]["lots_at_risk"] >= 0


def test_recipient_sees_only_own_cases(client):
    inbox = get(client, NGO, "/recipient/cases").json()
    assert inbox and all("lot" not in c for c in inbox)
    assert all(c["status"] in ("awaiting_recipient", "accepted", "pickup_scheduled", "in_transit", "completed") for c in inbox)


# ---------------- validation / errors ----------------
def test_validation_error_shape(client):
    r = post(client, OPS, "/lots", {"plant_id": "not-a-uuid", "quantity_kg": -5})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and isinstance(err["details"], list) and err["request_id"]


def test_lot_business_validation(client):
    ref = get(client, OPS, "/lots").json()["items"][0]
    now = datetime.now(timezone.utc)
    body = {"plant_id": ref["plant"]["id"], "product_id": ref["product"]["id"], "lot_code": "ZZ-TEST-01", "quantity_kg": 120,
            "produced_at": now.isoformat(), "safe_until": (now - timedelta(hours=1)).isoformat()}
    assert post(client, OPS, "/lots", body).json()["error"]["code"] == "INVALID_WINDOW"
    body["safe_until"] = (now + timedelta(hours=6)).isoformat()
    ok = post(client, OPS, "/lots", body)
    assert ok.status_code == 201 and ok.json()["freshness"]["state"] in ("SAFE", "ACT_SOON", "LOSS_IMMINENT")
    assert post(client, OPS, "/lots", body).json()["error"]["code"] == "LOT_CODE_TAKEN"


def test_pagination_and_filters(client):
    page = get(client, OPS, "/lots?page=1&page_size=3").json()
    assert len(page["items"]) == 3 and page["total"] >= 9 and page["pages"] >= 3
    mins = [l["freshness"]["remaining_minutes"] for l in page["items"]]
    assert mins == sorted(mins)                                    # most urgent first
    urgent = get(client, OPS, "/lots?urgency=LOSS_IMMINENT").json()["items"]
    assert urgent and all(l["freshness"]["state"] == "LOSS_IMMINENT" for l in urgent)
    assert get(client, OPS, "/lots?q=paneer").json()["total"] == 1
    assert get(client, OPS, "/lots?page_size=500").status_code == 422


# ---------------- the full recovery workflow ----------------
def test_end_to_end_recovery_workflow(client):
    lots = get(client, OPS, "/lots?urgency=ACT_SOON&page_size=50").json()["items"]
    lot = next(l for l in lots if l["product"]["sku"] == "DY-302" or (not l["open_case"] and l["product"]["sku"] in ("BK-101", "RM-202")))
    case = post(client, OPS, "/recovery-cases", {"lot_id": lot["id"]}).json()
    cid = case["id"]
    assert post(client, OPS, "/recovery-cases", {"lot_id": lot["id"]}).status_code == 409        # no duplicate cases

    detail = get(client, REC, f"/recovery-cases/{cid}").json()
    assert detail["status"] == "pending_approval" and len(detail["options"]) == 4
    assert "does not certify" in detail["disclaimer"]
    # needs evidence first for human-consumption pathways
    rec = next((o for o in detail["options"] if o["is_recommended"]), None)
    assert rec is not None

    for kind, name, ctype, data in (("photo", "p.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 20),
                                    ("temperature_log", "t.csv", "text/csv", b"time,temp\n1,4\n"),
                                    ("label", "l.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"1" * 20)):
        r = client.post(f"{API}/recovery-cases/{cid}/evidence", headers=auth(client, OPS), data={"kind": kind}, files={"file": (name, data, ctype)})
        assert r.status_code == 201, r.text
    detail = get(client, REC, f"/recovery-cases/{cid}").json()
    assert detail["evidence_score"] == 1.0
    options = {o["rung"]: o for o in detail["options"]}
    pick = next(o for o in detail["options"] if o["is_recommended"])
    assert pick["recipient_id"]

    # simulator responds to inputs
    sim = post(client, REC, f"/recovery-cases/{cid}/simulate", {"pickup_delay_min": 30, "acceptance_prob": 0.9, "handover_buffer_min": 20, "remaining_minutes": 600}).json()
    assert sim["simulated"] and sim["recommended"] and sim["hedge"]

    # human approval
    appr = post(client, REC, f"/recovery-cases/{cid}/approve", {"rung": pick["rung"], "recipient_id": pick["recipient_id"], "note": "ok"})
    assert appr.status_code == 200 and appr.json()["status"] == "awaiting_recipient"

    # recipient side: only the matching recipient user can see and answer the offer
    inbox = get(client, NGO, "/recipient/cases").json()
    mine = [c for c in inbox if c["id"] == cid]
    if not mine:  # a different recipient got the lot: confirm the NGO user can't see or answer it
        assert post(client, NGO, f"/recipient/cases/{cid}/respond", {"accept": True}).status_code == 404
        return
    assert post(client, NGO, f"/recipient/cases/{cid}/respond", {"accept": False}).json()["error"]["code"] == "REASON_REQUIRED"
    assert post(client, NGO, f"/recipient/cases/{cid}/respond", {"accept": True}).status_code == 200

    pk = post(client, OPS, f"/recovery-cases/{cid}/pickup", {"scheduled_for": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()})
    assert pk.status_code == 201
    pid = pk.json()["id"]
    assert client.post(f"{API}/pickups/{pid}/handover", headers=auth(client, LOGI), json={}).status_code == 409      # not arrived yet
    for status in ("in_transit", "arrived"):
        r = client.patch(f"{API}/pickups/{pid}/status", headers=auth(client, LOGI), json={"status": status})
        assert r.status_code == 200, r.text
    bad = client.patch(f"{API}/pickups/{pid}/status", headers=auth(client, LOGI), json={"status": "scheduled"})
    assert bad.json()["error"]["code"] == "INVALID_PICKUP_TRANSITION"
    before = get(client, ADMIN, "/sustainability/summary").json()["totals"]["kg"]
    done = client.post(f"{API}/pickups/{pid}/handover", headers=auth(client, NGO), json={"received_kg": lot["quantity_kg"]})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    after = get(client, ADMIN, "/sustainability/summary").json()["totals"]["kg"]
    assert after > before
    final = get(client, AUD, f"/recovery-cases/{cid}").json()
    assert final["status"] == "completed"
    actions = [e["action"] for e in final["timeline"]]
    for a in ("recovery_case.created", "evidence.uploaded", "recovery.approved", "recipient.accepted", "pickup.scheduled", "handover.confirmed", "case.completed"):
        assert a in actions, a
    assert get(client, AUD, "/audit/verify").json()["valid"] is True


def test_decline_triggers_replan_without_that_recipient(client):
    inbox = get(client, NGO, "/recipient/cases").json()
    offer = next(c for c in inbox if c["status"] == "awaiting_recipient")
    r = post(client, NGO, f"/recipient/cases/{offer['id']}/respond", {"accept": False, "reason": "No cold storage free today"})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    d = get(client, REC, f"/recovery-cases/{offer['id']}").json()
    assert d["replan_count"] == 1 and d["plan_version"] == 2
    assert all(o["recipient_name"] != "Annapurna Food Bank" for o in d["options"])
    assert any(e["action"] == "recipient.declined" for e in d["timeline"])


def test_reject_and_cancel(client):
    pend = get(client, REC, "/recovery-cases?status=pending_approval").json()["items"][0]
    assert post(client, REC, f"/recovery-cases/{pend['id']}/reject", {"note": "Condition unclear"}).json()["status"] == "rejected"
    assert post(client, REC, f"/recovery-cases/{pend['id']}/reject", {}).status_code == 409


def test_cannot_approve_ineligible_rung(client):
    pend = get(client, REC, "/recovery-cases?status=pending_approval").json()["items"][0]
    d = get(client, REC, f"/recovery-cases/{pend['id']}").json()
    bad = next((o for o in d["options"] if not o["eligible"]), None)
    if bad:
        r = post(client, REC, f"/recovery-cases/{pend['id']}/approve", {"rung": bad["rung"]})
        assert r.status_code == 409 and r.json()["error"]["code"] == "RUNG_NOT_ELIGIBLE"


# ---------------- uploads ----------------
def test_upload_validation(client):
    cid = get(client, OPS, "/recovery-cases?status=pending_approval").json()["items"][0]["id"]
    def up(name, data, ctype, kind="photo"):
        return client.post(f"{API}/recovery-cases/{cid}/evidence", headers=auth(client, OPS), data={"kind": kind}, files={"file": (name, data, ctype)})
    assert up("run.exe", b"MZ" + b"0" * 10, "application/octet-stream").json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert up("fake.png", b"not really a png", "image/png").json()["error"]["code"] == "INVALID_FILE_CONTENT"
    assert up("x.png", b"\x89PNG\r\n\x1a\n00", "text/html").json()["error"]["code"] == "CONTENT_TYPE_MISMATCH"
    assert up("x.png", b"", "image/png").json()["error"]["code"] == "EMPTY_FILE"
    assert up("../../etc/passwd.png", b"\x89PNG\r\n\x1a\n00", "image/png").status_code == 201      # path stripped; stored under random name
    assert up("ok.png", b"\x89PNG\r\n\x1a\n00", "image/png", kind="bogus").status_code == 422
    big = b"\x89PNG" + b"0" * (11 * 1024 * 1024)
    assert up("big.png", big, "image/png").status_code == 413


# ---------------- scenarios ----------------
def _targets(client):
    return get(client, OPS, "/scenarios/targets").json()


def test_scenarios_require_confirmation_and_support_reset(client):
    t = _targets(client)
    scheduled = next(c for c in get(client, OPS, "/recovery-cases?status=pickup_scheduled").json()["items"])
    prev = post(client, OPS, "/scenarios/preview", {"kind": "late_pickup", "target_id": scheduled["id"]}).json()
    assert prev["requires_confirmation"] and prev["effects"]
    assert post(client, OPS, "/scenarios/apply", {"kind": "late_pickup", "target_id": scheduled["id"]}).json()["error"]["code"] == "CONFIRMATION_REQUIRED"

    pk_before = get(client, OPS, "/pickups?active=true").json()["items"][0]
    run = post(client, OPS, "/scenarios/apply", {"kind": "late_pickup", "target_id": scheduled["id"], "confirm": True})
    assert run.status_code == 201
    pk_after = next(p for p in get(client, OPS, "/pickups?active=true").json()["items"] if p["id"] == pk_before["id"])
    assert pk_after["delay_minutes"] == pk_before["delay_minutes"] + 60
    assert any(n["type"] == "pickup_delay" for n in get(client, OPS, "/notifications").json()["items"])
    assert any(e["action"] == "scenario.triggered" for e in get(client, AUD, "/audit").json()["items"])

    rr = post(client, OPS, "/scenarios/reset")
    assert rr.json()["reverted"] == 1
    pk_reset = next(p for p in get(client, OPS, "/pickups?active=true").json()["items"] if p["id"] == pk_before["id"])
    assert pk_reset["delay_minutes"] == pk_before["delay_minutes"]


def test_freezer_failure_and_line_breakdown_and_rider_and_ngo(client):
    lot = next(l for l in get(client, OPS, "/lots?page_size=50").json()["items"] if l["open_case"] is None and l["freshness"]["state"] == "SAFE")
    before = lot["freshness"]["remaining_minutes"]
    assert post(client, OPS, "/scenarios/apply", {"kind": "freezer_failure", "target_id": lot["id"], "confirm": True}).status_code == 201
    after = get(client, OPS, f"/lots/{lot['id']}").json()["freshness"]["remaining_minutes"]
    assert after < before * 0.5

    plant = _targets(client)["plant"][0]["id"]
    n_lots = get(client, OPS, "/lots?page_size=100").json()["total"]
    assert post(client, OPS, "/scenarios/apply", {"kind": "line_breakdown", "target_id": plant, "confirm": True}).status_code == 201
    assert get(client, OPS, "/lots?page_size=100").json()["total"] == n_lots + 1               # surplus lot created
    assert any(a["kind"] == "line_breakdown" for a in get(client, OPS, f"/plant/overview?plant_id={plant}").json()["anomalies"])

    sched = get(client, OPS, "/recovery-cases?status=pickup_scheduled").json()["items"][0]
    r = post(client, OPS, "/scenarios/apply", {"kind": "rider_cancels", "target_id": sched["id"], "confirm": True})
    assert r.status_code == 201
    d = get(client, REC, f"/recovery-cases/{sched['id']}").json()
    assert d["status"] == "pending_approval" and d["replan_count"] >= 1

    waiting = next(c for c in get(client, OPS, "/recovery-cases?status=awaiting_recipient").json()["items"])
    assert post(client, OPS, "/scenarios/apply", {"kind": "ngo_declines", "target_id": waiting["id"], "confirm": True}).status_code == 201
    assert post(client, OPS, "/scenarios/reset").json()["reverted"] == 4
    assert get(client, OPS, "/lots?page_size=100").json()["total"] == n_lots                    # simulated surplus removed
    assert get(client, REC, f"/recovery-cases/{sched['id']}").json()["status"] == "pickup_scheduled"
    assert get(client, AUD, "/audit/verify").json()["valid"] is True


def test_scenario_target_in_other_org_rejected(client):
    other_lot = get(client, OTHER, "/lots").json()["items"][0]["id"]
    assert post(client, OPS, "/scenarios/apply", {"kind": "freezer_failure", "target_id": other_lot, "confirm": True}).status_code == 404


# ---------------- audit chain ----------------
def test_audit_chain_detects_tampering(client):
    assert get(client, AUD, "/audit/verify").json()["valid"] is True
    with SessionLocal() as s:
        victim = s.execute(select(AuditEvent).order_by(AuditEvent.seq).offset(3).limit(1)).scalar_one()
        s.execute(update(AuditEvent).where(AuditEvent.id == victim.id).values(summary="edited after the fact"))
        s.commit()
        seq = victim.seq
    v = get(client, AUD, "/audit/verify").json()
    assert v["valid"] is False and v["first_invalid_seq"] == seq


# ---------------- notifications / dashboard / search / exports ----------------
def test_notifications_read_flow(client):
    n = get(client, REC, "/notifications").json()
    assert n["unread"] > 0
    first = n["items"][0]["id"]
    assert post(client, REC, f"/notifications/{first}/read").json()["read"] is True
    assert post(client, REC, "/notifications/read-all").status_code == 200
    assert get(client, REC, "/notifications").json()["unread"] == 0
    other = get(client, OPS, "/notifications").json()["items"][0]["id"]
    assert post(client, REC, f"/notifications/{other}/read").status_code == 404                # can't touch someone else's


def test_dashboard_search_exports(client):
    k = get(client, OPS, "/dashboard/summary").json()
    assert k["kpis"]["kg_at_risk"] > 0 and len(k["trend"]) == 14 and k["recent_activity"]
    s = get(client, OPS, "/search?q=paneer").json()["results"]
    assert any(r["type"] == "lot" for r in s)
    assert get(client, NGO, "/search?q=paneer").json()["results"] == []
    csv = client.get(f"{API}/sustainability/export.csv", headers=auth(client, ADMIN))
    assert csv.status_code == 200 and csv.text.startswith("date,rung")
    assert client.get(f"{API}/audit/export.csv", headers=auth(client, AUD)).text.startswith("seq,timestamp")
    p = get(client, OPS, "/planning/forecast").json()
    assert p["backtest"]["mape_pct"] is not None and p["method"] == "STATISTICAL"
    assert get(client, OPS, "/plant/overview").json()["plant"]
    docs = get(client, AUD, "/compliance/documents").json()
    assert {d["status"] for d in docs} >= {"valid", "expiring_soon", "expired"}


def test_health_and_headers(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["service"] == "foodagent-api"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-request-id"]
    assert client.get("/nope").json()["error"]["code"] == "NOT_FOUND"
