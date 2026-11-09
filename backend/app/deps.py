from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User
from .security import decode_token

_RANK = {Role.OPERATOR: 1, Role.SUPERVISOR: 2, Role.ADMIN: 3}


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    username = decode_token(authorization.split(" ", 1)[1])
    user = db.scalar(select(User).where(User.username == username)) if username else None
    if not user or not user.active:
        raise HTTPException(401, "Invalid or expired session")
    return user


def require_role(minimum: Role) -> Callable[..., User]:
    def checker(user: User = Depends(current_user)) -> User:
        if _RANK.get(Role(user.role), 0) < _RANK[minimum]:
            raise HTTPException(403, f"Requires {minimum.value} role")
        return user

    return checker
