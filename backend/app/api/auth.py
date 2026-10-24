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
from app.core.errors import AppError, Conflict, Unauthorized
from app.core.logging import log_event
from app.models import Organization, RefreshToken, User
from app.schemas import LoginIn, RefreshIn, RegisterIn
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("foodagent.auth")
settings = get_settings()
_attempts: dict[str, deque] = defaultdict(deque)


def _rate_limit(key: str) -> None:
    """Sliding-window limiter (per process). Use a shared store such as Redis when running multiple replicas."""
    now, window = time.time(), _attempts[key]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_login_per_minute:
        raise AppError("Too many attempts. Please wait a minute and try again.", "RATE_LIMITED", 429)
    window.append(now)


def _issue(db, user: User) -> dict:
    refresh, jti, exp = sec.create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=sec.token_digest(jti), expires_at=exp))
    return {"access_token": sec.create_access_token(user.id, user.role, user.org_id), "refresh_token": refresh,
            "token_type": "bearer", "expires_in": settings.access_token_minutes * 60, "user": user_out(user)}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: DB):
    """Self-service sign-up creates a new organization and its first ADMIN."""
    problem = sec.validate_password_strength(body.password)
    if problem:
        raise AppError(problem, "WEAK_PASSWORD", 422)
    if db.execute(select(User.id).where(User.email == body.email)).first():
        raise Conflict("An account with this email already exists.", "EMAIL_TAKEN")
    slug = re.sub(r"[^a-z0-9]+", "-", body.organization_name.lower()).strip("-")[:60] + "-" + uuid.uuid4().hex[:5]
    org = Organization(name=body.organization_name.strip(), slug=slug, type="MANUFACTURER")
    db.add(org)
    db.flush()
    user = User(email=body.email, full_name=body.full_name.strip(), password_hash=sec.hash_password(body.password), role=sec.ADMIN, org_id=org.id)
    db.add(user)
    db.flush()
    audit.record(db, org.id, user, "auth.registered", "user", user.id, f"{user.full_name} created the organization")
    out = _issue(db, user)
    db.commit()
    log_event(log, "user registered", user_id=str(user.id))
    return out


@router.post("/login")
def login(body: LoginIn, db: DB, request: Request):
    _rate_limit(f"{request.client.host if request.client else '?'}:{body.email}")
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    # always run a hash check so response time doesn't reveal whether the email exists
    ok = sec.verify_password(body.password, user.password_hash if user else "$2b$12$" + "x" * 53)
    if not user or not ok or not user.is_active:
        log_event(log, "login failed", email_hash=sec.token_digest(body.email)[:12])
        raise Unauthorized("That email and password don't match.", "INVALID_CREDENTIALS")
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
    if not user or not user.is_active:
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
