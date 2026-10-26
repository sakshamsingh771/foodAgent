import uuid
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import security as sec
from app.core.database import get_db
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.models import User

bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if creds is None:
        raise Unauthorized("Please sign in to continue.", "NOT_AUTHENTICATED")
    data = sec.decode_access(creds.credentials)
    try:
        user_id = uuid.UUID(data["sub"])
    except (KeyError, TypeError, ValueError):
        raise Unauthorized("We couldn't verify your session. Please sign in again.", "TOKEN_INVALID") from None
    user = db.get(User, user_id)
    if not user:
        raise Unauthorized("This account is no longer active.", "ACCOUNT_INACTIVE")
    if user.status == sec.PENDING:
        raise Forbidden("Your account is awaiting approval.", "ACCOUNT_PENDING")
    if user.status != sec.ACTIVE or not user.is_active:
        raise Unauthorized("This account is no longer active.", "ACCOUNT_INACTIVE")
    # NOTE: role/org always come from the database row, never from the token claims, so a role change
    # or deactivation takes effect on the very next request even with an unexpired access token.
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require(*perms: str):
    """Backend permission check: the user's role must grant at least one listed permission."""
    def dep(user: CurrentUser) -> User:
        granted = sec.ROLE_PERMS.get(user.role, set())
        if not any(p in granted for p in perms):
            raise Forbidden("Your role doesn't have access to this action.", "FORBIDDEN_ROLE")
        return user
    return dep


def ensure_org(user: User, org_id: uuid.UUID | None) -> None:
    """Organization boundary. Platform admins may cross it; everyone else may not."""
    if user.is_platform_admin:
        return
    if org_id is None or org_id != user.org_id:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")  # 404, not 403: don't leak existence


def get_owned(db: Session, model, id_: uuid.UUID, user: User):
    obj = db.get(model, id_)
    if obj is None:
        raise NotFound("We couldn't find that record.", "NOT_FOUND")
    ensure_org(user, getattr(obj, "org_id", None))
    return obj


class Page:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        self.page, self.page_size = page, page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paged(items: list, total: int, p: Page) -> dict:
    return {"items": items, "total": total, "page": p.page, "page_size": p.page_size,
            "pages": max(1, -(-total // p.page_size))}
