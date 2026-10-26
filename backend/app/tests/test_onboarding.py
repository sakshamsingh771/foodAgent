"""Registration, invitations, approval, account status, role resolution and privilege-escalation tests."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.api import auth as auth_api
from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.models import AuditEvent, Invitation, Organization, Recipient, User
from app.seed import DEMO_PASSWORD
from app.tests.conftest import auth, login
from app.tests.test_api import ADMIN, API, AUD, LOGI, NGO, OPS, OTHER, REC, get, post

PW = "Strong#Pass123"
DEMO_ROLES = {
    ADMIN: ("ADMIN", "verdana-foods"), OPS: ("OPERATIONS_MANAGER", "verdana-foods"), REC: ("RECOVERY_MANAGER", "verdana-foods"),
    LOGI: ("LOGISTICS", "verdana-foods"), AUD: ("AUDITOR", "verdana-foods"), OTHER: ("ADMIN", "sahyadri-beverages"),
}


def reg(client, **kw):
    body = {"mode": "create_org", "full_name": "New Person", "email": "new@example.io", "password": PW, "confirm_password": PW, **kw}
    return client.post(f"{API}/auth/register", json=body)


def invite(client, who=ADMIN, email="invitee@example.io", role="LOGISTICS", **kw):
    r = post(client, who, "/invitations", {"email": email, "role": role, **kw})
    return r


def join(client, token, email="invitee@example.io", **kw):
    return client.post(f"{API}/auth/register", json={"mode": "join", "full_name": "Invited User", "email": email, "password": PW,
                                                      "confirm_password": PW, "invite_token": token, **kw})


# ---------- login & role resolution ----------
@pytest.mark.parametrize("email,expected", list(DEMO_ROLES.items()))
def test_demo_accounts_resolve_backend_role_and_org(client, email, expected):
    out = login(client, email)["user"]
    role, slug = expected
    assert out["role"] == role and out["status"] == "ACTIVE" and out["permissions"]
    with SessionLocal() as s:
        org = s.get(Organization, __import__("uuid").UUID(out["org_id"]))
        assert org is not None
        assert org.slug == slug


def test_recipient_demo_account_resolves(client):
    out = login(client, NGO)["user"]
    assert out["role"] == "RECIPIENT" and out["recipient_id"] and "lots:read" not in out["permissions"]


def test_login_failures(client):
    assert client.post(f"{API}/auth/login", json={"email": ADMIN, "password": "nope-nope-1"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "ghost@nowhere.io", "password": DEMO_PASSWORD}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "not-an-email", "password": "x"}).status_code == 422


def test_login_lockout_after_repeated_failures(client, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "max_failed_logins", 3)
    for _ in range(3):
        client.post(f"{API}/auth/login", json={"email": OPS, "password": "wrong-pass-1"})
    r = client.post(f"{API}/auth/login", json={"email": OPS, "password": DEMO_PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "ACCOUNT_LOCKED_TEMPORARILY"


def test_refresh_rotation_and_logout(client):
    t = login(client, OPS)
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert client.post(f"{API}/auth/logout", json={"refresh_token": r.json()["refresh_token"]}).status_code == 204
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 401


# ---------- public registration cannot escalate ----------
@pytest.mark.parametrize("extra", [{"role": "ADMIN"}, {"org_id": "00000000-0000-0000-0000-000000000000"}, {"status": "ACTIVE"},
                                   {"permissions": ["users:manage"]}, {"is_platform_admin": True}, {"requested_role": "ADMIN"}])
def test_registration_rejects_privileged_fields(client, extra):
    r = reg(client, organization_name="Evil Corp", **extra)
    assert r.status_code == 422
    with SessionLocal() as s:
        assert s.query(User).filter(User.email == "new@example.io").count() == 0


def test_create_org_is_pending_not_admin(client):
    r = reg(client, organization_name="Lakeside Kitchens")
    assert r.status_code == 201 and r.json()["status"] == "PENDING" and r.json()["session"] is None
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.email == "new@example.io")).scalar_one()
        assert u.role == "PENDING" and u.requested_role == "ADMIN" and u.is_active is False
    login_r = client.post(f"{API}/auth/login", json={"email": "new@example.io", "password": PW})
    assert login_r.status_code == 403 and login_r.json()["error"]["code"] == "ACCOUNT_PENDING"


def test_password_mismatch_and_weak(client):
    assert reg(client, organization_name="Org Two", confirm_password="Different#123").status_code == 422
    assert reg(client, organization_name="Org Two", password="onlyletterslong", confirm_password="onlyletterslong").json()["error"]["code"] == "WEAK_PASSWORD"


def test_setup_token_provisions_first_admin(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "first_admin_setup_token", "s" * 32)
    assert reg(client, organization_name="Wrong Token Co", setup_token="x" * 32).status_code == 403
    ok = reg(client, organization_name="Right Token Co", setup_token="s" * 32)
    assert ok.status_code == 201 and ok.json()["user"]["role"] == "ADMIN" and ok.json()["session"]["access_token"]


def test_platform_admin_approves_pending_org_admin(client):
    reg(client, organization_name="Lakeside Kitchens")
    with SessionLocal() as s:
        uid = str(s.execute(select(User.id).where(User.email == "new@example.io")).scalar_one())
    assert get(client, ADMIN, "/platform/registrations").status_code == 403  # org admins are not platform admins
    plat = "platform@foodagent.demo"
    assert [u["email"] for u in get(client, plat, "/platform/registrations").json()] == ["new@example.io"]
    assert post(client, plat, f"/platform/registrations/{uid}/approve").json()["role"] == "ADMIN"
    assert client.post(f"{API}/auth/login", json={"email": "new@example.io", "password": PW}).status_code == 200


# ---------- invitations ----------
def test_only_admin_can_manage_invitations(client):
    for who in (OPS, REC, LOGI, AUD, NGO):
        assert invite(client, who).status_code == 403
        assert get(client, who, "/invitations").status_code == 403


def test_invitation_join_assigns_role_from_backend(client):
    inv = invite(client, role="AUDITOR").json()
    assert "token" in inv and inv["status"] == "pending"
    with SessionLocal() as s:  # raw token is never stored
        row = s.execute(select(Invitation)).scalar_one()
        assert row.token_hash != inv["token"] and inv["token"] not in str(row.__dict__.values())
    assert client.get(f"{API}/auth/invitation", params={"token": inv["token"]}).json()["role"] == "AUDITOR"
    r = join(client, inv["token"])
    assert r.status_code == 201 and r.json()["user"]["role"] == "AUDITOR"
    admin_org = login(client, ADMIN)["user"]["org_id"]
    assert r.json()["user"]["org_id"] == admin_org


def test_join_cannot_override_role_or_org(client):
    inv = invite(client, role="LOGISTICS").json()
    assert join(client, inv["token"], role="ADMIN").status_code == 422
    assert join(client, inv["token"], org_id=login(client, OTHER)["user"]["org_id"]).status_code == 422


def test_invitation_is_bound_to_email_and_single_use(client):
    tok = invite(client).json()["token"]
    assert join(client, tok, email="someone-else@example.io").json()["error"]["code"] == "INVITATION_INVALID"
    assert join(client, tok).status_code == 201
    again = join(client, tok, email="invitee@example.io")
    assert again.status_code in (409, 410, 400)
    other = invite(client, email="second@example.io").json()["token"]
    assert join(client, other, email="second@example.io").status_code == 201
    assert join(client, other, email="second@example.io").status_code in (409, 410)


def test_invalid_expired_revoked_invitations(client):
    assert join(client, "x" * 40).json()["error"]["code"] == "INVITATION_INVALID"
    inv = invite(client).json()
    with SessionLocal() as s:
        row = s.get(Invitation, __import__("uuid").UUID(inv["id"]))
        assert row is not None
        row.expires_at = utcnow() - timedelta(minutes=1)
        s.commit()
    r = join(client, inv["token"])
    assert r.status_code == 410 and r.json()["error"]["code"] == "INVITATION_EXPIRED"
    inv2 = invite(client, email="rev@example.io").json()
    assert post(client, ADMIN, f"/invitations/{inv2['id']}/revoke").json()["status"] == "revoked"
    r2 = join(client, inv2["token"], email="rev@example.io")
    assert r2.status_code == 410 and r2.json()["error"]["code"] == "INVITATION_REVOKED"


def test_cross_org_admin_cannot_revoke_or_list_invitations(client):
    inv = invite(client).json()
    assert post(client, OTHER, f"/invitations/{inv['id']}/revoke").status_code == 404
    assert get(client, OTHER, "/invitations").json() == []


def test_recipient_invitation_requires_own_org_recipient(client):
    assert invite(client, role="RECIPIENT").status_code == 422
    assert invite(client, role="LOGISTICS", recipient_id="00000000-0000-0000-0000-000000000000").status_code == 422
    with SessionLocal() as s:
        foreign = s.execute(select(Recipient).where(Recipient.org_id != __import__("uuid").UUID(login(client, ADMIN)["user"]["org_id"]))).scalars().first()
    if foreign:
        assert invite(client, role="RECIPIENT", recipient_id=str(foreign.id)).status_code == 422


def test_invitation_events_are_audited(client):
    inv = invite(client).json()
    join(client, inv["token"])
    with SessionLocal() as s:
        actions = {a for (a,) in s.execute(select(AuditEvent.action)).all()}
    assert {"invitation.created", "invitation.accepted"} <= actions


# ---------- pending / disabled / role change ----------
def test_requires_approval_flow(client):
    tok = invite(client, role="OPERATIONS_MANAGER", requires_approval=True).json()["token"]
    r = join(client, tok)
    assert r.json()["status"] == "PENDING" and r.json()["session"] is None
    assert client.post(f"{API}/auth/login", json={"email": "invitee@example.io", "password": PW}).json()["error"]["code"] == "ACCOUNT_PENDING"
    uid = next(u["id"] for u in get(client, ADMIN, "/users?status=PENDING").json() if u["email"] == "invitee@example.io")
    assert post(client, OPS, f"/users/{uid}/approve", {}).status_code == 403
    assert post(client, OTHER, f"/users/{uid}/approve", {}).status_code == 404
    assert post(client, ADMIN, f"/users/{uid}/approve", {}).json()["role"] == "OPERATIONS_MANAGER"
    assert client.post(f"{API}/auth/login", json={"email": "invitee@example.io", "password": PW}).status_code == 200


def test_reject_blocks_login(client):
    tok = invite(client, requires_approval=True).json()["token"]
    join(client, tok)
    uid = next(u["id"] for u in get(client, ADMIN, "/users?status=PENDING").json())
    assert post(client, ADMIN, f"/users/{uid}/reject", {"reason": "not expected"}).json()["status"] == "REJECTED"
    assert client.post(f"{API}/auth/login", json={"email": "invitee@example.io", "password": PW}).status_code == 403


def test_pending_token_cannot_reach_protected_routes(client):
    """Even if a token existed for an account that later becomes PENDING, protected routes refuse it."""
    t = auth(client, LOGI)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.email == LOGI)).scalar_one()
        u.status, u.is_active = "PENDING", False
        s.commit()
    r = client.get(f"{API}/pickups", headers=t)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_PENDING"


def test_disabled_account_loses_access_immediately(client):
    t = auth(client, LOGI)
    uid = login(client, LOGI)["user"]["id"]
    r = client.patch(f"{API}/users/{uid}", headers=auth(client, ADMIN), json={"is_active": False, "reason": "left company"})
    assert r.status_code == 200 and r.json()["status"] == "DISABLED"
    assert client.get(f"{API}/auth/me", headers=t).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": LOGI, "password": DEMO_PASSWORD}).status_code == 403
    assert client.patch(f"{API}/users/{uid}", headers=auth(client, ADMIN), json={"is_active": True, "reason": "back"}).json()["status"] == "ACTIVE"


def test_role_change_applies_to_existing_token(client):
    t = auth(client, OPS)
    uid = login(client, OPS)["user"]["id"]
    assert client.get(f"{API}/lots", headers=t).status_code == 200
    assert client.patch(f"{API}/users/{uid}", headers=auth(client, ADMIN), json={"role": "LOGISTICS", "reason": "moved teams"}).status_code == 200
    assert client.get(f"{API}/auth/me", headers=t).json()["role"] == "LOGISTICS"  # role comes from the DB, not the stale token
    assert client.get(f"{API}/users", headers=t).status_code == 403
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": login(client, OPS)["refresh_token"]}).status_code == 200


def test_users_cannot_change_own_role_or_org(client):
    uid = login(client, OPS)["user"]["id"]
    for body in ({"role": "ADMIN", "reason": "x"}, {"org_id": "1"}):
        r = client.patch(f"{API}/users/{uid}", headers=auth(client, OPS), json=body)
        assert r.status_code in (403, 422)
    assert client.patch(f"{API}/users/{uid}", headers=auth(client, ADMIN), json={"role": "OPERATIONS_MANAGER", "org_id": "x"}).status_code == 422
    assert client.patch(f"{API}/users/{login(client, ADMIN)['user']['id']}", headers=auth(client, ADMIN), json={"role": "AUDITOR", "reason": "self"}).status_code == 422


def test_last_admin_protected(client):
    other_admin = login(client, OTHER)["user"]["id"]
    r = client.patch(f"{API}/users/{other_admin}", headers=auth(client, ADMIN), json={"is_active": False, "reason": "x"})
    assert r.status_code == 404  # different org: invisible
    tok = invite(client, role="ADMIN").json()["token"]
    join(client, tok)
    me = login(client, ADMIN)["user"]["id"]
    new_admin = login(client, "invitee@example.io", PW)["user"]["id"]
    assert client.patch(f"{API}/users/{new_admin}", headers=auth(client, ADMIN), json={"is_active": False, "reason": "ok"}).status_code == 200
    assert client.patch(f"{API}/users/{me}", headers=auth(client, ADMIN), json={"is_active": False, "reason": "x"}).status_code == 422  # no self-lockout
    # a platform administrator cannot strip an organization of its only active admin either
    r2 = client.patch(f"{API}/users/{other_admin}", headers=auth(client, "platform@foodagent.demo"), json={"is_active": False, "reason": "x"})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "LAST_ADMIN"


def test_user_changes_are_audited_with_before_after(client):
    uid = login(client, AUD)["user"]["id"]
    client.patch(f"{API}/users/{uid}", headers=auth(client, ADMIN), json={"role": "RECOVERY_MANAGER", "reason": "promotion"})
    with SessionLocal() as s:
        ev = s.execute(select(AuditEvent).where(AuditEvent.action == "user.role_changed")).scalars().first()
        assert ev and ev.meta["before"]["role"] == "AUDITOR" and ev.meta["after"]["role"] == "RECOVERY_MANAGER"


# ---------- isolation / read-only ----------
def test_cross_org_user_list_and_lot_access(client):
    emails = {u["email"] for u in get(client, OTHER, "/users").json()}
    assert emails == {"admin@sahyadribev.demo"}
    lot = get(client, OPS, "/lots").json()["items"][0]
    assert get(client, OTHER, f"/lots/{lot['id']}").status_code in (403, 404)
    assert get(client, OTHER, "/lots").json()["total"] != get(client, OPS, "/lots").json()["total"]


def test_recipient_cannot_use_staff_or_admin_endpoints(client):
    for path in ("/users", "/invitations", "/lots", "/recovery-cases", "/audit", "/pickups"):
        assert get(client, NGO, path).status_code == 403, path
    assert post(client, NGO, "/invitations", {"email": "a@b.io", "role": "ADMIN"}).status_code == 403


def test_auditor_cannot_write(client):
    uid = login(client, OPS)["user"]["id"]
    assert post(client, AUD, "/lots", {}).status_code == 403
    assert post(client, AUD, "/users", {"email": "z@z.io", "full_name": "Z Z", "password": PW, "role": "ADMIN"}).status_code == 403
    assert client.patch(f"{API}/users/{uid}", headers=auth(client, AUD), json={"role": "ADMIN", "reason": "x"}).status_code == 403
    assert post(client, AUD, "/invitations", {"email": "a@b.io", "role": "ADMIN"}).status_code == 403


# ---------- demo shortcuts ----------
def test_demo_accounts_endpoint_only_outside_production(client, monkeypatch):
    r = client.get(f"{API}/auth/demo-accounts")
    assert r.status_code == 200 and any(a["email"] == ADMIN for a in r.json()["accounts"])
    monkeypatch.setattr(auth_api.settings, "environment", "production")
    assert client.get(f"{API}/auth/demo-accounts").status_code == 404
