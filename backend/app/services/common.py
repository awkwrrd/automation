from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Base
from ..errors import NotFound
from ..models import Location, LocationType, NumberSequence

T = TypeVar("T", bound=Base)

PREFIXES = {
    "inbound": "RCV",
    "order": "ORD",
    "wave": "WAV",
    "shipment": "SHP",
    "count": "CC",
}


def next_number(db: Session, kind: str) -> str:
    seq = db.execute(
        select(NumberSequence).where(NumberSequence.name == kind).with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = NumberSequence(name=kind, next_value=1)
        db.add(seq)
        db.flush()
    value = seq.next_value
    seq.next_value = value + 1
    return f"{PREFIXES.get(kind, kind.upper()[:3])}{value:06d}"


def get_or_404(db: Session, model: type[T], obj_id: int, label: str | None = None) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise NotFound(label or model.__name__)
    return obj


def first_location_of_type(db: Session, warehouse_id: int, loc_type: LocationType) -> Location | None:
    return db.scalar(
        select(Location)
        .where(Location.warehouse_id == warehouse_id, Location.location_type == loc_type, Location.active.is_(True))
        .order_by(Location.pick_sequence, Location.code)
        .limit(1)
    )
