import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.models import EventOutbox, Notification, User


def publish(db: Session, org_id: uuid.UUID | None, type_: str, payload: dict | None = None, recipient_id=None) -> None:
    db.add(EventOutbox(org_id=org_id, type=type_, payload=payload or {}, recipient_id=recipient_id, created_at=utcnow()))


def notify_roles(
    db: Session, org_id: uuid.UUID, roles: list[str], type_: str, title: str, body: str = "",
    severity: str = "info", resource_type: str | None = None, resource_id=None,
) -> None:
    users = db.execute(
        select(User).where(User.org_id == org_id, User.role.in_(roles), User.is_active.is_(True))
    ).scalars().all()
    for u in users:
        add_notification(db, u, org_id, type_, title, body, severity, resource_type, resource_id)


def notify_recipient_users(db: Session, recipient_id, type_: str, title: str, body: str = "", resource_type=None, resource_id=None):
    users = db.execute(select(User).where(User.recipient_id == recipient_id, User.is_active.is_(True))).scalars().all()
    for u in users:
        add_notification(db, u, u.org_id, type_, title, body, "info", resource_type, resource_id)


def add_notification(db, user, org_id, type_, title, body="", severity="info", resource_type=None, resource_id=None):
    n = Notification(
        org_id=org_id, user_id=user.id, type=type_, title=title, body=body, severity=severity,
        resource_type=resource_type, resource_id=str(resource_id) if resource_id else None,
    )
    db.add(n)
    publish(db, org_id, "notification.created", {"user_id": str(user.id), "type": type_, "severity": severity, "title": title})
