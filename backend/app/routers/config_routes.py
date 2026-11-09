"""Warehouses, zones, locations, suppliers."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user, require_role
from ..models import InventoryBalance, Location, Role, Supplier, Warehouse, Zone
from ..schemas import (
    LocationGenerateIn, LocationIn, LocationOut, Page, SupplierIn, SupplierOut,
    WarehouseIn, WarehouseOut, ZoneIn, ZoneOut,
)
from ._util import like, paginate

router = APIRouter(tags=["configuration"], dependencies=[Depends(current_user)])
admin = Depends(require_role(Role.ADMIN))


def _save(db: Session, obj):
    try:
        db.add(obj)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A record with that code already exists")
    return obj


def _update(db: Session, model, obj_id: int, body):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    return _save(db, obj)


# warehouses
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(db: Session = Depends(get_db)):
    return db.scalars(select(Warehouse).order_by(Warehouse.code)).all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=201, dependencies=[admin])
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db)):
    return _save(db, Warehouse(**body.model_dump()))


@router.put("/warehouses/{wid}", response_model=WarehouseOut, dependencies=[admin])
def update_warehouse(wid: int, body: WarehouseIn, db: Session = Depends(get_db)):
    return _update(db, Warehouse, wid, body)


# zones
@router.get("/zones", response_model=list[ZoneOut])
def list_zones(warehouse_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Zone).order_by(Zone.code)
    if warehouse_id:
        q = q.where(Zone.warehouse_id == warehouse_id)
    return db.scalars(q).all()


@router.post("/zones", response_model=ZoneOut, status_code=201, dependencies=[admin])
def create_zone(body: ZoneIn, db: Session = Depends(get_db)):
    return _save(db, Zone(**body.model_dump()))


@router.put("/zones/{zid}", response_model=ZoneOut, dependencies=[admin])
def update_zone(zid: int, body: ZoneIn, db: Session = Depends(get_db)):
    return _update(db, Zone, zid, body)


# locations
def _loc_out(loc: Location, units: int | None) -> LocationOut:
    out = LocationOut.model_validate(loc)
    out.units = int(units or 0)
    return out


@router.get("/locations", response_model=Page[LocationOut])
def list_locations(warehouse_id: int | None = None, zone_id: int | None = None, location_type: str | None = None,
                   q: str | None = None, active: bool | None = None, empty: bool | None = None,
                   limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    units = (select(InventoryBalance.location_id, func.sum(InventoryBalance.qty_on_hand).label("units"))
             .group_by(InventoryBalance.location_id).subquery())
    stmt = (select(Location, units.c.units).outerjoin(units, units.c.location_id == Location.id)
            .options(joinedload(Location.zone)).order_by(Location.pick_sequence, Location.code))
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if zone_id:
        stmt = stmt.where(Location.zone_id == zone_id)
    if location_type:
        stmt = stmt.where(Location.location_type == location_type)
    if active is not None:
        stmt = stmt.where(Location.active.is_(active))
    if empty is True:
        stmt = stmt.where(or_(units.c.units.is_(None), units.c.units == 0))
    elif empty is False:
        stmt = stmt.where(units.c.units > 0)
    if q:
        stmt = stmt.where(Location.code.ilike(like(q)))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_loc_out(loc, u) for loc, u in rows], total=total)


@router.get("/locations/lookup", response_model=LocationOut)
def lookup_location(code: str, warehouse_id: int | None = None, db: Session = Depends(get_db)):
    q = select(Location).where(func.upper(Location.code) == code.strip().upper())
    if warehouse_id:
        q = q.where(Location.warehouse_id == warehouse_id)
    loc = db.scalars(q).first()
    if not loc:
        raise HTTPException(404, f"Location {code} not found")
    return _loc_out(loc, None)


@router.post("/locations", response_model=LocationOut, status_code=201, dependencies=[admin])
def create_location(body: LocationIn, db: Session = Depends(get_db)):
    return _loc_out(_save(db, Location(**body.model_dump())), 0)


@router.put("/locations/{lid}", response_model=LocationOut, dependencies=[admin])
def update_location(lid: int, body: LocationIn, db: Session = Depends(get_db)):
    return _loc_out(_update(db, Location, lid, body), None)


@router.post("/locations/generate", dependencies=[admin])
def generate_locations(body: LocationGenerateIn, db: Session = Depends(get_db)):
    existing = set(db.scalars(select(Location.code).where(Location.warehouse_id == body.warehouse_id)))
    max_seq = db.scalar(select(func.max(Location.pick_sequence)).where(
        Location.warehouse_id == body.warehouse_id)) or 0
    created = skipped = 0
    for aisle in body.aisles:
        for bay in range(body.bay_from, body.bay_to + 1):
            for level in range(body.level_from, body.level_to + 1):
                try:
                    code = body.pattern.format(aisle=aisle.strip(), bay=bay, level=level)
                except (KeyError, ValueError) as e:
                    raise HTTPException(422, f"Bad pattern: {e}")
                if code in existing:
                    skipped += 1
                    continue
                max_seq += 10
                db.add(Location(
                    warehouse_id=body.warehouse_id, zone_id=body.zone_id, code=code, aisle=aisle.strip(),
                    bay=f"{bay:02d}", level=f"{level:02d}", location_type=body.location_type,
                    pickable=body.pickable, pick_sequence=max_seq,
                ))
                existing.add(code)
                created += 1
    if created > 5000:
        raise HTTPException(422, "Refusing to create more than 5000 locations at once")
    db.flush()
    return {"created": created, "skipped_existing": skipped}


# suppliers
@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(db: Session = Depends(get_db)):
    return db.scalars(select(Supplier).order_by(Supplier.name)).all()


@router.post("/suppliers", response_model=SupplierOut, status_code=201,
             dependencies=[Depends(require_role(Role.SUPERVISOR))])
def create_supplier(body: SupplierIn, db: Session = Depends(get_db)):
    return _save(db, Supplier(**body.model_dump()))


@router.put("/suppliers/{sid}", response_model=SupplierOut, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def update_supplier(sid: int, body: SupplierIn, db: Session = Depends(get_db)):
    return _update(db, Supplier, sid, body)
