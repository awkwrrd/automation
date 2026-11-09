from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, require_role
from ..errors import WMSError
from ..models import InboundLine, InboundOrder, InboundStatus, Item, Role, User
from ..schemas import InboundIn, InboundOut, InboundSummary, Page, ReceiveIn, TaskOut
from ..services import inbound as svc
from ..services.common import get_or_404, next_number
from ._util import like, paginate

router = APIRouter(prefix="/inbound", tags=["inbound / receiving"], dependencies=[Depends(current_user)])


def _with_totals(order: InboundOrder, model=InboundOut):
    out = model.model_validate(order)
    out.qty_expected = sum(l.qty_expected for l in order.lines)
    out.qty_received = sum(l.qty_received for l in order.lines)
    return out


@router.get("", response_model=Page[InboundSummary])
def list_inbound(status: str | None = None, warehouse_id: int | None = None, q: str | None = None,
                 open_only: bool = False, limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(InboundOrder).options(selectinload(InboundOrder.lines), selectinload(InboundOrder.supplier)) \
        .order_by(InboundOrder.id.desc())
    if status:
        stmt = stmt.where(InboundOrder.status == status)
    if open_only:
        stmt = stmt.where(InboundOrder.status.in_((InboundStatus.OPEN, InboundStatus.RECEIVING)))
    if warehouse_id:
        stmt = stmt.where(InboundOrder.warehouse_id == warehouse_id)
    if q:
        stmt = stmt.where(or_(InboundOrder.number.ilike(like(q)), InboundOrder.reference.ilike(like(q))))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_with_totals(r[0], InboundSummary) for r in rows], total=total)


@router.post("", response_model=InboundOut, status_code=201,
             dependencies=[Depends(require_role(Role.SUPERVISOR))])
def create_inbound(body: InboundIn, db: Session = Depends(get_db)):
    order = InboundOrder(number=next_number(db, "inbound"),
                         **body.model_dump(exclude={"lines"}))
    for i, line in enumerate(body.lines, start=1):
        get_or_404(db, Item, line.item_id, "Item")
        order.lines.append(InboundLine(line_no=i, item_id=line.item_id, qty_expected=line.qty_expected))
    db.add(order)
    db.flush()
    return _with_totals(order)


@router.get("/{inbound_id}", response_model=InboundOut)
def get_inbound(inbound_id: int, db: Session = Depends(get_db)):
    return _with_totals(get_or_404(db, InboundOrder, inbound_id, "Receipt"))


@router.post("/{inbound_id}/receive", response_model=TaskOut | None)
def receive(inbound_id: int, body: ReceiveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    order = get_or_404(db, InboundOrder, inbound_id, "Receipt")
    return svc.receive(db, order, body.line_id, body.qty, user.username, location_id=body.location_id,
                       lot=body.lot_number, expiration_date=body.expiration_date,
                       create_putaway=body.create_putaway)


@router.post("/{inbound_id}/lines", response_model=InboundOut,
             dependencies=[Depends(require_role(Role.SUPERVISOR))])
def add_line(inbound_id: int, item_id: int, qty_expected: int, db: Session = Depends(get_db)):
    order = get_or_404(db, InboundOrder, inbound_id, "Receipt")
    if order.status in (InboundStatus.CLOSED, InboundStatus.CANCELLED):
        raise WMSError(f"Receipt is {order.status}")
    if qty_expected <= 0:
        raise WMSError("Quantity must be positive")
    get_or_404(db, Item, item_id, "Item")
    order.lines.append(InboundLine(line_no=len(order.lines) + 1, item_id=item_id, qty_expected=qty_expected))
    db.flush()
    return _with_totals(order)


@router.post("/{inbound_id}/close", response_model=InboundOut, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def close(inbound_id: int, db: Session = Depends(get_db)):
    order = get_or_404(db, InboundOrder, inbound_id, "Receipt")
    svc.close(db, order)
    return _with_totals(order)


@router.post("/{inbound_id}/cancel", response_model=InboundOut, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def cancel(inbound_id: int, db: Session = Depends(get_db)):
    order = get_or_404(db, InboundOrder, inbound_id, "Receipt")
    svc.cancel(db, order)
    return _with_totals(order)
