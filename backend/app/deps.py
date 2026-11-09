from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, Role, User, utcnow
from .security import decode_token, hash_api_key

_RANK = {Role.OPERATOR: 1, Role.SUPERVISOR: 2, Role.ADMIN: 3}


def _api_key_user(db: Session, key: str) -> User:
    rec = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(key)))
    if rec is None or not rec.active or not rec.user.active:
        raise HTTPException(401, "Invalid or revoked API key")
    rec.last_used_at = utcnow()
    return rec.user


def current_user(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> User:
    """Accepts a login token (`Authorization: Bearer <token>`) or an API key
    (`X-API-Key: wms_...` or `Authorization: Bearer wms_...`)."""
    if x_api_key:
        return _api_key_user(db, x_api_key)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    if token.startswith("wms_"):
        return _api_key_user(db, token)
    username = decode_token(token)
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
