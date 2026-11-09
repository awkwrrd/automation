from datetime import date

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ..errors import WMSError
from ..models import (
    InboundLine,
    InboundOrder,
    InboundStatus,
    InventoryBalance,
    Item,
    Location,
    LocationType,
    Task,
    TaskType,
    TxnType,
    utcnow,
)
from . import inventory
from .common import first_location_of_type, get_or_404

STORAGE_TYPES = (LocationType.BIN, LocationType.SHELF, LocationType.PALLET, LocationType.FLOOR)


def suggest_putaway_location(db: Session, item: Item, warehouse_id: int, exclude_id: int | None = None) -> Location | None:
    """Directed putaway: 1) item's home location, 2) a location already holding the item
    (consolidate), 3) the first empty storage location in pick sequence."""
    if item.default_location and item.default_location.warehouse_id == warehouse_id and item.default_location.active:
        return item.default_location
    consolidate = db.scalar(
        select(Location)
        .join(InventoryBalance, InventoryBalance.location_id == Location.id)
        .where(
            Location.warehouse_id == warehouse_id, Location.active.is_(True),
            Location.location_type.in_(STORAGE_TYPES), InventoryBalance.item_id == item.id,
            Location.id != (exclude_id or 0),
        )
        .group_by(Location.id)
        .order_by(func.sum(InventoryBalance.qty_on_hand).desc())
        .limit(1)
    )
    if consolidate:
        return consolidate
    return db.scalar(
        select(Location)
        .where(
            Location.warehouse_id == warehouse_id, Location.active.is_(True),
            Location.location_type.in_(STORAGE_TYPES),
            ~exists().where(InventoryBalance.location_id == Location.id),
        )
        .order_by(Location.pick_sequence, Location.code)
        .limit(1)
    )


def _refresh_status(order: InboundOrder) -> None:
    if order.status in (InboundStatus.CLOSED, InboundStatus.CANCELLED):
        return
    received = sum(line.qty_received for line in order.lines)
    if received == 0:
        order.status = InboundStatus.OPEN
    elif all(line.qty_received >= line.qty_expected for line in order.lines):
        order.status = InboundStatus.RECEIVED
    else:
        order.status = InboundStatus.RECEIVING


def receive(db: Session, order: InboundOrder, line_id: int, qty: int, username: str, *,
            location_id: int | None = None, lot: str = "", expiration_date: date | None = None,
            create_putaway: bool = True) -> Task | None:
    if order.status in (InboundStatus.CLOSED, InboundStatus.CANCELLED):
        raise WMSError(f"Receipt {order.number} is {order.status}")
    line = get_or_404(db, InboundLine, line_id, "Receipt line")
    if line.inbound_id != order.id:
        raise WMSError("Line does not belong to this receipt")
    if qty <= 0:
        raise WMSError("Quantity must be positive")
    if line.item.lot_tracked and not lot:
        raise WMSError(f"Item {line.item.sku} is lot-tracked; a lot number is required")

    if location_id is None:
        dock = first_location_of_type(db, order.warehouse_id, LocationType.DOCK)
        if dock is None:
            raise WMSError("No DOCK location configured for this warehouse; create one or pick a location")
        location_id = dock.id
    loc = get_or_404(db, Location, location_id, "Location")
    if loc.warehouse_id != order.warehouse_id:
        raise WMSError("Location is in a different warehouse")

    inventory.add_stock(db, line.item_id, loc.id, qty, lot=lot, expiration_date=expiration_date)
    inventory.record_txn(
        db, TxnType.RECEIVE, line.item_id, qty, username=username, warehouse_id=order.warehouse_id,
        to_location_id=loc.id, lot=lot, to_status="AVAILABLE",
        reference_type="INBOUND", reference_number=order.number,
    )
    line.qty_received += qty
    _refresh_status(order)

    task = None
    if create_putaway and loc.location_type == LocationType.DOCK:
        target = suggest_putaway_location(db, line.item, order.warehouse_id, exclude_id=loc.id)
        task = Task(
            task_type=TaskType.PUTAWAY, warehouse_id=order.warehouse_id, item_id=line.item_id,
            lot_number=lot, qty=qty, from_location_id=loc.id, to_location_id=target.id if target else None,
            inbound_line_id=line.id, reference_number=order.number,
        )
        db.add(task)
    db.flush()
    return task


def close(db: Session, order: InboundOrder) -> None:
    if order.status == InboundStatus.CANCELLED:
        raise WMSError("Receipt is cancelled")
    order.status = InboundStatus.CLOSED
    order.closed_at = utcnow()


def cancel(db: Session, order: InboundOrder) -> None:
    if any(line.qty_received for line in order.lines):
        raise WMSError("Cannot cancel a receipt that has received quantity; close it instead")
    order.status = InboundStatus.CANCELLED
    order.closed_at = utcnow()
