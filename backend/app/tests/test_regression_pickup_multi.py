"""Regression: the single-recipient pickup flow must not run on multi-recipient allocation cases."""
from datetime import datetime, timedelta, timezone

from app.tests.test_allocation_api import (LOGI, NGO, OPS, P, auth, client, invariants, offered, respond, setup_case)  # noqa: F401


def _pickup(client, case_id):
    return client.post(f"{P}/recovery-cases/{case_id}/pickup", headers=auth(client, OPS),
                       json={"scheduled_for": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()})


def test_legacy_pickup_cannot_complete_multi_allocation_case(client):
    case_id, lot_id = setup_case(caps=(120, 0, 0))
    a = offered(client, case_id)[0]
    assert respond(client, NGO, a["id"], accept=True).status_code == 200
    r = _pickup(client, case_id)
    # Must be a clean 409 telling the user to use allocation transport/handover, never a 500 or a silent pickup.
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "USE_ALLOCATION_HANDOVER"
    h = client.post(f"{P}/allocations/{a['id']}/handover", headers=auth(client, LOGI))
    assert h.status_code == 200 and h.json()["case_status"] == "completed"
    invariants(lot_id)


def test_active_allocations_worklist_is_role_and_org_scoped(client):
    case_id, _ = setup_case(caps=(120, 0, 0))
    a = offered(client, case_id)[0]
    respond(client, NGO, a["id"], accept=True)
    rows = client.get(f"{P}/allocations/active", headers=auth(client, LOGI))
    assert rows.status_code == 200 and [r["id"] for r in rows.json()] == [a["id"]]
    assert rows.json()[0]["status"] == "accepted"
    assert client.get(f"{P}/allocations/active", headers=auth(client, NGO)).status_code == 403  # recipients have no worklist
    assert client.get(f"{P}/allocations/active").status_code == 401
