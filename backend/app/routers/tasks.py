from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user, require_role
from ..errors import WMSError
from ..models import Item, Location, Role, Task, TaskStatus, TaskType, User
from ..schemas import MoveTaskIn, Page, TaskAssignIn, TaskCompleteIn, TaskOut
from ..services import tasks as svc
from ..services.common import get_or_404
from ..services.inbound import suggest_putaway_location
from ..services.inventory import get_balance
from ._util import like, paginate

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(current_user)])


@router.get("", response_model=Page[TaskOut])
def list_tasks(status: str | None = None, task_type: str | None = None, warehouse_id: int | None = None,
               assigned_to: str | None = None, wave_id: int | None = None, order_id: int | None = None,
               q: str | None = None, open_only: bool = False, limit: int = 100, offset: int = 0,
               db: Session = Depends(get_db)):
    fl = Location.__table__.alias("fl")
    stmt = (select(Task).join(Item, Item.id == Task.item_id)
            .outerjoin(fl, fl.c.id == Task.from_location_id)
            .options(joinedload(Task.item), joinedload(Task.from_location), joinedload(Task.to_location)))
    if open_only:
        stmt = stmt.where(Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)))
        stmt = stmt.order_by(Task.priority, fl.c.pick_sequence, Task.id)  # walk-path order
    else:
        stmt = stmt.order_by(Task.id.desc())
    if status:
        stmt = stmt.where(Task.status == status)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    if warehouse_id:
        stmt = stmt.where(Task.warehouse_id == warehouse_id)
    if assigned_to:
        stmt = stmt.where(Task.assigned_to == assigned_to)
    if wave_id:
        stmt = stmt.where(Task.wave_id == wave_id)
    if order_id:
        stmt = stmt.where(Task.order_id == order_id)
    if q:
        t = like(q)
        stmt = stmt.where(or_(Item.sku.ilike(t), Task.reference_number.ilike(t), fl.c.code.ilike(t)))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[r[0] for r in rows], total=total)


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Task, task_id, "Task")


@router.post("/{task_id}/complete", response_model=TaskOut)
def complete(task_id: int, body: TaskCompleteIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = get_or_404(db, Task, task_id, "Task")
    svc.complete(db, task, body.qty, user.username, body.to_location_id)
    db.flush()
    db.refresh(task)
    return task


@router.post("/{task_id}/assign", response_model=TaskOut)
def assign(task_id: int, body: TaskAssignIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = get_or_404(db, Task, task_id, "Task")
    if task.status not in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS):
        raise WMSError(f"Task is {task.status}")
    task.assigned_to = body.assigned_to
    return task


@router.post("/{task_id}/cancel", response_model=TaskOut, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def cancel(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = get_or_404(db, Task, task_id, "Task")
    svc.cancel(db, task, user.username)
    return task


@router.post("", response_model=TaskOut, status_code=201, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def create_move_task(body: MoveTaskIn, db: Session = Depends(get_db)):
    """Create a manual move / replenishment task for a floor operator."""
    if body.task_type == TaskType.PICK:
        raise WMSError("Pick tasks are created by releasing orders")
    src = get_or_404(db, Location, body.from_location_id, "Location")
    item = get_or_404(db, Item, body.item_id, "Item")
    bal = get_balance(db, item.id, src.id, body.lot_number)
    if not bal or bal.qty_available < body.qty:
        raise WMSError(f"Only {bal.qty_available if bal else 0} available at {src.code}")
    dest_id = body.to_location_id
    if dest_id is None:
        target = suggest_putaway_location(db, item, src.warehouse_id, exclude_id=src.id)
        dest_id = target.id if target else None
    task = Task(task_type=body.task_type, warehouse_id=src.warehouse_id, item_id=item.id,
                lot_number=body.lot_number, qty=body.qty, from_location_id=src.id, to_location_id=dest_id,
                priority=body.priority)
    db.add(task)
    db.flush()
    return task
