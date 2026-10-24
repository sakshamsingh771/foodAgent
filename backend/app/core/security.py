import hashlib
import re
import secrets
import uuid
from datetime import timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import Unauthorized

settings = get_settings()
ALGO = "HS256"

ADMIN = "ADMIN"
OPS = "OPERATIONS_MANAGER"
RECOVERY = "RECOVERY_MANAGER"
RECIPIENT = "RECIPIENT"
LOGISTICS = "LOGISTICS"
AUDITOR = "AUDITOR"
ROLES = [ADMIN, OPS, RECOVERY, RECIPIENT, LOGISTICS, AUDITOR]

_READ_ALL = {
    "lots:read", "cases:read", "recipients:read", "pickups:read", "plant:read", "planning:read",
    "sustainability:read", "compliance:read", "audit:read", "scenarios:read", "dashboard:read",
    "evidence:read", "simulate",
}
ROLE_PERMS: dict[str, set[str]] = {
    ADMIN: _READ_ALL | {
        "lots:write", "cases:create", "cases:approve", "cases:close", "evidence:write",
        "pickups:write", "compliance:write", "scenarios:run", "users:manage",
    },
    OPS: (_READ_ALL - {"audit:read"}) | {
        "lots:write", "cases:create", "evidence:write", "pickups:write", "scenarios:run", "compliance:write",
    },
    RECOVERY: _READ_ALL | {"cases:create", "cases:approve", "cases:close", "evidence:write", "pickups:write"},
    AUDITOR: set(_READ_ALL),
    LOGISTICS: {"pickups:read", "pickups:write", "cases:read", "lots:read", "evidence:read", "dashboard:read"},
    RECIPIENT: {"recipient:inbox", "recipient:respond", "pickups:handover_own"},
}


def validate_password_strength(pw: str) -> str | None:
    if len(pw) < 10:
        return "Password must be at least 10 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password must include letters and numbers."
    return None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, role: str, org_id: uuid.UUID | None) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id), "role": role, "org": str(org_id) if org_id else None,
        "type": "access", "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def create_refresh_token(user_id: uuid.UUID):
    now = utcnow()
    jti = secrets.token_hex(16)
    exp = now + timedelta(days=settings.refresh_token_days)
    token = jwt.encode(
        {"sub": str(user_id), "jti": jti, "type": "refresh", "iat": now, "exp": exp},
        settings.jwt_refresh_secret, algorithm=ALGO,
    )
    return token, jti, exp


def decode_access(token: str) -> dict:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Your session has expired. Please sign in again.", "TOKEN_EXPIRED")
    except jwt.PyJWTError:
        raise Unauthorized("We couldn't verify your session. Please sign in again.", "TOKEN_INVALID")
    if data.get("type") != "access":
        raise Unauthorized("Invalid token type.", "TOKEN_INVALID")
    return data


def decode_refresh(token: str) -> dict:
    try:
        data = jwt.decode(token, settings.jwt_refresh_secret, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise Unauthorized("Your session has expired. Please sign in again.", "REFRESH_INVALID")
    if data.get("type") != "refresh":
        raise Unauthorized("Invalid token type.", "REFRESH_INVALID")
    return data


def token_digest(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()
