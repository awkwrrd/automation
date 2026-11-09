import csv
import io
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user, require_role
from ..models import InventoryBalance, InventoryStatus, Item, Location, LocationType, Role
from ..schemas import ItemIn, ItemOut, Page
from ._util import like, paginate

router = APIRouter(prefix="/items", tags=["items"], dependencies=[Depends(current_user)])
supervisor = Depends(require_role(Role.SUPERVISOR))

CSV_FIELDS = [f for f in ItemIn.model_fields]


def _stock_subquery():
    """On-hand / allocated per item. 'available' = AVAILABLE status, excluding staged (picked) stock."""
    return (
        select(
            InventoryBalance.item_id,
            func.sum(InventoryBalance.qty_on_hand).label("on_hand"),
            func.sum(InventoryBalance.qty_allocated).label("allocated"),
            func.sum(case(
                (and_(InventoryBalance.status == InventoryStatus.AVAILABLE,
                      Location.location_type != LocationType.STAGING),
                 InventoryBalance.qty_on_hand - InventoryBalance.qty_allocated),
                else_=0,
            )).label("available"),
        )
        .join(Location, Location.id == InventoryBalance.location_id)
        .group_by(InventoryBalance.item_id)
        .subquery()
    )


def _out(item: Item, on_hand=0, allocated=0, available=0) -> ItemOut:
    out = ItemOut.model_validate(item)
    out.on_hand, out.allocated, out.available = int(on_hand or 0), int(allocated or 0), int(available or 0)
    return out


@router.get("", response_model=Page[ItemOut])
def list_items(q: str | None = None, category: str | None = None, active: bool | None = None,
               low_stock: bool = False, limit: int = 50, offset: int = 0, sort: str = "sku",
               db: Session = Depends(get_db)):
    s = _stock_subquery()
    stmt = (select(Item, s.c.on_hand, s.c.allocated, s.c.available)
            .outerjoin(s, s.c.item_id == Item.id).options(joinedload(Item.default_location)))
    if q:
        t = like(q)
        stmt = stmt.where(or_(Item.sku.ilike(t), Item.name.ilike(t), Item.barcode.ilike(t),
                              Item.shopify_variant_id == q.strip()))
    if category:
        stmt = stmt.where(Item.category == category)
    if active is not None:
        stmt = stmt.where(Item.active.is_(active))
    if low_stock:
        stmt = stmt.where(Item.reorder_point > 0, func.coalesce(s.c.available, 0) <= Item.reorder_point)
    order = {"sku": Item.sku, "name": Item.name, "-updated": Item.updated_at.desc(),
             "available": func.coalesce(s.c.available, 0)}.get(sort, Item.sku)
    rows, total = paginate(db, stmt.order_by(order), limit, offset)
    return Page(items=[_out(*r) for r in rows], total=total)


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    return [c for c in db.scalars(select(Item.category).where(Item.category.is_not(None)).distinct().order_by(Item.category))]


@router.get("/lookup", response_model=ItemOut)
def lookup(code: str, db: Session = Depends(get_db)):
    """Scan lookup by SKU or barcode."""
    c = code.strip()
    item = db.scalar(select(Item).where(or_(func.upper(Item.sku) == c.upper(), Item.barcode == c)))
    if not item:
        raise HTTPException(404, f"No item with SKU/barcode {code}")
    return get_item(item.id, db)


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for item in db.scalars(select(Item).order_by(Item.sku)):
        w.writerow({f: getattr(item, f) for f in CSV_FIELDS})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=items.csv"})


@router.post("/import", dependencies=[supervisor])
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upsert items by SKU from a CSV (same columns as the export; only `sku` and `name` required)."""
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "sku" not in reader.fieldnames:
        raise HTTPException(422, "CSV must have a 'sku' column")
    created = updated = 0
    errors: list[str] = []
    for n, row in enumerate(reader, start=2):
        data = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k in CSV_FIELDS}
        data = {k: (None if v == "" else v) for k, v in data.items()}
        if not data.get("sku"):
            errors.append(f"row {n}: missing sku")
            continue
        for b in ("lot_tracked", "active"):
            if b in data and data[b] is not None:
                data[b] = str(data[b]).lower() in ("1", "true", "yes", "y")
        try:
            for dec in ("unit_cost", "price", "weight", "length", "width", "height"):
                if data.get(dec) is not None:
                    data[dec] = Decimal(str(data[dec]))
            for i in ("reorder_point", "reorder_qty", "supplier_id", "default_location_id"):
                if data.get(i) is not None:
                    data[i] = int(data[i])
        except (InvalidOperation, ValueError) as e:
            errors.append(f"row {n}: {e}")
            continue
        item = db.scalar(select(Item).where(Item.sku == data["sku"]))
        if item:
            for k, v in data.items():
                if v is not None:
                    setattr(item, k, v)
            updated += 1
        else:
            if not data.get("name"):
                errors.append(f"row {n}: name required for new SKU {data['sku']}")
                continue
            payload = ItemIn(**{k: v for k, v in data.items() if v is not None})
            db.add(Item(**payload.model_dump()))
            created += 1
    db.flush()
    return {"created": created, "updated": updated, "errors": errors[:100]}


@router.get("/{item_id}", response_model=ItemOut)
def get_item(item_id: int, db: Session = Depends(get_db)):
    s = _stock_subquery()
    row = db.execute(select(Item, s.c.on_hand, s.c.allocated, s.c.available)
                     .outerjoin(s, s.c.item_id == Item.id).where(Item.id == item_id)).first()
    if not row:
        raise HTTPException(404, "Item not found")
    return _out(*row)


@router.post("", response_model=ItemOut, status_code=201, dependencies=[supervisor])
def create_item(body: ItemIn, db: Session = Depends(get_db)):
    item = Item(**body.model_dump())
    try:
        db.add(item)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"SKU {body.sku} already exists")
    return _out(item)


@router.put("/{item_id}", response_model=ItemOut, dependencies=[supervisor])
def update_item(item_id: int, body: ItemIn, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"SKU {body.sku} already exists")
    return get_item(item_id, db)
