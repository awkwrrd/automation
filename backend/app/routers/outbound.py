from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, require_role
from ..errors import WMSError
from ..models import (Item, OrderStatus, OutboundLine, OutboundOrder, Role, Task, TaskStatus, User, Wave)
from ..schemas import (OrderIn, OrderOut, OrderSummary, PackIn, Page, ShipIn, ShipmentOut, WaveIn, WaveOut)
from ..services import integrations
from ..services import outbound as svc
from ..services.common import get_or_404, next_number
from ._util import like, paginate

router = APIRouter(tags=["outbound / orders"], dependencies=[Depends(current_user)])
supervisor = Depends(require_role(Role.SUPERVISOR))


def _summary(order: OutboundOrder, model=OrderOut):
    out = model.model_validate(order)
    out.units = sum(l.qty_ordered for l in order.lines)
    out.line_count = len(order.lines)
    return out


@router.get("/orders", response_model=Page[OrderSummary])
def list_orders(status: str | None = None, warehouse_id: int | None = None, q: str | None = None,
                wave_id: int | None = None, unwaved: bool = False, open_only: bool = False,
                limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    stmt = (select(OutboundOrder).options(selectinload(OutboundOrder.lines), selectinload(OutboundOrder.wave))
            .order_by(OutboundOrder.priority, OutboundOrder.id.desc()))
    if status:
        stmt = stmt.where(OutboundOrder.status.in_(status.split(",")))
    if open_only:
        stmt = stmt.where(OutboundOrder.status.not_in((OrderStatus.SHIPPED, OrderStatus.CANCELLED)))
    if warehouse_id:
        stmt = stmt.where(OutboundOrder.warehouse_id == warehouse_id)
    if wave_id:
        stmt = stmt.where(OutboundOrder.wave_id == wave_id)
    if unwaved:
        stmt = stmt.where(OutboundOrder.wave_id.is_(None))
    if q:
        t = like(q)
        stmt = stmt.where(or_(OutboundOrder.number.ilike(t), OutboundOrder.external_id.ilike(t),
                              OutboundOrder.customer_name.ilike(t)))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_summary(r[0], OrderSummary) for r in rows], total=total)


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(body: OrderIn, db: Session = Depends(get_db)):
    if body.external_id and db.scalar(select(OutboundOrder.id).where(
            OutboundOrder.external_id == body.external_id, OutboundOrder.channel == body.channel)):
        raise WMSError(f"Order with external id {body.external_id} already exists", 409)
    order = OutboundOrder(number=next_number(db, "order"), **body.model_dump(exclude={"lines"}))
    for i, line in enumerate(body.lines, start=1):
        item = get_or_404(db, Item, line.item_id, "Item")
        if not item.active:
            raise WMSError(f"Item {item.sku} is inactive")
        order.lines.append(OutboundLine(line_no=i, **line.model_dump()))
    db.add(order)
    db.flush()
    return _summary(order)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return _summary(get_or_404(db, OutboundOrder, order_id, "Order"))


def _act(order_id: int, db: Session):
    return get_or_404(db, OutboundOrder, order_id, "Order")


@router.post("/orders/{order_id}/allocate", response_model=OrderOut, dependencies=[supervisor])
def allocate(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = _act(order_id, db)
    svc.allocate(db, order, user.username)
    return _summary(order)


@router.post("/orders/{order_id}/release", response_model=OrderOut, dependencies=[supervisor])
def release(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Allocate whatever is still needed, then create pick tasks."""
    order = _act(order_id, db)
    if order.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_ALLOCATED):
        svc.allocate(db, order, user.username)
    tasks = svc.release(db, order)
    if tasks:
        integrations.order_released(db, order, tasks)
    return _summary(order)


@router.post("/orders/{order_id}/deallocate", response_model=OrderOut, dependencies=[supervisor])
def deallocate(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = _act(order_id, db)
    svc.deallocate(db, order, user.username)
    return _summary(order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, dependencies=[supervisor])
def cancel(order_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = _act(order_id, db)
    svc.cancel(db, order, user.username)
    return _summary(order)


@router.post("/orders/{order_id}/pack", response_model=ShipmentOut)
def pack(order_id: int, body: PackIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.pack(db, _act(order_id, db), user.username, carrier=body.carrier, service=body.service,
                    packages=body.packages, weight=body.weight)


@router.post("/orders/{order_id}/ship", response_model=ShipmentOut)
def ship(order_id: int, body: ShipIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.ship(db, _act(order_id, db), user.username, tracking_number=body.tracking_number,
                    carrier=body.carrier)


# ------------------------------------------------------------------ waves
def _wave_out(db: Session, wave: Wave) -> WaveOut:
    out = WaveOut.model_validate(wave)
    out.order_count = len(wave.orders)
    out.total_tasks = db.scalar(select(func.count(Task.id)).where(Task.wave_id == wave.id)) or 0
    out.open_tasks = db.scalar(select(func.count(Task.id)).where(
        Task.wave_id == wave.id, Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))) or 0
    return out


@router.get("/waves", response_model=Page[WaveOut])
def list_waves(status: str | None = None, warehouse_id: int | None = None, limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db)):
    stmt = select(Wave).options(selectinload(Wave.orders)).order_by(Wave.id.desc())
    if status:
        stmt = stmt.where(Wave.status == status)
    if warehouse_id:
        stmt = stmt.where(Wave.warehouse_id == warehouse_id)
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_wave_out(db, r[0]) for r in rows], total=total)


@router.post("/waves", response_model=WaveOut, status_code=201, dependencies=[supervisor])
def create_wave(body: WaveIn, db: Session = Depends(get_db)):
    return _wave_out(db, svc.create_wave(db, body.warehouse_id, body.order_ids, body.description))


@router.get("/waves/{wave_id}", response_model=WaveOut)
def get_wave(wave_id: int, db: Session = Depends(get_db)):
    return _wave_out(db, get_or_404(db, Wave, wave_id, "Wave"))


@router.post("/waves/{wave_id}/release", dependencies=[supervisor])
def release_wave(wave_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return svc.release_wave(db, get_or_404(db, Wave, wave_id, "Wave"), user.username)
