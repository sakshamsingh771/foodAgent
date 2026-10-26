"""Invitations, approval of pending accounts and platform approval of new organizations. All writes are audited."""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update

from app.api.auth import invitation_state
from app.api.deps import DB, CurrentUser, require
from app.api.serializers import iso, user_out
from app.core import security as sec
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import Invitation, RefreshToken, Recipient, User
from app.schemas import DecisionIn, InvitationCreateIn
from app.services import audit

router = APIRouter(tags=["users"])
settings = get_settings()


def _need_org(user: User):
    if user.org_id is None:
        raise AppError("This action must be performed within an organization.", "ORG_REQUIRED", 422)
    return user.org_id


def _inv_out(i: Invitation, token: str | None = None) -> dict:
    out = {"id": str(i.id), "email": i.email, "role": i.role, "recipient_id": str(i.recipient_id) if i.recipient_id else None,
           "status": invitation_state(i), "expires_at": iso(i.expires_at), "max_uses": i.max_uses, "use_count": i.use_count,
           "requires_approval": i.requires_approval, "created_at": iso(i.created_at), "revoked_at": iso(i.revoked_at)}
    if token:  # shown exactly once, at creation; only the hash is stored
        out["token"] = token
        out["invite_url"] = f"{settings.app_url.rstrip('/')}/register?invite={token}"
    return out


@router.post("/invitations", status_code=201)
def create_invitation(body: InvitationCreateIn, db: DB, user: User = Depends(require("users:manage"))):
    org_id = _need_org(user)
    if db.execute(select(User.id).where(User.email == body.email)).first():
        raise Conflict("An account with this email already exists.", "EMAIL_TAKEN")
    now = utcnow()
    for old in db.execute(select(Invitation).where(Invitation.org_id == org_id, Invitation.email == body.email)).scalars():
        if invitation_state(old, now) == "pending":
            raise Conflict("A pending invitation already exists for this email. Revoke it first.", "INVITATION_EXISTS")
    recipient_id = None
    if body.role == sec.RECIPIENT:
        rec = db.get(Recipient, body.recipient_id) if body.recipient_id else None
        if rec is None or rec.org_id != org_id:  # the recipient record must belong to the inviting organization
            raise AppError("Choose a recipient from your organization for a recipient invitation.", "RECIPIENT_REQUIRED", 422)
        recipient_id = rec.id
    elif body.recipient_id is not None:
        raise AppError("Only recipient invitations can be linked to a recipient.", "RECIPIENT_NOT_ALLOWED", 422)
    raw = sec.new_invite_token()
    inv = Invitation(org_id=org_id, email=body.email, role=body.role, recipient_id=recipient_id, token_hash=sec.token_digest(raw),
                     expires_at=now + timedelta(days=body.expires_in_days), max_uses=body.max_uses, requires_approval=body.requires_approval,
                     created_by=user.id)
    db.add(inv)
    db.flush()
    audit.record(db, org_id, user, "invitation.created", "invitation", inv.id, f"{user.full_name} invited {inv.email} as {inv.role}",
                 {"email": inv.email, "role": inv.role, "expires_at": iso(inv.expires_at), "requires_approval": inv.requires_approval})
    db.commit()
    return _inv_out(inv, raw)


@router.get("/invitations")
def list_invitations(db: DB, user: User = Depends(require("users:manage"))):
    org_id = _need_org(user)
    rows = db.execute(select(Invitation).where(Invitation.org_id == org_id).order_by(Invitation.created_at.desc()).limit(200)).scalars().all()
    return [_inv_out(i) for i in rows]


@router.post("/invitations/{inv_id}/revoke")
def revoke_invitation(inv_id: uuid.UUID, db: DB, user: User = Depends(require("users:manage"))):
    org_id = _need_org(user)
    inv = db.get(Invitation, inv_id)
    if inv is None or inv.org_id != org_id:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    if inv.revoked_at is None and inv.use_count < inv.max_uses:
        inv.revoked_at = utcnow()
        audit.record(db, org_id, user, "invitation.revoked", "invitation", inv.id, f"{user.full_name} revoked the invitation for {inv.email}",
                     {"email": inv.email, "role": inv.role})
        db.commit()
    return _inv_out(inv)


def _decide(db, actor: User, target: User, approve: bool, body: DecisionIn, org_id) -> dict:
    if target.status != sec.PENDING:
        raise Conflict("This account is not waiting for a decision.", "NOT_PENDING")
    before = {"status": target.status, "role": target.role}
    if approve:
        role = body.role or target.requested_role
        if role not in sec.ROLES or role == sec.RECIPIENT and target.recipient_id is None:
            raise AppError("Choose a valid role for this account.", "ROLE_REQUIRED", 422)
        target.role = role
        sec.set_status(target, sec.ACTIVE)
    else:
        sec.set_status(target, sec.REJECTED)
    target.decided_by, target.decided_at, target.decision_note = actor.id, utcnow(), (body.reason or "").strip() or None
    db.execute(update(RefreshToken).where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit.record(db, org_id, actor, "user.approved" if approve else "user.rejected", "user", target.id,
                 f"{actor.full_name} {'approved' if approve else 'rejected'} {target.full_name}" + (f" as {target.role}" if approve else ""),
                 {"before": before, "after": {"status": target.status, "role": target.role}, "reason": target.decision_note})
    db.commit()
    return user_out(target)


def _org_target(db, user: User, user_id: uuid.UUID) -> User:
    org_id = _need_org(user)
    target = db.get(User, user_id)
    if target is None or target.org_id != org_id or target.is_platform_admin:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    if target.id == user.id:
        raise AppError("You can't approve or reject your own account.", "SELF_CHANGE_FORBIDDEN", 422)
    return target


@router.post("/users/{user_id}/approve")
def approve_user(user_id: uuid.UUID, body: DecisionIn, db: DB, user: User = Depends(require("users:manage"))):
    target = _org_target(db, user, user_id)
    return _decide(db, user, target, True, body, user.org_id)


@router.post("/users/{user_id}/reject")
def reject_user(user_id: uuid.UUID, body: DecisionIn, db: DB, user: User = Depends(require("users:manage"))):
    target = _org_target(db, user, user_id)
    return _decide(db, user, target, False, body, user.org_id)


# ---- Platform administrators approve brand-new organizations' first administrator ----------
def platform_admin(user: CurrentUser) -> User:
    if not user.is_platform_admin:
        raise Forbidden("Platform administrator access is required.", "FORBIDDEN_ROLE")
    return user


@router.get("/platform/registrations", tags=["platform"])
def platform_registrations(db: DB, user: User = Depends(platform_admin)):
    rows = db.execute(select(User).where(User.status == sec.PENDING, User.requested_role == sec.ADMIN, User.recipient_id.is_(None))
                      .order_by(User.created_at)).scalars().all()
    return [user_out(u) for u in rows]


def _platform_target(db, user: User, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None or target.org_id is None or target.is_platform_admin:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    return target


@router.post("/platform/registrations/{user_id}/approve", tags=["platform"])
def platform_approve(user_id: uuid.UUID, db: DB, user: User = Depends(platform_admin)):
    t = _platform_target(db, user, user_id)
    return _decide(db, user, t, True, DecisionIn(role=sec.ADMIN), t.org_id)


@router.post("/platform/registrations/{user_id}/reject", tags=["platform"])
def platform_reject(user_id: uuid.UUID, body: DecisionIn, db: DB, user: User = Depends(platform_admin)):
    t = _platform_target(db, user, user_id)
    return _decide(db, user, t, False, body, t.org_id)
