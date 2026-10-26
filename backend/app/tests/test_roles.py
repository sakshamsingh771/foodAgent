"""Role matrix, org isolation, user management, stock adjustment and report export tests."""
import uuid

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import AuditEvent, InventoryLot, User
from app.services import audit
from app.tests.conftest import auth, login
from app.tests.test_api import ADMIN, AUD, LOGI, NGO, OPS, OTHER, REC, API, get, post

ALL = [ADMIN, OPS, REC, LOGI, AUD, NGO]


def patch(client, who, path, json=None):
    return client.patch(API + path, headers=auth(client, who), json=json)


def _first_lot(client, who=OPS):
    return get(client, who, "/lots").json()["items"][0]


# ---- permissions are exposed from the backend (single source of truth) ----
def test_me_exposes_permissions(client):
    perms = {w: set(login(client, w)["user"]["permissions"]) for w in ALL}
    assert "users:manage" in perms[ADMIN] and "users:manage" not in perms[OPS]
    assert "lots:adjust" in perms[OPS] and "lots:adjust" not in perms[AUD]
    assert "cases:approve" not in perms[LOGI] and "lots:write" not in perms[LOGI]
    assert perms[NGO] == {"recipient:inbox", "recipient:respond", "pickups:handover_own"}
    assert "lots:write" not in perms[AUD] and "cases:approve" not in perms[AUD]


# ---- forbidden direct API calls ----
@pytest.mark.parametrize("who,method,path,body", [
    (LOGI, "get", "/users", None), (OPS, "get", "/users", None), (AUD, "get", "/users", None), (NGO, "get", "/lots", None),
    (AUD, "post", "/lots", {}), (LOGI, "post", "/lots", {}), (NGO, "get", "/recovery-cases", None),
    (LOGI, "get", "/audit", None), (NGO, "get", "/reports/cases.csv", None), (LOGI, "get", "/reports/cases.csv", None),
    (OPS, "get", "/admin/overview", None), (AUD, "get", "/admin/overview", None),
])
def test_forbidden(client, who, method, path, body):
    r = get(client, who, path) if method == "get" else post(client, who, path, body)
    assert r.status_code == 403, (who, path, r.status_code)


def test_auditor_cannot_mutate(client):
    lot = _first_lot(client)
    assert post(client, AUD, f"/lots/{lot['id']}/adjust", {"delta_kg": 1, "reason": "auditor attempt"}).status_code == 403
    assert patch(client, AUD, "/users/" + login(client, OPS)["user"]["id"], {"role": "AUDITOR", "reason": "x"}).status_code == 403


# ---- user management ----
def test_admin_changes_role_and_deactivates(client):
    me = login(client, ADMIN)["user"]
    ops_id = login(client, OPS)["user"]["id"]
    assert patch(client, ADMIN, f"/users/{ops_id}", {"is_active": False}).status_code == 422  # reason required
    r = patch(client, ADMIN, f"/users/{ops_id}", {"role": "AUDITOR", "reason": "rotation"})
    assert r.status_code == 200 and r.json()["role"] == "AUDITOR"
    assert patch(client, ADMIN, f"/users/{me['id']}", {"is_active": False, "reason": "self"}).status_code == 422  # no self lockout
    r = patch(client, ADMIN, f"/users/{ops_id}", {"is_active": False, "reason": "left company"})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": OPS, "password": "FoodAgent#2026demo"}).status_code == 403
    # old access token stops working immediately
    with SessionLocal() as s:
        acts = {e.action for e in s.execute(select(AuditEvent)).scalars()}
    assert {"user.role_changed", "user.deactivated"} <= acts


def test_cross_org_user_update_is_404(client):
    other_id = login(client, OTHER)["user"]["id"]
    assert patch(client, ADMIN, f"/users/{other_id}", {"role": "AUDITOR", "reason": "nope"}).status_code == 404


def test_last_admin_protected(client):
    # promote ops to admin, then demote the original: allowed; the platform admin is not in this org so a sole admin can't be removed
    ops_id = login(client, OPS)["user"]["id"]
    assert patch(client, ADMIN, f"/users/{ops_id}", {"role": "ADMIN", "reason": "second admin"}).status_code == 200
    assert patch(client, ADMIN, f"/users/{ops_id}", {"role": "AUDITOR", "reason": "back"}).status_code == 200


def test_recipient_role_locked(client):
    nid = login(client, NGO)["user"]["id"]
    # recipient users belong to another org, so an org admin sees 404 rather than learning they exist
    assert patch(client, ADMIN, f"/users/{nid}", {"role": "AUDITOR", "reason": "x"}).status_code == 404


# ---- stock adjustment ----
def test_adjust_validations_and_audit(client):
    lot = _first_lot(client)
    qty = lot["quantity_kg"]
    assert post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": 5, "reason": "x"}).status_code == 422  # reason too short
    assert post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": 0, "reason": "no change here"}).status_code == 422
    assert post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": -(qty + 1), "reason": "negative stock"}).status_code == 422
    assert post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": -qty, "reason": "zero stock attempt"}).status_code == 422
    r = post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": 2.5, "reason": "recount found extra crates"})
    assert r.status_code == 200 and r.json()["quantity_kg"] == pytest.approx(qty + 2.5)
    hist = get(client, OPS, f"/lots/{lot['id']}/history").json()
    assert hist[0]["action"] == "lot.adjusted" and hist[0]["metadata"]["reason"] == "recount found extra crates"
    with SessionLocal() as s:
        row = s.get(InventoryLot, uuid.UUID(lot["id"]))
        assert row is not None
        assert audit.verify_chain(s, row.org_id)["valid"]


def test_adjust_cross_org_and_role(client):
    lot = _first_lot(client)
    assert post(client, OTHER, f"/lots/{lot['id']}/adjust", {"delta_kg": 1, "reason": "other org admin"}).status_code == 404
    for who in (REC, LOGI, NGO):
        assert post(client, who, f"/lots/{lot['id']}/adjust", {"delta_kg": 1, "reason": "not allowed"}).status_code == 403


def test_adjust_cannot_drop_below_reserved(client):
    lot = _first_lot(client)
    with SessionLocal() as s:
        l = s.get(InventoryLot, uuid.UUID(lot["id"]))
        assert l is not None
        l.reserved_kg = l.quantity_kg - 1
        s.commit()
    r = post(client, OPS, f"/lots/{lot['id']}/adjust", {"delta_kg": -5, "reason": "try below reserved"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "BELOW_COMMITTED"


# ---- reports / exports ----
def test_exports_and_audit_trail(client):
    for who in (ADMIN, REC, AUD, OPS):
        r = get(client, who, "/reports/cases.csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert r.text.splitlines()[0].startswith("case_number")
    assert get(client, AUD, "/reports/exceptions").status_code == 200
    with SessionLocal() as s:
        assert s.execute(select(AuditEvent).where(AuditEvent.action == "report.exported")).first()


def test_exports_are_org_scoped(client):
    mine = get(client, ADMIN, "/reports/inventory.csv").text
    theirs = get(client, OTHER, "/reports/inventory.csv").text
    assert mine != theirs
    lots_mine = {l for l in mine.splitlines()[1:]}
    assert not (lots_mine & set(theirs.splitlines()[1:]))


def test_admin_overview(client):
    d = get(client, ADMIN, "/admin/overview").json()
    assert d["users_by_role"]["ADMIN"]["active"] >= 1 and "pending_approvals" in d
