from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user, require_role
from ..models import CountStatus, CycleCount, Role, User
from ..schemas import CountEntryIn, CountIn, CountOut, CountSummary, Page
from ..services import counts as svc
from ..services.common import get_or_404
from ._util import paginate

router = APIRouter(prefix="/counts", tags=["cycle counts"], dependencies=[Depends(current_user)])


def _out(count: CycleCount, model=CountOut, hide_expected: bool = False):
    out = model.model_validate(count)
    out.line_count = len(count.lines)
    out.counted_lines = sum(1 for l in count.lines if l.counted_qty is not None)
    if hide_expected and isinstance(out, CountOut) and count.blind and count.status == CountStatus.OPEN:
        for line in out.lines:
            line.expected_qty = None
    return out


@router.get("", response_model=Page[CountSummary])
def list_counts(status: str | None = None, warehouse_id: int | None = None, limit: int = 50, offset: int = 0,
                db: Session = Depends(get_db)):
    stmt = select(CycleCount).options(selectinload(CycleCount.lines)).order_by(CycleCount.id.desc())
    if status:
        stmt = stmt.where(CycleCount.status == status)
    if warehouse_id:
        stmt = stmt.where(CycleCount.warehouse_id == warehouse_id)
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_out(r[0], CountSummary) for r in rows], total=total)


@router.post("", response_model=CountOut, status_code=201)
def create_count(body: CountIn, db: Session = Depends(get_db), user: User = Depends(require_role(Role.SUPERVISOR))):
    count = svc.create(db, body.warehouse_id, user.username, location_ids=body.location_ids, zone_id=body.zone_id,
                       item_id=body.item_id, description=body.description, blind=body.blind)
    return _out(count)


@router.get("/{count_id}", response_model=CountOut)
def get_count(count_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _out(get_or_404(db, CycleCount, count_id, "Count"), hide_expected=user.role == Role.OPERATOR)


@router.post("/{count_id}/record", response_model=CountOut)
def record(count_id: int, entries: list[CountEntryIn], db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    count = get_or_404(db, CycleCount, count_id, "Count")
    svc.record(db, count, [e.model_dump() for e in entries], user.username)
    db.refresh(count)
    return _out(count, hide_expected=user.role == Role.OPERATOR)


@router.post("/{count_id}/complete", response_model=CountOut)
def complete(count_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(Role.SUPERVISOR))):
    count = get_or_404(db, CycleCount, count_id, "Count")
    svc.complete(db, count, user.username)
    return _out(count)


@router.post("/{count_id}/cancel", response_model=CountOut)
def cancel(count_id: int, db: Session = Depends(get_db), _: User = Depends(require_role(Role.SUPERVISOR))):
    count = get_or_404(db, CycleCount, count_id, "Count")
    if count.status == CountStatus.OPEN:
        count.status = CountStatus.CANCELLED
    return _out(count)
