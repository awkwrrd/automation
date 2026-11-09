"""Bootstrap admin user, and (optionally) a demo warehouse with items, stock and orders."""
import zlib
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import (InboundLine, InboundOrder, Item, Location, LocationType, OutboundLine, OutboundOrder, Role,
                     Supplier, User, Warehouse, Zone, ZoneType)
from .security import hash_password
from .services import inbound, tasks as task_svc
from .services.common import next_number


def seed(db: Session) -> None:
    if not db.scalar(select(User.id).limit(1)):
        db.add(User(username=settings.admin_username, full_name="Administrator", role=Role.ADMIN,
                    password_hash=hash_password(settings.admin_password)))
        db.flush()
    if settings.seed_demo_data and not db.scalar(select(Warehouse.id).limit(1)):
        _demo(db)


def _demo(db: Session) -> None:
    db.add_all([
        User(username="supervisor", full_name="Sam Supervisor", role=Role.SUPERVISOR,
             password_hash=hash_password("supervisor")),
        User(username="operator", full_name="Ola Operator", role=Role.OPERATOR, password_hash=hash_password("operator")),
    ])
    wh = Warehouse(code="DC1", name="Main Distribution Center", address1="100 Commerce Way", city="Columbus",
                   state="OH", postal_code="43004", country="US")
    db.add(wh)
    db.flush()
    zones = {
        code: Zone(warehouse_id=wh.id, code=code, name=name, zone_type=zt)
        for code, name, zt in [
            ("RCV", "Receiving Dock", ZoneType.RECEIVING), ("FWD", "Forward Pick", ZoneType.PICK),
            ("RSV", "Reserve Storage", ZoneType.STORAGE), ("SHP", "Shipping / Staging", ZoneType.SHIPPING),
            ("QA", "Quarantine", ZoneType.QUARANTINE),
        ]
    }
    db.add_all(zones.values())
    db.flush()
    seq = 0

    def loc(code, zone, ltype, pickable=True, aisle=None, bay=None, level=None):
        nonlocal seq
        seq += 10
        l = Location(warehouse_id=wh.id, zone_id=zones[zone].id, code=code, location_type=ltype, pickable=pickable,
                     pick_sequence=seq, aisle=aisle, bay=bay, level=level)
        db.add(l)
        return l

    dock = loc("DOCK-01", "RCV", LocationType.DOCK, pickable=False)
    loc("DOCK-02", "RCV", LocationType.DOCK, pickable=False)
    for aisle in ("A", "B"):
        for bay in range(1, 7):
            for level in range(1, 4):
                loc(f"{aisle}-{bay:02d}-{level:02d}", "FWD", LocationType.BIN, aisle=aisle, bay=f"{bay:02d}",
                    level=f"{level:02d}")
    for bay in range(1, 9):
        for level in range(1, 3):
            loc(f"R-{bay:02d}-{level:02d}", "RSV", LocationType.PALLET, pickable=False, aisle="R",
                bay=f"{bay:02d}", level=f"{level:02d}")
    loc("STAGE-01", "SHP", LocationType.STAGING, pickable=False)
    loc("STAGE-02", "SHP", LocationType.STAGING, pickable=False)
    loc("QA-01", "QA", LocationType.FLOOR, pickable=False)
    db.flush()

    sup1 = Supplier(code="NORTHWIND", name="Northwind Apparel Co.", contact_name="Dana Lee", email="orders@northwind.example")
    sup2 = Supplier(code="ACMEHOME", name="Acme Home Goods", contact_name="Raj Patel", email="sales@acmehome.example")
    db.add_all([sup1, sup2])
    db.flush()

    catalog = [
        ("TS-BLK-S", "Classic Tee - Black / S", "Apparel", sup1, 6.50, 24.00, 0.4, 20, 60),
        ("TS-BLK-M", "Classic Tee - Black / M", "Apparel", sup1, 6.50, 24.00, 0.4, 20, 60),
        ("TS-BLK-L", "Classic Tee - Black / L", "Apparel", sup1, 6.50, 24.00, 0.45, 20, 60),
        ("TS-WHT-M", "Classic Tee - White / M", "Apparel", sup1, 6.50, 24.00, 0.4, 15, 48),
        ("HD-GRY-M", "Pullover Hoodie - Grey / M", "Apparel", sup1, 18.00, 59.00, 1.2, 10, 24),
        ("HD-GRY-L", "Pullover Hoodie - Grey / L", "Apparel", sup1, 18.00, 59.00, 1.3, 10, 24),
        ("CAP-NVY", "Logo Cap - Navy", "Accessories", sup1, 4.25, 22.00, 0.3, 12, 36),
        ("TOTE-NAT", "Canvas Tote - Natural", "Accessories", sup1, 3.10, 18.00, 0.5, 10, 40),
        ("MUG-12OZ", "Ceramic Mug 12oz", "Home", sup2, 2.80, 16.00, 0.9, 24, 72),
        ("CNDL-CED", "Soy Candle - Cedar", "Home", sup2, 5.40, 28.00, 1.0, 12, 36),
        ("CNDL-LAV", "Soy Candle - Lavender", "Home", sup2, 5.40, 28.00, 1.0, 12, 36),
        ("BTL-SS-20", "Insulated Bottle 20oz", "Home", sup2, 7.90, 34.00, 0.8, 10, 30),
        ("STKR-PK", "Sticker Pack", "Accessories", sup1, 0.60, 6.00, 0.05, 50, 200),
        ("PSTR-A3", "Art Print A3", "Home", sup2, 1.90, 25.00, 0.2, 8, 25),
    ]
    items = []
    for sku, name, cat, sup, cost, price, wt, rop, roq in catalog:
        it = Item(sku=sku, name=name, category=cat, supplier_id=sup.id, unit_cost=Decimal(str(cost)),
                  price=Decimal(str(price)), weight=Decimal(str(wt)), reorder_point=rop, reorder_qty=roq,
                  barcode=f"0{zlib.crc32(sku.encode()) % 10**11:011d}")
        items.append(it)
    lot_item = Item(sku="SNK-GRN-BAR", name="Granola Bar (12 ct)", category="Food", supplier_id=sup2.id,
                    unit_cost=Decimal("3.20"), price=Decimal("9.00"), weight=Decimal("0.7"), reorder_point=20,
                    reorder_qty=60, lot_tracked=True, barcode="012345678905")
    items.append(lot_item)
    db.add_all(items)
    db.flush()

    # Receive initial stock through the normal inbound flow so there is an audit trail
    qtys = [40, 55, 38, 12, 22, 9, 30, 25, 80, 14, 6, 18, 150, 30]
    po = InboundOrder(number=next_number(db, "inbound"), warehouse_id=wh.id, supplier_id=sup1.id,
                      reference="PO-10001", expected_date=date.today() - timedelta(days=3))
    for i, (it, q) in enumerate(zip(items[:-1], qtys), start=1):
        po.lines.append(InboundLine(line_no=i, item_id=it.id, qty_expected=q))
    db.add(po)
    db.flush()
    for line in po.lines:
        t = inbound.receive(db, po, line.id, line.qty_expected, "admin", location_id=dock.id)
        if t and t.to_location_id:
            task_svc.complete(db, t, None, "admin")
    po2 = InboundOrder(number=next_number(db, "inbound"), warehouse_id=wh.id, supplier_id=sup2.id,
                       reference="PO-10002", expected_date=date.today())
    po2.lines.append(InboundLine(line_no=1, item_id=lot_item.id, qty_expected=48))
    po2.lines.append(InboundLine(line_no=2, item_id=items[8].id, qty_expected=72))
    po2.lines.append(InboundLine(line_no=3, item_id=items[10].id, qty_expected=36))
    db.add(po2)
    db.flush()
    t = inbound.receive(db, po2, po2.lines[0].id, 24, "admin", location_id=dock.id, lot="LOT-2401",
                        expiration_date=date.today() + timedelta(days=120))
    if t and t.to_location_id:
        task_svc.complete(db, t, None, "admin")
    inbound.receive(db, po2, po2.lines[1].id, 36, "admin", location_id=dock.id)  # leaves an open putaway task

    customers = [
        ("Jordan Smith", "Austin", "TX", [(0, 2), (6, 1)]),
        ("Priya Nair", "Seattle", "WA", [(4, 1)]),
        ("Chris Wong", "Denver", "CO", [(8, 4), (9, 1), (10, 1)]),
        ("Alex Rivera", "Miami", "FL", [(1, 1), (12, 3)]),
        ("Morgan Blake", "Chicago", "IL", [(5, 2)]),
    ]
    for n, (name, city, st, lines) in enumerate(customers):
        o = OutboundOrder(number=next_number(db, "order"), warehouse_id=wh.id, channel="SHOPIFY",
                          external_id=f"#{1001 + n}", customer_name=name, ship_name=name,
                          ship_address1=f"{100 + n * 7} Main St", ship_city=city, ship_state=st,
                          ship_postal_code="00000", ship_country="US", ship_method="Ground")
        for i, (idx, q) in enumerate(lines, start=1):
            o.lines.append(OutboundLine(line_no=i, item_id=items[idx].id, qty_ordered=q))
        db.add(o)
    db.flush()
