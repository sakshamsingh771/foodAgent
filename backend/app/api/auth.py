import hmac
import logging
import re
import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.serializers import user_out
from app.core import security as sec
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from app.core.logging import log_event
from app.models import Invitation, Organization, RefreshToken, Recipient, User
from app.schemas import LoginIn, RefreshIn, RegisterIn
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("foodagent.auth")
settings = get_settings()
_attempts: dict[str, deque] = defaultdict(deque)
_failures: dict[str, deque] = defaultdict(deque)

DEMO_ACCOUNTS = [
    ("admin@verdanafoods.demo", "Admin"), ("ops@verdanafoods.demo", "Operations manager"),
    ("recovery@verdanafoods.demo", "Recovery manager"), ("logistics@verdanafoods.demo", "Logistics"),
    ("auditor@verdanafoods.demo", "Auditor"), ("recipient@annapurna.demo", "Recipient"),
    ("admin@sahyadribev.demo", "Other organization (Sahyadri) admin"),
]


def _rate_limit(key: str, limit: int | None = None) -> None:
    """Sliding-window limiter (per process). Use a shared store such as Redis/an API gateway when running multiple replicas."""
    now, window = time.time(), _attempts[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= (limit or settings.rate_limit_login_per_minute):
        raise AppError("Too many attempts. Please wait a minute and try again.", "RATE_LIMITED", 429)
    window.append(now)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _locked(email: str) -> bool:
    now, window = time.time(), _failures[email]
    while window and now - window[0] > settings.failed_login_window_minutes * 60:
        window.popleft()
    return len(window) >= settings.max_failed_logins


def _issue(db, user: User) -> dict:
    refresh, jti, exp = sec.create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=sec.token_digest(jti), expires_at=exp))
    return {"access_token": sec.create_access_token(user.id, user.role, user.org_id), "refresh_token": refresh,
            "token_type": "bearer", "expires_in": settings.access_token_minutes * 60, "user": user_out(user)}


def invitation_state(inv: Invitation, now=None) -> str:
    now = now or utcnow()
    if inv.revoked_at:
        return "revoked"
    if inv.use_count >= inv.max_uses:
        return "used"
    if inv.expires_at <= now:
        return "expired"
    return "pending"


def load_invitation(db, raw_token: str, email: str | None = None, lock: bool = False) -> Invitation:
    """Resolve and validate an invitation token. Raises a precise error for expired/revoked/used invitations."""
    q = select(Invitation).where(Invitation.token_hash == sec.token_digest(raw_token))
    inv = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if inv is None or (email is not None and inv.email != email):
        raise AppError("This invitation isn't valid for this email address.", "INVITATION_INVALID", 400)
    state = invitation_state(inv)
    if state == "revoked":
        raise AppError("This invitation has been revoked. Ask your administrator for a new one.", "INVITATION_REVOKED", 410)
    if state == "expired":
        raise AppError("This invitation has expired. Ask your administrator for a new one.", "INVITATION_EXPIRED", 410)
    if state == "used":
        raise AppError("This invitation has already been used.", "INVITATION_USED", 410)
    return inv


@router.get("/invitation")
def invitation_lookup(token: str, db: DB, request: Request):
    """Public: lets the registration page show which organization/role a valid invitation is for."""
    _rate_limit(f"inv:{_client_ip(request)}", 20)
    inv = load_invitation(db, token)
    org = db.get(Organization, inv.org_id)
    return {"organization_name": org.name if org else "", "role": inv.role, "email": inv.email,
            "requires_approval": inv.requires_approval, "expires_at": inv.expires_at.isoformat()}


@router.get("/demo-accounts")
def demo_accounts(db: DB):
    """Development/demo convenience only. 404 in production; quick-login still goes through POST /auth/login."""
    if not settings.demo_enabled:
        raise NotFound("Not found.", "NOT_FOUND")
    from app.seed import DEMO_PASSWORD
    existing = set(db.execute(select(User.email).where(User.email.in_([e for e, _ in DEMO_ACCOUNTS]))).scalars())
    return {"password": DEMO_PASSWORD, "accounts": [{"email": e, "label": label} for e, label in DEMO_ACCOUNTS if e in existing]}


def _pending_response(user: User, message: str) -> dict:
    return {"status": user.status, "message": message, "session": None, "user": None}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: DB, request: Request):
    """Public registration. The client never chooses a role or organization:
    - mode=join: role and organization come from a valid invitation row (email-bound, expiring, single-use).
    - mode=create_org: creates the organization; the creator is NOT an admin until a protected setup token is presented
      or a platform administrator approves the request."""
    _rate_limit(f"reg:{_client_ip(request)}", settings.rate_limit_register_per_minute)
    problem = sec.validate_password_strength(body.password)
    if problem:
        raise AppError(problem, "WEAK_PASSWORD", 422)
    if db.execute(select(User.id).where(User.email == body.email)).first():
        raise Conflict("An account with this email already exists.", "EMAIL_TAKEN")
    now = utcnow()
    if body.mode == "join":
        inv = load_invitation(db, body.invite_token or "", body.email, lock=True)
        if inv.role == sec.RECIPIENT:
            rec = db.get(Recipient, inv.recipient_id) if inv.recipient_id else None
            if rec is None or rec.org_id != inv.org_id:
                raise AppError("This invitation is no longer valid.", "INVITATION_INVALID", 400)
        user = User(email=body.email, full_name=body.full_name.strip(), password_hash=sec.hash_password(body.password),
                    role=inv.role, org_id=inv.org_id, recipient_id=inv.recipient_id, created_by=inv.created_by)
        if inv.requires_approval:
            user.role, user.requested_role = sec.PENDING_ROLE, inv.role
            sec.set_status(user, sec.PENDING)
        else:
            sec.set_status(user, sec.ACTIVE)
        db.add(user)
        db.flush()
        inv.use_count += 1
        inv.last_used_by = user.id
        audit.record(db, inv.org_id, user, "invitation.accepted", "invitation", inv.id,
                     f"{user.full_name} accepted an invitation as {inv.role}", {"role": inv.role, "pending": inv.requires_approval})
        audit.record(db, inv.org_id, user, "auth.registered", "user", user.id, f"{user.full_name} joined the organization")
        if user.status == sec.PENDING:
            db.commit()
            return _pending_response(user, "Your account has been created and is waiting for an administrator to approve it.")
        out = _issue(db, user)
        db.commit()
        log_event(log, "user joined", user_id=str(user.id))
        return {"status": sec.ACTIVE, "message": "Welcome aboard.", "session": out, "user": out["user"]}

    # create_org
    organization_name = body.organization_name or ""
    slug = re.sub(r"[^a-z0-9]+", "-", organization_name.lower()).strip("-")[:60] + "-" + uuid.uuid4().hex[:5]
    org = Organization(name=organization_name.strip(), slug=slug, type="MANUFACTURER")
    db.add(org)
    db.flush()
    setup_ok = bool(settings.first_admin_setup_token) and bool(body.setup_token) and hmac.compare_digest(
        body.setup_token.encode(), settings.first_admin_setup_token.encode())
    if body.setup_token and not setup_ok:
        raise Forbidden("That setup code isn't valid.", "SETUP_TOKEN_INVALID")
    user = User(email=body.email, full_name=body.full_name.strip(), password_hash=sec.hash_password(body.password),
                role=sec.ADMIN if setup_ok else sec.PENDING_ROLE, org_id=org.id, requested_role=None if setup_ok else sec.ADMIN)
    sec.set_status(user, sec.ACTIVE if setup_ok else sec.PENDING)
    db.add(user)
    db.flush()
    audit.record(db, org.id, user, "auth.registered", "user", user.id,
                 f"{user.full_name} created the organization " + ("(first admin via setup code)" if setup_ok else "(awaiting platform approval)"))
    if not setup_ok:
        db.commit()
        log_event(log, "org registration pending", user_id=str(user.id))
        return _pending_response(user, "Your organization has been created. A platform administrator must approve your administrator "
                                       "access before you can sign in. You'll be able to sign in once it's approved.")
    out = _issue(db, user)
    db.commit()
    return {"status": sec.ACTIVE, "message": "Your organization is ready.", "session": out, "user": out["user"]}


@router.post("/login")
def login(body: LoginIn, db: DB, request: Request):
    _rate_limit(f"{_client_ip(request)}:{body.email}")
    if _locked(body.email):
        raise AppError("Too many failed sign-in attempts. Please try again later.", "ACCOUNT_LOCKED_TEMPORARILY", 429)
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    # always run a hash check so response time doesn't reveal whether the email exists
    ok = sec.verify_password(body.password, user.password_hash if user else "$2b$12$" + "x" * 53)
    if not user or not ok:
        _failures[body.email].append(time.time())
        log_event(log, "login failed", email_hash=sec.token_digest(body.email)[:12])
        raise Unauthorized("That email and password don't match.", "INVALID_CREDENTIALS")
    _failures.pop(body.email, None)
    if user.status == sec.PENDING:
        raise Forbidden("Your account is awaiting approval. You'll be able to sign in once an administrator approves it.", "ACCOUNT_PENDING")
    if user.status != sec.ACTIVE or not user.is_active:
        raise Forbidden("This account is not active. Contact your organization's administrator.", "ACCOUNT_DISABLED")
    user.last_login_at = utcnow()
    out = _issue(db, user)
    if user.org_id:
        audit.record(db, user.org_id, user, "auth.login", "user", user.id, f"{user.full_name} signed in")
    db.commit()
    log_event(log, "login ok", user_id=str(user.id))
    return out


@router.post("/refresh")
def refresh(body: RefreshIn, db: DB):
    data = sec.decode_refresh(body.refresh_token)
    row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == sec.token_digest(data["jti"]))).scalar_one_or_none()
    if not row or row.revoked_at or row.expires_at < utcnow():
        raise Unauthorized("Your session has expired. Please sign in again.", "REFRESH_INVALID")
    user = db.get(User, row.user_id)
    if not user or not user.is_active or user.status != sec.ACTIVE:
        raise Unauthorized("This account is no longer active.", "ACCOUNT_INACTIVE")
    row.revoked_at = utcnow()  # rotate: each refresh token works once
    out = _issue(db, user)
    db.commit()
    return out


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: DB):
    try:
        data = sec.decode_refresh(body.refresh_token)
    except Unauthorized:
        return None
    row = db.execute(select(RefreshToken).where(RefreshToken.token_hash == sec.token_digest(data["jti"]))).scalar_one_or_none()
    if row and not row.revoked_at:
        row.revoked_at = utcnow()
        db.commit()
    return None


@router.get("/me")
def me(user: CurrentUser):
    return user_out(user)
