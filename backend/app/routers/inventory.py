from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user, require_role
from ..models import InventoryBalance, InventoryTransaction, Item, Location, Role, User, Zone
from ..schemas import AdjustIn, BalanceOut, MoveIn, Page, StatusChangeIn, TxnOut
from ..services import inventory as svc
from ._util import like, paginate

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/balances", response_model=Page[BalanceOut], dependencies=[Depends(current_user)])
def balances(warehouse_id: int | None = None, item_id: int | None = None, location_id: int | None = None,
             zone_id: int | None = None, status: str | None = None, q: str | None = None,
             location: str | None = None, lot: str | None = None, limit: int = 100, offset: int = 0,
             db: Session = Depends(get_db)):
    stmt = (select(InventoryBalance, Zone.code)
            .join(Item, Item.id == InventoryBalance.item_id)
            .join(Location, Location.id == InventoryBalance.location_id)
            .outerjoin(Zone, Zone.id == Location.zone_id)
            .options(joinedload(InventoryBalance.item), joinedload(InventoryBalance.location))
            .where(InventoryBalance.qty_on_hand != 0)
            .order_by(Item.sku, Location.pick_sequence, Location.code))
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if item_id:
        stmt = stmt.where(InventoryBalance.item_id == item_id)
    if location_id:
        stmt = stmt.where(InventoryBalance.location_id == location_id)
    if zone_id:
        stmt = stmt.where(Location.zone_id == zone_id)
    if status:
        stmt = stmt.where(InventoryBalance.status == status)
    if lot:
        stmt = stmt.where(InventoryBalance.lot_number.ilike(like(lot)))
    if location:
        stmt = stmt.where(Location.code.ilike(like(location)))
    if q:
        t = like(q)
        stmt = stmt.where(or_(Item.sku.ilike(t), Item.name.ilike(t), Item.barcode.ilike(t)))
    rows, total = paginate(db, stmt, limit, offset)
    out = []
    for bal, zone_code in rows:
        b = BalanceOut.model_validate({
            **{k: getattr(bal, k) for k in ("id", "item", "location", "lot_number", "expiration_date", "status",
                                            "qty_on_hand", "qty_allocated", "qty_available", "updated_at")},
            "warehouse_id": bal.location.warehouse_id, "zone_code": zone_code,
        })
        out.append(b)
    return Page(items=out, total=total)


@router.post("/adjust")
def adjust(body: AdjustIn, db: Session = Depends(get_db), user: User = Depends(require_role(Role.SUPERVISOR))):
    svc.adjust(db, item_id=body.item_id, location_id=body.location_id, qty_delta=body.qty,
               reason_code=body.reason_code, username=user.username, lot=body.lot_number, status=body.status,
               expiration_date=body.expiration_date, notes=body.notes)
    return {"ok": True}


@router.post("/move")
def move(body: MoveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    svc.move(db, item_id=body.item_id, from_location_id=body.from_location_id,
             to_location_id=body.to_location_id, qty=body.qty, username=user.username,
             lot=body.lot_number, status=body.status, notes=body.notes)
    return {"ok": True}


@router.post("/status")
def change_status(body: StatusChangeIn, db: Session = Depends(get_db),
                  user: User = Depends(require_role(Role.SUPERVISOR))):
    svc.change_status(db, item_id=body.item_id, location_id=body.location_id, qty=body.qty,
                      from_status=body.from_status, to_status=body.to_status, username=user.username,
                      lot=body.lot_number, reason_code=body.reason_code, notes=body.notes)
    return {"ok": True}


@router.get("/transactions", response_model=Page[TxnOut], dependencies=[Depends(current_user)])
def transactions(item_id: int | None = None, location_id: int | None = None, txn_type: str | None = None,
                 q: str | None = None, reference: str | None = None, username: str | None = None,
                 date_from: datetime | None = None, date_to: datetime | None = None,
                 limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    stmt = (select(InventoryTransaction).join(Item, Item.id == InventoryTransaction.item_id)
            .options(joinedload(InventoryTransaction.item), joinedload(InventoryTransaction.from_location),
                     joinedload(InventoryTransaction.to_location))
            .order_by(InventoryTransaction.id.desc()))
    if item_id:
        stmt = stmt.where(InventoryTransaction.item_id == item_id)
    if location_id:
        stmt = stmt.where(or_(InventoryTransaction.from_location_id == location_id,
                              InventoryTransaction.to_location_id == location_id))
    if txn_type:
        stmt = stmt.where(InventoryTransaction.txn_type == txn_type)
    if reference:
        stmt = stmt.where(InventoryTransaction.reference_number.ilike(like(reference)))
    if username:
        stmt = stmt.where(InventoryTransaction.username == username)
    if date_from:
        stmt = stmt.where(InventoryTransaction.created_at >= date_from)
    if date_to:
        stmt = stmt.where(InventoryTransaction.created_at <= date_to)
    if q:
        t = like(q)
        stmt = stmt.where(or_(Item.sku.ilike(t), Item.name.ilike(t)))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[r[0] for r in rows], total=total)
