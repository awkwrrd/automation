"""Outbound integration events (WMS -> external systems such as a robotics platform).

Events are written to the `outbound_messages` table inside the same database transaction
as the business change that caused them (transactional outbox), so a message is never
lost and never sent for a change that was rolled back. `dispatcher.py` delivers them.
"""
import json
from collections.abc import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    IntegrationEndpoint,
    IntegrationEvent,
    Location,
    MessageStatus,
    OutboundMessage,
    OutboundOrder,
    Task,
    TaskType,
    Warehouse,
    utcnow,
)

SCHEMA_VERSION = "1.0"


# ------------------------------------------------------------------ payload building
def _loc(loc: Location | None) -> dict | None:
    if loc is None:
        return None
    return {
        "id": loc.id, "code": loc.code, "zone": loc.zone.code if loc.zone else None, "type": loc.location_type,
        "aisle": loc.aisle, "bay": loc.bay, "level": loc.level, "position": loc.position,
        "sequence": loc.pick_sequence,
    }


def task_payload(task: Task, order_number: str | None = None) -> dict:
    item = task.item
    return {
        "task_id": task.id,
        "task_type": task.task_type,
        "priority": task.priority,
        "item": {
            "id": item.id, "sku": item.sku, "name": item.name, "barcode": item.barcode, "uom": item.uom,
            "weight": float(item.weight) if item.weight is not None else None, "weight_unit": item.weight_unit,
            "lot_tracked": item.lot_tracked,
        },
        "lot_number": task.lot_number or None,
        "qty": task.qty - task.qty_done,
        "from_location": _loc(task.from_location),
        "to_location": _loc(task.to_location),
        "order_id": task.order_id,
        "order_number": order_number,
        "reference": task.reference_number,
    }


def order_payload(order: OutboundOrder) -> dict:
    return {
        "id": order.id, "number": order.number, "external_id": order.external_id, "channel": order.channel,
        "priority": order.priority, "customer_name": order.customer_name, "ship_method": order.ship_method,
        "requested_ship_date": order.requested_ship_date.isoformat() if order.requested_ship_date else None,
        "ship_to": {
            "name": order.ship_name, "address1": order.ship_address1, "address2": order.ship_address2,
            "city": order.ship_city, "state": order.ship_state, "postal_code": order.ship_postal_code,
            "country": order.ship_country,
        },
        "lines": [{"line_no": l.line_no, "sku": l.item.sku, "qty_ordered": l.qty_ordered} for l in order.lines],
    }


def _envelope(msg: OutboundMessage, warehouse: Warehouse | None, data: dict) -> dict:
    return {
        "event": msg.event,
        "delivery_id": msg.id,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": msg.created_at.isoformat() + "Z",
        "warehouse": {"id": warehouse.id, "code": warehouse.code} if warehouse else None,
        "data": data,
        "callbacks": {
            "confirm_tasks": f"{settings.public_url}/api/automation/confirmations",
        },
    }


# ------------------------------------------------------------------ routing
def endpoints_for(db: Session, event: str, warehouse_id: int | None) -> list[IntegrationEndpoint]:
    eps = db.scalars(select(IntegrationEndpoint).where(IntegrationEndpoint.active.is_(True))
                     .order_by(IntegrationEndpoint.id)).all()
    return [e for e in eps if event in e.event_list and (e.warehouse_id is None or e.warehouse_id == warehouse_id)]


def _task_zone(task: Task) -> int | None:
    # putaway is routed by where it is going; everything else by where it is picked from
    loc = task.to_location if task.task_type == TaskType.PUTAWAY else task.from_location
    return loc.zone_id if loc else None


def enqueue(db: Session, endpoint: IntegrationEndpoint, event: str, reference: str | None,
            warehouse_id: int | None, data: dict) -> OutboundMessage:
    msg = OutboundMessage(endpoint_id=endpoint.id, event=event, reference=reference,
                          status=MessageStatus.PENDING, next_attempt_at=utcnow(), created_at=utcnow())
    db.add(msg)
    db.flush()  # need the id for delivery_id
    wh = db.get(Warehouse, warehouse_id) if warehouse_id else None
    msg.payload = json.dumps(_envelope(msg, wh, data), default=str)
    return msg


def emit_tasks(db: Session, event: IntegrationEvent, warehouse_id: int, reference: str | None,
               tasks: Iterable[Task], build: Callable[[list[Task]], dict]) -> list[OutboundMessage]:
    """Send newly created tasks to every subscribed endpoint whose warehouse/zone filter matches.
    `build(tasks)` returns the event-specific `data` block for that endpoint's subset of tasks."""
    tasks = list(tasks)
    out = []
    for ep in endpoints_for(db, event, warehouse_id):
        zones = ep.zone_id_list
        mine = [t for t in tasks if (not zones or _task_zone(t) in zones)
                and (t.dispatch_endpoint_id is None or t.dispatch_endpoint_id == ep.id)]
        if not mine:
            continue
        if ep.assign_tasks:
            for t in mine:
                t.dispatch_endpoint_id = ep.id
                t.assigned_to = ep.name
        out.append(enqueue(db, ep, event, reference, warehouse_id, build(mine)))
    return out


def emit_tasks_cancelled(db: Session, tasks: Iterable[Task], reason: str) -> None:
    by_ep: dict[int, list[Task]] = {}
    for t in tasks:
        if t.dispatch_endpoint_id:
            by_ep.setdefault(t.dispatch_endpoint_id, []).append(t)
    for ep_id, ts in by_ep.items():
        ep = db.get(IntegrationEndpoint, ep_id)
        if ep is None or not ep.active or IntegrationEvent.TASK_CANCELLED not in ep.event_list:
            continue
        enqueue(db, ep, IntegrationEvent.TASK_CANCELLED, ts[0].reference_number, ts[0].warehouse_id, {
            "reason": reason,
            "tasks": [{"task_id": t.id, "task_type": t.task_type, "order_id": t.order_id,
                       "reference": t.reference_number, "sku": t.item.sku, "qty": t.qty,
                       "qty_done": t.qty_done} for t in ts],
        })


# ------------------------------------------------------------------ event helpers used by services
def wave_released(db: Session, wave, tasks: list[Task]) -> None:
    orders = {o.id: o for o in wave.orders}

    def build(mine: list[Task]) -> dict:
        ids = sorted({t.order_id for t in mine if t.order_id})
        return {
            "wave": {"id": wave.id, "number": wave.number, "description": wave.description,
                     "released_at": wave.released_at.isoformat() + "Z" if wave.released_at else None},
            "orders": [order_payload(orders[i]) for i in ids if i in orders],
            "tasks": [task_payload(t, orders[t.order_id].number if t.order_id in orders else None) for t in mine],
        }

    emit_tasks(db, IntegrationEvent.WAVE_RELEASED, wave.warehouse_id, wave.number, tasks, build)


def order_released(db: Session, order: OutboundOrder, tasks: list[Task]) -> None:
    emit_tasks(db, IntegrationEvent.ORDER_RELEASED, order.warehouse_id, order.number, tasks, lambda mine: {
        "order": order_payload(order),
        "tasks": [task_payload(t, order.number) for t in mine],
    })


def putaway_created(db: Session, receipt, task: Task) -> None:
    emit_tasks(db, IntegrationEvent.PUTAWAY_CREATED, task.warehouse_id, receipt.number, [task], lambda mine: {
        "receipt": {"id": receipt.id, "number": receipt.number, "reference": receipt.reference},
        "tasks": [task_payload(t) for t in mine],
    })
