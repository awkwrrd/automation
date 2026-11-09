"""WMS data model.

Enumerated values are stored as plain strings (not native DB enums) so the schema
stays portable across PostgreSQL / MySQL / SQL Server / SQLite.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- enums
class Role(StrEnum):
    ADMIN = "ADMIN"            # everything incl. users & configuration
    SUPERVISOR = "SUPERVISOR"  # adjustments, count approval, order/wave control
    OPERATOR = "OPERATOR"      # receive, putaway, pick, pack, ship, move


class ZoneType(StrEnum):
    RECEIVING = "RECEIVING"
    STORAGE = "STORAGE"
    PICK = "PICK"
    PACK = "PACK"
    SHIPPING = "SHIPPING"
    QUARANTINE = "QUARANTINE"


class LocationType(StrEnum):
    BIN = "BIN"
    SHELF = "SHELF"
    PALLET = "PALLET"
    FLOOR = "FLOOR"
    DOCK = "DOCK"        # inbound dock / receiving stage
    STAGING = "STAGING"  # outbound staging (picked, awaiting ship)


class InventoryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    HOLD = "HOLD"
    DAMAGED = "DAMAGED"
    QUARANTINE = "QUARANTINE"


class TxnType(StrEnum):
    RECEIVE = "RECEIVE"
    PUTAWAY = "PUTAWAY"
    MOVE = "MOVE"
    ADJUST = "ADJUST"
    STATUS = "STATUS"
    ALLOCATE = "ALLOCATE"
    DEALLOCATE = "DEALLOCATE"
    PICK = "PICK"
    SHIP = "SHIP"
    COUNT = "COUNT"


class InboundStatus(StrEnum):
    OPEN = "OPEN"
    RECEIVING = "RECEIVING"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class InboundType(StrEnum):
    PO = "PO"
    ASN = "ASN"
    RETURN = "RETURN"


class OrderStatus(StrEnum):
    NEW = "NEW"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AllocationStatus(StrEnum):
    OPEN = "OPEN"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class WaveStatus(StrEnum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class TaskType(StrEnum):
    PUTAWAY = "PUTAWAY"
    PICK = "PICK"
    MOVE = "MOVE"
    REPLENISH = "REPLENISH"


class TaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ShipmentStatus(StrEnum):
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"


class IntegrationEvent(StrEnum):
    WAVE_RELEASED = "wave.released"      # a wave was released: its pick tasks
    ORDER_RELEASED = "order.released"    # a single order released outside a wave
    PUTAWAY_CREATED = "putaway.created"  # receiving created a putaway task
    TASK_CANCELLED = "task.cancelled"    # a task previously sent to the endpoint was cancelled
    TEST = "test"                        # manual connectivity test from the GUI


class MessageStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuthType(StrEnum):
    NONE = "NONE"
    BEARER = "BEARER"   # Authorization: Bearer <value>
    BASIC = "BASIC"     # value = "user:password"
    HEADER = "HEADER"   # <auth_header>: <value>, e.g. X-API-Key


class PayloadFormat(StrEnum):
    STANDARD = "STANDARD"  # one message per event, snake_case, nested under "data"
    ORDER = "ORDER"        # one flat PascalCase message per order (Lines[], UnitType, Category ...)


# Suggested values (free text is allowed; receivers usually compare case-insensitively)
UNIT_TYPES = ["EACH", "LINEAR", "AREA", "VOLUME", "WEIGHT", "CASE", "PALLET"]
ORDER_CATEGORIES = ["STANDARD", "CONSOLIDATION", "EXPEDITED", "WHOLESALE", "REPLACEMENT", "SAMPLE"]


class CountStatus(StrEnum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


ENUM_LEN = 24


# --------------------------------------------------------------------------- core / admin
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(ENUM_LEN), default=Role.OPERATOR)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NumberSequence(Base):
    """Document number generator (RCV000001, ORD000001, ...)."""
    __tablename__ = "number_sequences"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1)


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    address1: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str | None] = mapped_column(String(64))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Shopify "location" this warehouse maps to (used by the integration stage)
    shopify_location_id: Mapped[str | None] = mapped_column(String(64))

    zones: Mapped[list[Zone]] = relationship(back_populates="warehouse")


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("warehouse_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    zone_type: Mapped[str] = mapped_column(String(ENUM_LEN), default=ZoneType.STORAGE)

    warehouse: Mapped[Warehouse] = relationship(back_populates="zones")


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"))
    code: Mapped[str] = mapped_column(String(32))
    aisle: Mapped[str | None] = mapped_column(String(8))
    bay: Mapped[str | None] = mapped_column(String(8))
    level: Mapped[str | None] = mapped_column(String(8))
    position: Mapped[str | None] = mapped_column(String(8))
    location_type: Mapped[str] = mapped_column(String(ENUM_LEN), default=LocationType.BIN)
    pickable: Mapped[bool] = mapped_column(Boolean, default=True)
    pick_sequence: Mapped[int] = mapped_column(Integer, default=0)
    max_units: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    warehouse: Mapped[Warehouse] = relationship()
    zone: Mapped[Zone | None] = relationship()


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    contact_name: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- items & inventory
class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str | None] = mapped_column(String(128))
    brand: Mapped[str | None] = mapped_column(String(128))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    uom: Mapped[str] = mapped_column(String(16), default="EA")
    # how the item is measured/handled downstream, e.g. EACH or LINEAR (sold by length)
    unit_type: Mapped[str | None] = mapped_column(String(24), default="EACH")
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    weight_unit: Mapped[str] = mapped_column(String(8), default="lb")
    length: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dim_unit: Mapped[str] = mapped_column(String(8), default="in")
    reorder_point: Mapped[int] = mapped_column(Integer, default=0)
    reorder_qty: Mapped[int] = mapped_column(Integer, default=0)
    lot_tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    default_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    image_url: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Shopify identifiers (populated by the integration stage)
    shopify_product_id: Mapped[str | None] = mapped_column(String(64), index=True)
    shopify_variant_id: Mapped[str | None] = mapped_column(String(64), index=True)
    shopify_inventory_item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    supplier: Mapped[Supplier | None] = relationship()
    default_location: Mapped[Location | None] = relationship()


class InventoryBalance(Base):
    """Quantity of an item in a location, per lot and inventory status."""
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id", "lot_number", "status", name="uq_balance_key"),
        Index("ix_balance_location", "location_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    lot_number: Mapped[str] = mapped_column(String(64), default="")  # "" = no lot
    expiration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=InventoryStatus.AVAILABLE)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    qty_allocated: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship()
    location: Mapped[Location] = relationship()

    @property
    def qty_available(self) -> int:
        return self.qty_on_hand - self.qty_allocated


class InventoryTransaction(Base):
    """Immutable audit trail of every inventory movement."""
    __tablename__ = "inventory_transactions"
    __table_args__ = (Index("ix_txn_item_created", "item_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    txn_type: Mapped[str] = mapped_column(String(ENUM_LEN), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    from_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    lot_number: Mapped[str] = mapped_column(String(64), default="")
    qty: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str | None] = mapped_column(String(ENUM_LEN))
    to_status: Mapped[str | None] = mapped_column(String(ENUM_LEN))
    reason_code: Mapped[str | None] = mapped_column(String(32))
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_number: Mapped[str | None] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship()
    from_location: Mapped[Location | None] = relationship(foreign_keys=[from_location_id])
    to_location: Mapped[Location | None] = relationship(foreign_keys=[to_location_id])


# --------------------------------------------------------------------------- inbound
class InboundOrder(Base):
    """Purchase order / ASN / customer return expected at the dock."""
    __tablename__ = "inbound_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    order_type: Mapped[str] = mapped_column(String(ENUM_LEN), default=InboundType.PO)
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=InboundStatus.OPEN, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    reference: Mapped[str | None] = mapped_column(String(64))
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    warehouse: Mapped[Warehouse] = relationship()
    supplier: Mapped[Supplier | None] = relationship()
    lines: Mapped[list[InboundLine]] = relationship(
        back_populates="inbound", cascade="all, delete-orphan", order_by="InboundLine.line_no"
    )


class InboundLine(Base):
    __tablename__ = "inbound_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    inbound_id: Mapped[int] = mapped_column(ForeignKey("inbound_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty_expected: Mapped[int] = mapped_column(Integer)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)

    inbound: Mapped[InboundOrder] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()


# --------------------------------------------------------------------------- outbound
class Wave(Base):
    __tablename__ = "waves"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=WaveStatus.PLANNED)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime)

    orders: Mapped[list[OutboundOrder]] = relationship(back_populates="wave")


class OutboundOrder(Base):
    """Customer / sales order to be fulfilled (e.g. a Shopify order)."""
    __tablename__ = "outbound_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(64), index=True)  # e.g. Shopify order id
    channel: Mapped[str] = mapped_column(String(32), default="MANUAL")
    category: Mapped[str | None] = mapped_column(String(32), default="STANDARD")  # e.g. CONSOLIDATION
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=OrderStatus.NEW, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 = highest
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    wave_id: Mapped[int | None] = mapped_column(ForeignKey("waves.id"))
    customer_name: Mapped[str | None] = mapped_column(String(255))
    customer_email: Mapped[str | None] = mapped_column(String(255))
    customer_phone: Mapped[str | None] = mapped_column(String(64))
    ship_name: Mapped[str | None] = mapped_column(String(255))
    ship_address1: Mapped[str | None] = mapped_column(String(255))
    ship_address2: Mapped[str | None] = mapped_column(String(255))
    ship_city: Mapped[str | None] = mapped_column(String(128))
    ship_state: Mapped[str | None] = mapped_column(String(64))
    ship_postal_code: Mapped[str | None] = mapped_column(String(32))
    ship_country: Mapped[str | None] = mapped_column(String(64))
    ship_method: Mapped[str | None] = mapped_column(String(64))
    requested_ship_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)

    warehouse: Mapped[Warehouse] = relationship()
    wave: Mapped[Wave | None] = relationship(back_populates="orders")
    lines: Mapped[list[OutboundLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OutboundLine.line_no"
    )
    shipments: Mapped[list[Shipment]] = relationship(back_populates="order")


class OutboundLine(Base):
    __tablename__ = "outbound_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("outbound_orders.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    external_line_id: Mapped[str | None] = mapped_column(String(64))
    qty_ordered: Mapped[int] = mapped_column(Integer)
    qty_allocated: Mapped[int] = mapped_column(Integer, default=0)
    qty_picked: Mapped[int] = mapped_column(Integer, default=0)
    qty_shipped: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped[OutboundOrder] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()
    allocations: Mapped[list[Allocation]] = relationship(back_populates="line")


class Allocation(Base):
    """Reservation of specific inventory (location + lot) against an order line."""
    __tablename__ = "allocations"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_line_id: Mapped[int] = mapped_column(ForeignKey("outbound_lines.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    lot_number: Mapped[str] = mapped_column(String(64), default="")
    qty: Mapped[int] = mapped_column(Integer)
    qty_picked: Mapped[int] = mapped_column(Integer, default=0)
    staged_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=AllocationStatus.OPEN)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    line: Mapped[OutboundLine] = relationship(back_populates="allocations")
    location: Mapped[Location] = relationship(foreign_keys=[location_id])


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("outbound_orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=ShipmentStatus.PACKED)
    carrier: Mapped[str | None] = mapped_column(String(64))
    service: Mapped[str | None] = mapped_column(String(64))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    packages: Mapped[int] = mapped_column(Integer, default=1)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    packed_by: Mapped[str | None] = mapped_column(String(64))
    packed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime)

    order: Mapped[OutboundOrder] = relationship(back_populates="shipments")


# --------------------------------------------------------------------------- tasks
class Task(Base):
    """Unit of work for the floor: putaway, pick, move, replenishment."""
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_task_status_type", "status", "task_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_type: Mapped[str] = mapped_column(String(ENUM_LEN))
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=TaskStatus.OPEN)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    lot_number: Mapped[str] = mapped_column(String(64), default="")
    qty: Mapped[int] = mapped_column(Integer)
    qty_done: Mapped[int] = mapped_column(Integer, default=0)
    from_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    inbound_line_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_lines.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("outbound_orders.id"), index=True)
    allocation_id: Mapped[int | None] = mapped_column(ForeignKey("allocations.id"))
    wave_id: Mapped[int | None] = mapped_column(ForeignKey("waves.id"))
    reference_number: Mapped[str | None] = mapped_column(String(64))
    assigned_to: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(String(64))
    # integration endpoint (e.g. a robotics platform) this task was dispatched to
    dispatch_endpoint_id: Mapped[int | None] = mapped_column(Integer, index=True)

    item: Mapped[Item] = relationship()
    from_location: Mapped[Location | None] = relationship(foreign_keys=[from_location_id])
    to_location: Mapped[Location | None] = relationship(foreign_keys=[to_location_id])
    allocation: Mapped[Allocation | None] = relationship()


# --------------------------------------------------------------------------- cycle counts
class CycleCount(Base):
    __tablename__ = "cycle_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=CountStatus.OPEN)
    description: Mapped[str | None] = mapped_column(String(255))
    blind: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    lines: Mapped[list[CycleCountLine]] = relationship(
        back_populates="count", cascade="all, delete-orphan", order_by="CycleCountLine.id"
    )


class CycleCountLine(Base):
    __tablename__ = "cycle_count_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("cycle_counts.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    lot_number: Mapped[str] = mapped_column(String(64), default="")
    inv_status: Mapped[str] = mapped_column(String(ENUM_LEN), default=InventoryStatus.AVAILABLE)
    expected_qty: Mapped[int] = mapped_column(Integer, default=0)
    counted_qty: Mapped[int | None] = mapped_column(Integer)
    adjusted_qty: Mapped[int | None] = mapped_column(Integer)
    counted_by: Mapped[str | None] = mapped_column(String(64))
    counted_at: Mapped[datetime | None] = mapped_column(DateTime)

    count: Mapped[CycleCount] = relationship(back_populates="lines")
    location: Mapped[Location] = relationship()
    item: Mapped[Item] = relationship()


# --------------------------------------------------------------------------- integrations
class IntegrationEndpoint(Base):
    """An external system (robotics platform, WCS, ERP...) the WMS pushes events to."""
    __tablename__ = "integration_endpoints"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(1024))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))  # None = all warehouses
    events: Mapped[str] = mapped_column(Text, default="")       # comma-separated IntegrationEvent values
    zone_ids: Mapped[str | None] = mapped_column(Text)           # comma-separated; None = all zones
    auth_type: Mapped[str] = mapped_column(String(16), default=AuthType.NONE)
    auth_header: Mapped[str | None] = mapped_column(String(64))
    auth_value: Mapped[str | None] = mapped_column(Text)
    signing_secret: Mapped[str | None] = mapped_column(String(128))
    extra_headers: Mapped[str | None] = mapped_column(Text)      # JSON object
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=10)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    assign_tasks: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # message shape (nullable so existing databases upgrade in place; None = STANDARD)
    payload_format: Mapped[str | None] = mapped_column(String(16), default=PayloadFormat.STANDARD)
    field_names: Mapped[str | None] = mapped_column(Text)    # JSON {"OldKey": "NewKey"} renames, any depth
    static_fields: Mapped[str | None] = mapped_column(Text)  # JSON object merged into every message

    @property
    def event_list(self) -> list[str]:
        return [e for e in (self.events or "").split(",") if e]

    @property
    def zone_id_list(self) -> list[int]:
        return [int(z) for z in (self.zone_ids or "").split(",") if z.strip()]


class OutboundMessage(Base):
    """Transactional outbox: written with the business change, delivered by the dispatcher."""
    __tablename__ = "outbound_messages"
    __table_args__ = (Index("ix_outbox_status_endpoint", "status", "endpoint_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(ForeignKey("integration_endpoints.id"), index=True)
    event: Mapped[str] = mapped_column(String(48))
    reference: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(ENUM_LEN), default=MessageStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    endpoint: Mapped[IntegrationEndpoint] = relationship()


class ApiKey(Base):
    """Long-lived credential for system-to-system calls; acts as the linked user."""
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship()
