from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user
from ..models import (InboundOrder, InboundStatus, InventoryBalance, InventoryTransaction, Item, Location,
                      OrderStatus, OutboundOrder, Task, TaskStatus, TxnType, utcnow)
from ..schemas import TxnOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(current_user)])


@router.get("")
def dashboard(warehouse_id: int | None = None, db: Session = Depends(get_db)):
    def wh(stmt, col):
        return stmt.where(col == warehouse_id) if warehouse_id else stmt

    orders_by_status = dict(db.execute(wh(
        select(OutboundOrder.status, func.count()).group_by(OutboundOrder.status), OutboundOrder.warehouse_id
    )).all())
    tasks_by_type = dict(db.execute(wh(
        select(Task.task_type, func.count()).where(Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))
        .group_by(Task.task_type), Task.warehouse_id
    )).all())
    units = db.scalar(wh(select(func.coalesce(func.sum(InventoryBalance.qty_on_hand), 0))
                         .join(Location, Location.id == InventoryBalance.location_id), Location.warehouse_id))
    loc_total = db.scalar(wh(select(func.count(Location.id)).where(Location.active.is_(True)), Location.warehouse_id))
    loc_used = db.scalar(wh(select(func.count(func.distinct(InventoryBalance.location_id)))
                            .join(Location, Location.id == InventoryBalance.location_id)
                            .where(InventoryBalance.qty_on_hand > 0), Location.warehouse_id))
    open_receipts = db.scalar(wh(select(func.count(InboundOrder.id)).where(
        InboundOrder.status.in_((InboundStatus.OPEN, InboundStatus.RECEIVING))), InboundOrder.warehouse_id))
    since = utcnow() - timedelta(days=7)
    shipped_7d = db.scalar(wh(select(func.count(OutboundOrder.id)).where(
        OutboundOrder.status == OrderStatus.SHIPPED, OutboundOrder.shipped_at >= since), OutboundOrder.warehouse_id))
    received_7d = db.scalar(wh(select(func.coalesce(func.sum(InventoryTransaction.qty), 0)).where(
        InventoryTransaction.txn_type == TxnType.RECEIVE, InventoryTransaction.created_at >= since),
        InventoryTransaction.warehouse_id))

    # low stock: available (AVAILABLE status, non-staging) <= reorder point
    from .items import _stock_subquery
    s = _stock_subquery()
    low = db.execute(
        select(Item.id, Item.sku, Item.name, Item.reorder_point, Item.reorder_qty,
               func.coalesce(s.c.available, 0).label("available"))
        .outerjoin(s, s.c.item_id == Item.id)
        .where(Item.active.is_(True), Item.reorder_point > 0, func.coalesce(s.c.available, 0) <= Item.reorder_point)
        .order_by(func.coalesce(s.c.available, 0)).limit(10)
    ).mappings().all()
    low_count = db.scalar(select(func.count()).select_from(
        select(Item.id).outerjoin(s, s.c.item_id == Item.id)
        .where(Item.active.is_(True), Item.reorder_point > 0, func.coalesce(s.c.available, 0) <= Item.reorder_point)
        .subquery()))

    # daily throughput (last 7 days): units received vs shipped
    daily = {}
    for t, d, q in db.execute(wh(
        select(InventoryTransaction.txn_type, func.date(InventoryTransaction.created_at), func.sum(InventoryTransaction.qty))
        .where(InventoryTransaction.created_at >= since,
               InventoryTransaction.txn_type.in_((TxnType.RECEIVE, TxnType.SHIP)))
        .group_by(InventoryTransaction.txn_type, func.date(InventoryTransaction.created_at)),
        InventoryTransaction.warehouse_id)).all():
        key = str(d)
        daily.setdefault(key, {"date": key, "received": 0, "shipped": 0})
        daily[key]["received" if t == TxnType.RECEIVE else "shipped"] += abs(int(q or 0))
    days = []
    for i in range(6, -1, -1):
        key = (utcnow() - timedelta(days=i)).date().isoformat()
        days.append(daily.get(key, {"date": key, "received": 0, "shipped": 0}))

    recent = db.scalars(wh(select(InventoryTransaction), InventoryTransaction.warehouse_id)
                        .options(joinedload(InventoryTransaction.item), joinedload(InventoryTransaction.from_location),
                                 joinedload(InventoryTransaction.to_location))
                        .order_by(InventoryTransaction.id.desc()).limit(12)).all()

    open_statuses = [s for s in OrderStatus if s not in (OrderStatus.SHIPPED, OrderStatus.CANCELLED)]
    return {
        "skus": db.scalar(select(func.count(Item.id)).where(Item.active.is_(True))),
        "units_on_hand": int(units or 0),
        "locations_total": loc_total, "locations_used": loc_used,
        "open_orders": sum(orders_by_status.get(s, 0) for s in open_statuses),
        "orders_by_status": orders_by_status,
        "open_tasks_by_type": tasks_by_type,
        "open_receipts": open_receipts,
        "shipped_orders_7d": shipped_7d,
        "received_units_7d": int(received_7d or 0),
        "low_stock_count": low_count,
        "low_stock": [dict(r) for r in low],
        "throughput": days,
        "recent_transactions": [TxnOut.model_validate(t).model_dump(mode="json") for t in recent],
    }
