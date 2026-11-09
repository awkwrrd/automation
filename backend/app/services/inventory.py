"""Inventory engine: every change to on-hand quantity goes through here so that
balances and the transaction audit trail always agree."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import WMSError
from ..models import (
    InventoryBalance,
    InventoryStatus,
    InventoryTransaction,
    Item,
    Location,
    TxnType,
)
from .common import get_or_404


def get_balance(
    db: Session, item_id: int, location_id: int, lot: str = "", status: str = InventoryStatus.AVAILABLE,
    *, create: bool = False, expiration_date: date | None = None,
) -> InventoryBalance | None:
    bal = db.execute(
        select(InventoryBalance)
        .where(
            InventoryBalance.item_id == item_id,
            InventoryBalance.location_id == location_id,
            InventoryBalance.lot_number == (lot or ""),
            InventoryBalance.status == status,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if bal is None and create:
        bal = InventoryBalance(
            item_id=item_id, location_id=location_id, lot_number=lot or "", status=status,
            qty_on_hand=0, qty_allocated=0, expiration_date=expiration_date,
        )
        db.add(bal)
        db.flush()
    elif bal is not None and expiration_date and not bal.expiration_date:
        bal.expiration_date = expiration_date
    return bal


def record_txn(db: Session, txn_type: TxnType, item_id: int, qty: int, *, username: str | None = None,
               warehouse_id: int | None = None, from_location_id: int | None = None,
               to_location_id: int | None = None, lot: str = "", from_status: str | None = None,
               to_status: str | None = None, reason_code: str | None = None, reference_type: str | None = None,
               reference_number: str | None = None, notes: str | None = None) -> InventoryTransaction:
    txn = InventoryTransaction(
        txn_type=txn_type, item_id=item_id, qty=qty, username=username, warehouse_id=warehouse_id,
        from_location_id=from_location_id, to_location_id=to_location_id, lot_number=lot or "",
        from_status=from_status, to_status=to_status, reason_code=reason_code,
        reference_type=reference_type, reference_number=reference_number, notes=notes,
    )
    db.add(txn)
    return txn


def _check_item_location(db: Session, item_id: int, location_id: int) -> tuple[Item, Location]:
    item = get_or_404(db, Item, item_id, "Item")
    loc = get_or_404(db, Location, location_id, "Location")
    if not loc.active:
        raise WMSError(f"Location {loc.code} is inactive")
    return item, loc


def _check_lot(item: Item, lot: str) -> None:
    if item.lot_tracked and not lot:
        raise WMSError(f"Item {item.sku} is lot-tracked; a lot number is required")


def add_stock(db: Session, item_id: int, location_id: int, qty: int, *, lot: str = "",
              status: str = InventoryStatus.AVAILABLE, expiration_date: date | None = None) -> InventoryBalance:
    if qty <= 0:
        raise WMSError("Quantity must be positive")
    bal = get_balance(db, item_id, location_id, lot, status, create=True, expiration_date=expiration_date)
    assert bal is not None
    bal.qty_on_hand += qty
    return bal


def remove_stock(db: Session, item_id: int, location_id: int, qty: int, *, lot: str = "",
                 status: str = InventoryStatus.AVAILABLE, from_allocated: bool = False) -> InventoryBalance:
    """Remove on-hand. If from_allocated, the qty is also released from qty_allocated
    (i.e. it is the reserved stock being consumed); otherwise only unallocated stock may be taken."""
    if qty <= 0:
        raise WMSError("Quantity must be positive")
    bal = get_balance(db, item_id, location_id, lot, status)
    if bal is None:
        raise WMSError("No inventory found at that location / lot / status")
    if from_allocated:
        if bal.qty_allocated < qty:
            raise WMSError(f"Only {bal.qty_allocated} allocated at {bal.location.code}")
        bal.qty_allocated -= qty
    elif bal.qty_available < qty:
        raise WMSError(
            f"Insufficient available quantity at {bal.location.code}: "
            f"{bal.qty_available} available ({bal.qty_allocated} allocated)"
        )
    bal.qty_on_hand -= qty
    return bal


def cleanup_balance(db: Session, bal: InventoryBalance | None) -> None:
    if bal is not None and bal.qty_on_hand == 0 and bal.qty_allocated == 0:
        db.delete(bal)


# ------------------------------------------------------------------ user-facing operations
def adjust(db: Session, *, item_id: int, location_id: int, qty_delta: int, reason_code: str, username: str,
           lot: str = "", status: str = InventoryStatus.AVAILABLE, expiration_date: date | None = None,
           notes: str | None = None, txn_type: TxnType = TxnType.ADJUST,
           reference_type: str | None = None, reference_number: str | None = None) -> None:
    if qty_delta == 0:
        raise WMSError("Adjustment quantity cannot be zero")
    item, loc = _check_item_location(db, item_id, location_id)
    if qty_delta > 0:
        _check_lot(item, lot)
        add_stock(db, item_id, location_id, qty_delta, lot=lot, status=status, expiration_date=expiration_date)
        bal = None
    else:
        bal = remove_stock(db, item_id, location_id, -qty_delta, lot=lot, status=status)
    record_txn(
        db, txn_type, item_id, qty_delta, username=username, warehouse_id=loc.warehouse_id,
        to_location_id=location_id if qty_delta > 0 else None,
        from_location_id=location_id if qty_delta < 0 else None,
        lot=lot, to_status=status, reason_code=reason_code, notes=notes,
        reference_type=reference_type, reference_number=reference_number,
    )
    db.flush()
    cleanup_balance(db, bal)


def move(db: Session, *, item_id: int, from_location_id: int, to_location_id: int, qty: int, username: str,
         lot: str = "", status: str = InventoryStatus.AVAILABLE, txn_type: TxnType = TxnType.MOVE,
         reference_type: str | None = None, reference_number: str | None = None,
         notes: str | None = None) -> None:
    if from_location_id == to_location_id:
        raise WMSError("From and to locations are the same")
    _, src = _check_item_location(db, item_id, from_location_id)
    _, dst = _check_item_location(db, item_id, to_location_id)
    if src.warehouse_id != dst.warehouse_id:
        raise WMSError("Moves between warehouses are not supported; use a transfer")
    src_bal = remove_stock(db, item_id, from_location_id, qty, lot=lot, status=status)
    add_stock(db, item_id, to_location_id, qty, lot=lot, status=status, expiration_date=src_bal.expiration_date)
    record_txn(
        db, txn_type, item_id, qty, username=username, warehouse_id=src.warehouse_id,
        from_location_id=from_location_id, to_location_id=to_location_id, lot=lot,
        from_status=status, to_status=status, reference_type=reference_type,
        reference_number=reference_number, notes=notes,
    )
    db.flush()
    cleanup_balance(db, src_bal)


def change_status(db: Session, *, item_id: int, location_id: int, qty: int, from_status: str, to_status: str,
                  username: str, lot: str = "", reason_code: str | None = None, notes: str | None = None) -> None:
    if from_status == to_status:
        raise WMSError("Status is unchanged")
    _, loc = _check_item_location(db, item_id, location_id)
    src_bal = remove_stock(db, item_id, location_id, qty, lot=lot, status=from_status)
    add_stock(db, item_id, location_id, qty, lot=lot, status=to_status, expiration_date=src_bal.expiration_date)
    record_txn(
        db, TxnType.STATUS, item_id, qty, username=username, warehouse_id=loc.warehouse_id,
        from_location_id=location_id, to_location_id=location_id, lot=lot,
        from_status=from_status, to_status=to_status, reason_code=reason_code, notes=notes,
    )
    db.flush()
    cleanup_balance(db, src_bal)
