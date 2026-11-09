from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import WMSError
from ..models import (
    CountStatus,
    CycleCount,
    CycleCountLine,
    InventoryBalance,
    Location,
    TxnType,
    utcnow,
)
from . import inventory
from .common import next_number


def create(db: Session, warehouse_id: int, username: str, *, location_ids: list[int] | None = None,
           zone_id: int | None = None, item_id: int | None = None, description: str | None = None,
           blind: bool = False) -> CycleCount:
    q = (select(InventoryBalance).join(Location, Location.id == InventoryBalance.location_id)
         .where(Location.warehouse_id == warehouse_id))
    if location_ids:
        q = q.where(Location.id.in_(location_ids))
    if zone_id:
        q = q.where(Location.zone_id == zone_id)
    if item_id:
        q = q.where(InventoryBalance.item_id == item_id)
    if not (location_ids or zone_id or item_id):
        raise WMSError("Choose locations, a zone, or an item to count")
    balances = db.scalars(q.order_by(Location.pick_sequence, Location.code)).all()
    count = CycleCount(number=next_number(db, "count"), warehouse_id=warehouse_id, description=description,
                       blind=blind, created_by=username)
    db.add(count)
    for b in balances:
        count.lines.append(CycleCountLine(
            location_id=b.location_id, item_id=b.item_id, lot_number=b.lot_number, inv_status=b.status,
            expected_qty=b.qty_on_hand,
        ))
    if not balances and location_ids:
        pass  # empty-location count: counters can add lines for found stock
    db.flush()
    return count


def record(db: Session, count: CycleCount, entries: list[dict], username: str) -> None:
    if count.status != CountStatus.OPEN:
        raise WMSError(f"Count is {count.status}")
    by_id = {line.id: line for line in count.lines}
    for e in entries:
        if e["counted_qty"] is not None and e["counted_qty"] < 0:
            raise WMSError("Counted quantity cannot be negative")
        if e.get("line_id"):
            line = by_id.get(e["line_id"])
            if line is None:
                raise WMSError(f"Line {e['line_id']} not in this count")
        else:  # stock found that was not expected
            line = CycleCountLine(location_id=e["location_id"], item_id=e["item_id"],
                                  lot_number=e.get("lot_number") or "", expected_qty=0)
            count.lines.append(line)
        line.counted_qty = e["counted_qty"]
        line.counted_by = username
        line.counted_at = utcnow()
    db.flush()


def complete(db: Session, count: CycleCount, username: str) -> int:
    """Post variances as COUNT adjustments against current on-hand. Returns # of adjustments."""
    if count.status != CountStatus.OPEN:
        raise WMSError(f"Count is {count.status}")
    uncounted = [l for l in count.lines if l.counted_qty is None]
    if uncounted:
        raise WMSError(f"{len(uncounted)} line(s) have not been counted")
    adjustments = 0
    for line in count.lines:
        bal = inventory.get_balance(db, line.item_id, line.location_id, line.lot_number, line.inv_status)
        current = bal.qty_on_hand if bal else 0
        allocated = bal.qty_allocated if bal else 0
        delta = line.counted_qty - current
        if delta == 0:
            line.adjusted_qty = 0
            continue
        if line.counted_qty < allocated:
            raise WMSError(
                f"{line.item.sku} @ {line.location.code}: counted {line.counted_qty} is below the "
                f"{allocated} allocated to orders; deallocate first"
            )
        inventory.adjust(
            db, item_id=line.item_id, location_id=line.location_id, qty_delta=delta, reason_code="CYCLE_COUNT",
            username=username, lot=line.lot_number, status=line.inv_status, txn_type=TxnType.COUNT,
            reference_type="COUNT", reference_number=count.number,
        )
        line.adjusted_qty = delta
        adjustments += 1
    count.status = CountStatus.COMPLETED
    count.completed_at = utcnow()
    db.flush()
    return adjustments
