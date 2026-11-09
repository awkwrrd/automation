from sqlalchemy.orm import Session

from ..errors import WMSError
from ..models import Location, Task, TaskStatus, TaskType, TxnType, utcnow
from . import integrations, inventory, outbound


def complete(db: Session, task: Task, qty: int | None, username: str, to_location_id: int | None = None) -> None:
    if task.status not in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS):
        raise WMSError(f"Task is {task.status}")
    remaining = task.qty - task.qty_done
    qty = remaining if qty is None else qty

    if task.task_type == TaskType.PICK:
        outbound.complete_pick(db, task, qty, username, to_location_id)
        return

    # putaway / move / replenish are all location-to-location moves
    dest_id = to_location_id or task.to_location_id
    if dest_id is None:
        raise WMSError("Choose a destination location")
    dest = db.get(Location, dest_id)
    if dest is None or dest.warehouse_id != task.warehouse_id:
        raise WMSError("Invalid destination location")
    if qty <= 0 or qty > remaining:
        raise WMSError(f"Quantity must be between 1 and {remaining}")
    txn = {TaskType.PUTAWAY: TxnType.PUTAWAY}.get(TaskType(task.task_type), TxnType.MOVE)
    inventory.move(
        db, item_id=task.item_id, from_location_id=task.from_location_id, to_location_id=dest.id,
        qty=qty, username=username, lot=task.lot_number, txn_type=txn,
        reference_type="TASK", reference_number=task.reference_number or str(task.id),
    )
    task.qty_done += qty
    task.to_location_id = dest.id
    if task.qty_done >= task.qty:
        task.status = TaskStatus.COMPLETE
        task.completed_at = utcnow()
        task.completed_by = username
    else:
        task.status = TaskStatus.IN_PROGRESS


def cancel(db: Session, task: Task, username: str) -> None:
    if task.status not in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS):
        raise WMSError(f"Task is {task.status}")
    if task.task_type == TaskType.PICK:
        # cancelling a pick == confirming zero picked: releases the reservation
        outbound.complete_pick(db, task, 0, username)
        task.status = TaskStatus.CANCELLED
    else:
        task.status = TaskStatus.CANCELLED
        task.completed_at = utcnow()
        task.completed_by = username
    integrations.emit_tasks_cancelled(db, [task], f"Task {task.id} cancelled by {username}")
