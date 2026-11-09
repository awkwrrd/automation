from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user, require_role
from ..models import Role, User
from ..schemas import LoginIn, LoginOut, UserIn, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(tags=["auth & users"])


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password")
    return LoginOut(token=create_token(user.username), user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/meta")
def meta():
    """Public metadata the UI needs (enums, app name)."""
    from ..models import (ORDER_CATEGORIES, UNIT_TYPES, InboundType, InventoryStatus, LocationType,
                          OrderStatus, TaskStatus, TaskType, TxnType, ZoneType)
    return {
        "app_name": settings.app_name,
        "roles": [r.value for r in Role],
        "zone_types": [z.value for z in ZoneType],
        "location_types": [z.value for z in LocationType],
        "inventory_statuses": [z.value for z in InventoryStatus],
        "order_statuses": [z.value for z in OrderStatus],
        "task_types": [z.value for z in TaskType],
        "task_statuses": [z.value for z in TaskStatus],
        "txn_types": [z.value for z in TxnType],
        "inbound_types": [z.value for z in InboundType],
        "unit_types": UNIT_TYPES,
        "order_categories": ORDER_CATEGORIES,
        "adjust_reasons": ["DAMAGED", "FOUND", "LOST", "EXPIRED", "SAMPLE", "RETURN", "DATA_CORRECTION", "OTHER"],
    }


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _=Depends(require_role(Role.SUPERVISOR))):
    return db.scalars(select(User).order_by(User.username)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), _=Depends(require_role(Role.ADMIN))):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Username already exists")
    if not body.password:
        raise HTTPException(422, "Password is required")
    user = User(**body.model_dump(exclude={"password"}), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserIn, db: Session = Depends(get_db),
                actor: User = Depends(require_role(Role.ADMIN))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == actor.id and (not body.active or body.role != Role.ADMIN):
        raise HTTPException(400, "You cannot deactivate or demote yourself")
    for k, v in body.model_dump(exclude={"password"}).items():
        setattr(user, k, v)
    if body.password:
        user.password_hash = hash_password(body.password)
    return user
