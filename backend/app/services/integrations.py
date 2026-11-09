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
    Item,
    PayloadFormat,
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

# (reference, message body) pairs produced for per-order (ORDER format) endpoints
OrderMessages = list[tuple[str | None, dict]]

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


# ------------------------------------------------------------------ per-order (PascalCase) format
def _num(v) -> float | None:
    return float(v) if v is not None else None


def _p_loc(loc: Location | None) -> dict | None:
    if loc is None:
        return None
    return {"Code": loc.code, "Zone": loc.zone.code if loc.zone else None, "Type": loc.location_type,
            "Aisle": loc.aisle, "Bay": loc.bay, "Level": loc.level, "Position": loc.position,
            "Sequence": loc.pick_sequence}


def _p_item(item: Item) -> dict:
    return {
        "Sku": item.sku, "Description": item.name, "Barcode": item.barcode, "UnitOfMeasure": item.uom,
        "UnitType": item.unit_type or "EACH", "Weight": _num(item.weight), "WeightUnit": item.weight_unit,
        "Length": _num(item.length), "Width": _num(item.width), "Height": _num(item.height),
        "DimensionUnit": item.dim_unit, "LotTracked": item.lot_tracked,
    }


def _p_task(t: Task) -> dict:
    return {"TaskId": t.id, "TaskType": t.task_type, "Quantity": t.qty - t.qty_done, "LotNumber": t.lot_number or None,
            "FromLocation": _p_loc(t.from_location), "ToLocation": _p_loc(t.to_location), "Priority": t.priority}


def _p_header(event: str, warehouse: Warehouse | None, is_test: bool = False) -> dict:
    return {
        "Event": event, "DeliveryId": None, "SchemaVersion": SCHEMA_VERSION, "IsTest": is_test,
        "OccurredAt": utcnow().isoformat() + "Z",
        "Warehouse": warehouse.code if warehouse else None,
    }


def order_message(event: str, order: OutboundOrder, tasks: list[Task], wave=None, is_test: bool = False) -> dict:
    """One order with all its lines. Each line lists the tasks sent with this message
    (only tasks routed to this endpoint, so a line can have none)."""
    by_line: dict[int, list[Task]] = {}
    for t in tasks:
        line_id = t.allocation.order_line_id if t.allocation else None
        by_line.setdefault(line_id, []).append(t)
    lines = []
    for l in order.lines:
        lt = by_line.get(l.id, [])
        lines.append({
            "LineNumber": l.line_no, "ExternalLineId": l.external_line_id, **_p_item(l.item),
            "Quantity": l.qty_ordered, "QuantityToPick": sum(t.qty - t.qty_done for t in lt),
            "Tasks": [_p_task(t) for t in lt],
        })
    return {
        **_p_header(event, order.warehouse, is_test),
        "WaveNumber": wave.number if wave else (order.wave.number if order.wave else None),
        "OrderId": order.id, "OrderNumber": order.number, "ExternalOrderId": order.external_id,
        "Channel": order.channel, "Category": order.category or "STANDARD", "Priority": order.priority,
        "ShipMethod": order.ship_method,
        "RequestedShipDate": order.requested_ship_date.isoformat() if order.requested_ship_date else None,
        "Customer": {"Name": order.customer_name, "Email": order.customer_email, "Phone": order.customer_phone},
        "ShipTo": {"Name": order.ship_name or order.customer_name, "Address1": order.ship_address1,
                   "Address2": order.ship_address2, "City": order.ship_city, "State": order.ship_state,
                   "PostalCode": order.ship_postal_code, "Country": order.ship_country},
        "Notes": order.notes,
        "Lines": lines,
        "Callbacks": {"ConfirmTasks": f"{settings.public_url}/api/automation/confirmations"},
    }


def putaway_message(event: str, receipt, tasks: list[Task]) -> dict:
    return {
        **_p_header(event, receipt.warehouse),
        "ReceiptNumber": receipt.number, "Reference": receipt.reference, "OrderNumber": None,
        "Category": "PUTAWAY",
        "Lines": [{"LineNumber": i, **_p_item(t.item), "Quantity": t.qty - t.qty_done,
                   "QuantityToPick": t.qty - t.qty_done, "Tasks": [_p_task(t)]} for i, t in enumerate(tasks, 1)],
        "Callbacks": {"ConfirmTasks": f"{settings.public_url}/api/automation/confirmations"},
    }


def cancel_message(event: str, db: Session, tasks: list[Task], reason: str) -> OrderMessages:
    groups: dict[int | None, list[Task]] = {}
    for t in tasks:
        groups.setdefault(t.order_id, []).append(t)
    out = []
    for order_id, ts in groups.items():
        order = db.get(OutboundOrder, order_id) if order_id else None
        wh = db.get(Warehouse, ts[0].warehouse_id)
        out.append((order.number if order else ts[0].reference_number, {
            **_p_header(event, wh),
            "OrderNumber": order.number if order else None, "ExternalOrderId": order.external_id if order else None,
            "Category": (order.category or "STANDARD") if order else "PUTAWAY", "Reason": reason,
            "Lines": [{"LineNumber": i, **_p_item(t.item), "Quantity": t.qty, "QuantityDone": t.qty_done,
                       "Tasks": [{"TaskId": t.id, "TaskType": t.task_type}]} for i, t in enumerate(ts, 1)],
        }))
    return out


def sample_order_message(db: Session, warehouse_id: int | None) -> dict:
    """Realistic but clearly fake order (IsTest=true, OrderNumber TEST-0001) for the Test/Preview buttons.
    Uses real items so UnitType etc. look like production data; never a real order."""
    wh = db.get(Warehouse, warehouse_id) if warehouse_id else db.scalar(select(Warehouse).order_by(Warehouse.id))
    items = db.scalars(select(Item).where(Item.active.is_(True)).order_by(Item.id).limit(2)).all()
    lines = [{"LineNumber": i, "ExternalLineId": None, **_p_item(it), "Quantity": i, "QuantityToPick": i,
              "Tasks": [{"TaskId": 0, "TaskType": "PICK", "Quantity": i, "LotNumber": None,
                         "FromLocation": {"Code": "TEST-LOC", "Zone": None, "Type": "BIN", "Aisle": None, "Bay": None,
                                          "Level": None, "Position": None, "Sequence": 0},
                         "ToLocation": None, "Priority": 5}]} for i, it in enumerate(items, 1)]
    return {
        **_p_header(IntegrationEvent.TEST, wh, is_test=True),
        "WaveNumber": None, "OrderId": 0, "OrderNumber": "TEST-0001", "ExternalOrderId": None, "Channel": "TEST",
        "Category": "STANDARD", "Priority": 5, "ShipMethod": "Ground", "RequestedShipDate": None,
        "Customer": {"Name": "Test Customer", "Email": None, "Phone": None},
        "ShipTo": {"Name": "Test Customer", "Address1": "1 Test St", "Address2": None, "City": "Testville",
                   "State": "OH", "PostalCode": "00000", "Country": "US"},
        "Notes": "Test message - do not fulfil", "Lines": lines,
        "Callbacks": {"ConfirmTasks": f"{settings.public_url}/api/automation/confirmations"},
    }


def _rename(obj, names: dict[str, str]):
    if isinstance(obj, dict):
        return {names.get(k, k): _rename(v, names) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rename(v, names) for v in obj]
    return obj


def shape(ep: IntegrationEndpoint, body: dict) -> dict:
    """Apply the endpoint's key renames, then merge its static fields."""
    names = json.loads(ep.field_names) if ep.field_names else {}
    statics = json.loads(ep.static_fields) if ep.static_fields else {}
    out = _rename(body, names) if names else body
    return {**out, **statics} if statics else out


def is_order_format(ep: IntegrationEndpoint) -> bool:
    return (ep.payload_format or PayloadFormat.STANDARD) == PayloadFormat.ORDER


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
            warehouse_id: int | None, data: dict, *, raw: bool = False) -> OutboundMessage:
    """Queue a message. STANDARD: `data` is wrapped in the event envelope.
    raw=True (ORDER format): `data` is the complete message body; its DeliveryId is filled in."""
    msg = OutboundMessage(endpoint_id=endpoint.id, event=event, reference=reference,
                          status=MessageStatus.PENDING, next_attempt_at=utcnow(), created_at=utcnow())
    db.add(msg)
    db.flush()  # need the id for delivery_id
    if raw:
        body = {**data, "DeliveryId": msg.id} if "DeliveryId" in data else data
    else:
        wh = db.get(Warehouse, warehouse_id) if warehouse_id else None
        body = _envelope(msg, wh, data)
    msg.payload = json.dumps(shape(endpoint, body), default=str)
    return msg


def emit_tasks(db: Session, event: IntegrationEvent, warehouse_id: int, reference: str | None,
               tasks: Iterable[Task], build: Callable[[list[Task]], dict],
               build_orders: Callable[[list[Task]], OrderMessages] | None = None) -> list[OutboundMessage]:
    """Send newly created tasks to every subscribed endpoint whose warehouse/zone filter matches.
    `build(tasks)` returns the STANDARD `data` block for that endpoint's subset of tasks;
    `build_orders(tasks)` returns the per-order messages for ORDER-format endpoints."""
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
        if is_order_format(ep) and build_orders:
            for ref, body in build_orders(mine):
                out.append(enqueue(db, ep, event, ref, warehouse_id, body, raw=True))
        else:
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
        if is_order_format(ep):
            for ref, body in cancel_message(IntegrationEvent.TASK_CANCELLED, db, ts, reason):
                enqueue(db, ep, IntegrationEvent.TASK_CANCELLED, ref, ts[0].warehouse_id, body, raw=True)
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

    def build_orders(mine: list[Task]) -> OrderMessages:
        ids = sorted({t.order_id for t in mine if t.order_id})
        return [(orders[i].number, order_message(IntegrationEvent.WAVE_RELEASED, orders[i],
                                                 [t for t in mine if t.order_id == i], wave))
                for i in ids if i in orders]

    emit_tasks(db, IntegrationEvent.WAVE_RELEASED, wave.warehouse_id, wave.number, tasks, build, build_orders)


def order_released(db: Session, order: OutboundOrder, tasks: list[Task]) -> None:
    emit_tasks(db, IntegrationEvent.ORDER_RELEASED, order.warehouse_id, order.number, tasks, lambda mine: {
        "order": order_payload(order),
        "tasks": [task_payload(t, order.number) for t in mine],
    }, lambda mine: [(order.number, order_message(IntegrationEvent.ORDER_RELEASED, order, mine))])


def putaway_created(db: Session, receipt, task: Task) -> None:
    emit_tasks(db, IntegrationEvent.PUTAWAY_CREATED, task.warehouse_id, receipt.number, [task], lambda mine: {
        "receipt": {"id": receipt.id, "number": receipt.number, "reference": receipt.reference},
        "tasks": [task_payload(t) for t in mine],
    }, lambda mine: [(receipt.number, putaway_message(IntegrationEvent.PUTAWAY_CREATED, receipt, mine))])
