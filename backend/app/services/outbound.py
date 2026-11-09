"""Outbound flow: allocate -> release (pick tasks) -> pick -> pack -> ship."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import WMSError
from ..models import (
    Allocation,
    AllocationStatus,
    InventoryBalance,
    InventoryStatus,
    Location,
    LocationType,
    OrderStatus,
    OutboundOrder,
    Shipment,
    ShipmentStatus,
    Task,
    TaskStatus,
    TaskType,
    TxnType,
    Wave,
    WaveStatus,
    utcnow,
)
from . import integrations, inventory
from .common import first_location_of_type, next_number

CLOSED = (OrderStatus.SHIPPED, OrderStatus.CANCELLED)


def _open_tasks(db: Session, order: OutboundOrder) -> list[Task]:
    return list(db.scalars(select(Task).where(
        Task.order_id == order.id, Task.task_type == TaskType.PICK,
        Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
    )))


def refresh_status(db: Session, order: OutboundOrder) -> None:
    if order.status in CLOSED or order.status == OrderStatus.PACKED:
        return
    lines = order.lines
    picked = sum(line.qty_picked for line in lines)
    allocated = sum(line.qty_allocated for line in lines)
    has_tasks = db.scalar(select(Task.id).where(Task.order_id == order.id, Task.task_type == TaskType.PICK).limit(1))
    open_tasks = _open_tasks(db, order)
    unreleased = any(
        a.status == AllocationStatus.OPEN and not _has_task(db, a) for line in lines for a in line.allocations
    )
    if open_tasks:
        order.status = OrderStatus.PICKING if picked else OrderStatus.RELEASED
    elif unreleased:
        order.status = (OrderStatus.ALLOCATED if all(l.qty_allocated >= l.qty_ordered for l in lines)
                        else OrderStatus.PARTIALLY_ALLOCATED)
    elif has_tasks and picked:
        order.status = OrderStatus.PICKED
    elif allocated:
        order.status = (OrderStatus.ALLOCATED if all(l.qty_allocated >= l.qty_ordered for l in lines)
                        else OrderStatus.PARTIALLY_ALLOCATED)
    else:
        order.status = OrderStatus.NEW


def _has_task(db: Session, alloc: Allocation) -> bool:
    return db.scalar(select(Task.id).where(Task.allocation_id == alloc.id).limit(1)) is not None


def allocate(db: Session, order: OutboundOrder, username: str) -> int:
    """Reserve inventory FEFO (earliest expiry first), then by pick sequence. Returns units allocated."""
    if order.status in CLOSED or order.status == OrderStatus.PACKED:
        raise WMSError(f"Order {order.number} is {order.status}")
    total = 0
    for line in order.lines:
        need = line.qty_ordered - line.qty_allocated
        if need <= 0:
            continue
        balances = db.scalars(
            select(InventoryBalance)
            .join(Location, Location.id == InventoryBalance.location_id)
            .where(
                InventoryBalance.item_id == line.item_id,
                InventoryBalance.status == InventoryStatus.AVAILABLE,
                InventoryBalance.qty_on_hand > InventoryBalance.qty_allocated,
                Location.warehouse_id == order.warehouse_id,
                Location.pickable.is_(True),
                Location.active.is_(True),
            )
            .order_by(
                InventoryBalance.expiration_date.is_(None),
                InventoryBalance.expiration_date,
                InventoryBalance.received_at,
                Location.pick_sequence,
                Location.code,
            )
            .with_for_update()
        ).all()
        for bal in balances:
            if need <= 0:
                break
            take = min(need, bal.qty_available)
            bal.qty_allocated += take
            line.qty_allocated += take
            need -= take
            total += take
            db.add(Allocation(
                order_line_id=line.id, item_id=line.item_id, location_id=bal.location_id,
                lot_number=bal.lot_number, qty=take,
            ))
            inventory.record_txn(
                db, TxnType.ALLOCATE, line.item_id, take, username=username, warehouse_id=order.warehouse_id,
                from_location_id=bal.location_id, lot=bal.lot_number,
                reference_type="ORDER", reference_number=order.number,
            )
    db.flush()
    db.refresh(order)
    refresh_status(db, order)
    return total


def release(db: Session, order: OutboundOrder, wave: Wave | None = None) -> list[Task]:
    """Create pick tasks for every allocation that does not yet have one."""
    if order.status in CLOSED or order.status == OrderStatus.PACKED:
        raise WMSError(f"Order {order.number} is {order.status}")
    staging = first_location_of_type(db, order.warehouse_id, LocationType.STAGING)
    if staging is None:
        raise WMSError("No STAGING location configured for this warehouse")
    tasks: list[Task] = []
    for line in order.lines:
        for alloc in line.allocations:
            if alloc.status != AllocationStatus.OPEN or _has_task(db, alloc):
                continue
            task = Task(
                task_type=TaskType.PICK, warehouse_id=order.warehouse_id, item_id=alloc.item_id,
                lot_number=alloc.lot_number, qty=alloc.qty, from_location_id=alloc.location_id,
                to_location_id=staging.id, order_id=order.id, allocation_id=alloc.id,
                wave_id=wave.id if wave else order.wave_id, priority=order.priority,
                reference_number=order.number,
            )
            db.add(task)
            tasks.append(task)
    if not tasks and not _open_tasks(db, order):
        raise WMSError(f"Order {order.number} has nothing allocated to release")
    db.flush()
    refresh_status(db, order)
    return tasks


def complete_pick(db: Session, task: Task, qty: int, username: str, to_location_id: int | None = None) -> None:
    alloc = task.allocation
    if alloc is None:
        raise WMSError("Pick task has no allocation")
    remaining = task.qty - task.qty_done
    if qty < 0 or qty > remaining:
        raise WMSError(f"Pick quantity must be between 0 and {remaining}")
    order = db.get(OutboundOrder, task.order_id)
    assert order is not None
    line = alloc.line
    staging_id = to_location_id or task.to_location_id
    if staging_id is None:
        raise WMSError("No destination (staging) location")
    staging = db.get(Location, staging_id)
    if staging is None or staging.location_type != LocationType.STAGING:
        raise WMSError("Picks must be dropped to a STAGING location")

    if qty > 0:
        src = inventory.remove_stock(db, alloc.item_id, alloc.location_id, qty, lot=alloc.lot_number,
                                     from_allocated=True)
        # staged stock stays reserved (allocated) until shipped
        dst = inventory.add_stock(db, alloc.item_id, staging.id, qty, lot=alloc.lot_number,
                                  expiration_date=src.expiration_date)
        dst.qty_allocated += qty
        inventory.record_txn(
            db, TxnType.PICK, alloc.item_id, qty, username=username, warehouse_id=task.warehouse_id,
            from_location_id=alloc.location_id, to_location_id=staging.id, lot=alloc.lot_number,
            reference_type="ORDER", reference_number=order.number,
        )
        alloc.qty_picked += qty
        alloc.staged_location_id = staging.id
        line.qty_picked += qty
        task.qty_done += qty
        db.flush()
        inventory.cleanup_balance(db, src)

    # short pick: confirming less than remaining closes the task and un-reserves the rest
    short = task.qty - task.qty_done
    if short > 0:
        bal = inventory.get_balance(db, alloc.item_id, alloc.location_id, alloc.lot_number)
        if bal is not None:
            bal.qty_allocated -= short
        alloc.qty -= short
        line.qty_allocated -= short
        inventory.record_txn(
            db, TxnType.DEALLOCATE, alloc.item_id, short, username=username, warehouse_id=task.warehouse_id,
            from_location_id=alloc.location_id, lot=alloc.lot_number, reason_code="SHORT_PICK",
            reference_type="ORDER", reference_number=order.number,
        )
    alloc.status = AllocationStatus.PICKED if alloc.qty_picked > 0 else AllocationStatus.CANCELLED
    task.status = TaskStatus.COMPLETE
    task.completed_at = utcnow()
    task.completed_by = username
    task.to_location_id = staging.id
    db.flush()
    refresh_status(db, order)
    _refresh_wave(db, order.wave_id)


def _refresh_wave(db: Session, wave_id: int | None) -> None:
    if not wave_id:
        return
    wave = db.get(Wave, wave_id)
    if wave and wave.status == WaveStatus.RELEASED:
        open_count = db.scalar(select(Task.id).where(
            Task.wave_id == wave_id, Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS))
        ).limit(1))
        if open_count is None:
            wave.status = WaveStatus.COMPLETE


def pack(db: Session, order: OutboundOrder, username: str, *, carrier: str | None, service: str | None,
         packages: int = 1, weight: Decimal | None = None) -> Shipment:
    if order.status != OrderStatus.PICKED:
        raise WMSError(f"Order must be PICKED to pack (currently {order.status})")
    if _open_tasks(db, order):
        raise WMSError("Order still has open pick tasks")
    shipment = Shipment(
        number=next_number(db, "shipment"), order_id=order.id, carrier=carrier, service=service,
        packages=max(1, packages), weight=weight, packed_by=username,
    )
    db.add(shipment)
    order.status = OrderStatus.PACKED
    db.flush()
    return shipment


def ship(db: Session, order: OutboundOrder, username: str, *, tracking_number: str | None,
         carrier: str | None = None) -> Shipment:
    if order.status != OrderStatus.PACKED:
        raise WMSError(f"Order must be PACKED to ship (currently {order.status})")
    shipment = next((s for s in order.shipments if s.status == ShipmentStatus.PACKED), None)
    if shipment is None:
        raise WMSError("No packed shipment found")
    for line in order.lines:
        for alloc in line.allocations:
            if alloc.status == AllocationStatus.PICKED and alloc.qty_picked > 0:
                bal = inventory.remove_stock(db, alloc.item_id, alloc.staged_location_id, alloc.qty_picked,
                                             lot=alloc.lot_number, from_allocated=True)
                inventory.record_txn(
                    db, TxnType.SHIP, alloc.item_id, -alloc.qty_picked, username=username,
                    warehouse_id=order.warehouse_id, from_location_id=alloc.staged_location_id,
                    lot=alloc.lot_number, reference_type="ORDER", reference_number=order.number,
                )
                line.qty_shipped += alloc.qty_picked
                alloc.status = AllocationStatus.SHIPPED
                db.flush()
                inventory.cleanup_balance(db, bal)
            elif alloc.status == AllocationStatus.OPEN:
                _release_allocation(db, order, alloc, username)
    shipment.status = ShipmentStatus.SHIPPED
    shipment.tracking_number = tracking_number
    if carrier:
        shipment.carrier = carrier
    shipment.shipped_at = utcnow()
    order.status = OrderStatus.SHIPPED
    order.shipped_at = shipment.shipped_at
    if order.shopify_order_id:  # picked up by the Shopify connector, which creates the fulfillment
        order.shopify_fulfillment_status = "PENDING"
    db.flush()
    return shipment


def _release_allocation(db: Session, order: OutboundOrder, alloc: Allocation, username: str) -> None:
    open_qty = alloc.qty - alloc.qty_picked
    if open_qty > 0:
        bal = inventory.get_balance(db, alloc.item_id, alloc.location_id, alloc.lot_number)
        if bal is not None:
            bal.qty_allocated -= open_qty
        alloc.line.qty_allocated -= open_qty
        inventory.record_txn(
            db, TxnType.DEALLOCATE, alloc.item_id, open_qty, username=username, warehouse_id=order.warehouse_id,
            from_location_id=alloc.location_id, lot=alloc.lot_number,
            reference_type="ORDER", reference_number=order.number,
        )
    alloc.qty = alloc.qty_picked
    alloc.status = AllocationStatus.PICKED if alloc.qty_picked else AllocationStatus.CANCELLED


def deallocate(db: Session, order: OutboundOrder, username: str) -> None:
    """Release every un-picked reservation and cancel open pick tasks."""
    if order.status in CLOSED or order.status == OrderStatus.PACKED:
        raise WMSError(f"Order {order.number} is {order.status}")
    cancelled = _open_tasks(db, order)
    for task in cancelled:
        task.status = TaskStatus.CANCELLED
        task.completed_at = utcnow()
        task.completed_by = username
    integrations.emit_tasks_cancelled(db, cancelled, f"Order {order.number} unallocated or cancelled")
    for line in order.lines:
        for alloc in line.allocations:
            if alloc.status == AllocationStatus.OPEN:
                _release_allocation(db, order, alloc, username)
    db.flush()
    refresh_status(db, order)


def cancel(db: Session, order: OutboundOrder, username: str) -> None:
    if order.status in CLOSED:
        raise WMSError(f"Order {order.number} is already {order.status}")
    for s in order.shipments:
        if s.status == ShipmentStatus.PACKED:
            db.delete(s)
    order.status = OrderStatus.PICKED if order.status == OrderStatus.PACKED else order.status
    deallocate(db, order, username)
    # picked stock sitting in staging is un-reserved so it can be put back / reused
    for line in order.lines:
        for alloc in line.allocations:
            if alloc.status == AllocationStatus.PICKED and alloc.staged_location_id:
                bal = inventory.get_balance(db, alloc.item_id, alloc.staged_location_id, alloc.lot_number)
                if bal is not None:
                    bal.qty_allocated -= alloc.qty_picked
                alloc.status = AllocationStatus.CANCELLED
    order.status = OrderStatus.CANCELLED
    db.flush()


# ------------------------------------------------------------------ waves
def create_wave(db: Session, warehouse_id: int, order_ids: list[int], description: str | None) -> Wave:
    if not order_ids:
        raise WMSError("Select at least one order")
    wave = Wave(number=next_number(db, "wave"), warehouse_id=warehouse_id, description=description)
    db.add(wave)
    db.flush()
    for oid in order_ids:
        order = db.get(OutboundOrder, oid)
        if order is None:
            raise WMSError(f"Order id {oid} not found")
        if order.warehouse_id != warehouse_id:
            raise WMSError(f"Order {order.number} belongs to another warehouse")
        if order.status not in (OrderStatus.NEW, OrderStatus.PARTIALLY_ALLOCATED, OrderStatus.ALLOCATED):
            raise WMSError(f"Order {order.number} is {order.status} and cannot be waved")
        if order.wave_id:
            raise WMSError(f"Order {order.number} is already on a wave")
        order.wave_id = wave.id
    db.flush()
    return wave


def release_wave(db: Session, wave: Wave, username: str) -> dict:
    if wave.status != WaveStatus.PLANNED:
        raise WMSError(f"Wave is {wave.status}")
    tasks: list[Task] = []
    skipped: list[str] = []
    for order in wave.orders:
        if order.status in CLOSED:
            continue
        allocate(db, order, username)
        try:
            tasks += release(db, order, wave)
        except WMSError:
            skipped.append(order.number)
    wave.status = WaveStatus.RELEASED
    wave.released_at = utcnow()
    db.flush()
    if tasks:
        integrations.wave_released(db, wave, tasks)
    _refresh_wave(db, wave.id)
    return {"tasks_created": len(tasks), "orders_not_released": skipped}
