from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    InboundType,
    InventoryStatus,
    LocationType,
    Role,
    TaskType,
    ZoneType,
)

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class Ref(ORM):
    id: int
    code: str


class ItemRef(ORM):
    id: int
    sku: str
    name: str


# ------------------------------------------------------------------ auth / users
class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    email: str | None
    role: str
    active: bool


class LoginOut(BaseModel):
    token: str
    user: UserOut


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    full_name: str = ""
    email: str | None = None
    role: Role = Role.OPERATOR
    active: bool = True
    password: str | None = None


# ------------------------------------------------------------------ config
class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str
    address1: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    active: bool = True
    shopify_location_id: str | None = None


class WarehouseOut(ORM, WarehouseIn):
    id: int


class ZoneIn(BaseModel):
    warehouse_id: int
    code: str = Field(min_length=1, max_length=16)
    name: str
    zone_type: ZoneType = ZoneType.STORAGE


class ZoneOut(ORM, ZoneIn):
    id: int


class LocationIn(BaseModel):
    warehouse_id: int
    zone_id: int | None = None
    code: str = Field(min_length=1, max_length=32)
    aisle: str | None = None
    bay: str | None = None
    level: str | None = None
    position: str | None = None
    location_type: LocationType = LocationType.BIN
    pickable: bool = True
    pick_sequence: int = 0
    max_units: int | None = None
    active: bool = True


class LocationOut(ORM, LocationIn):
    id: int
    zone: Ref | None = None
    units: int = 0


class LocationGenerateIn(BaseModel):
    """Generate a block of locations, e.g. aisles A-C x bays 1-10 x levels 1-4."""
    warehouse_id: int
    zone_id: int | None = None
    aisles: list[str]
    bay_from: int = 1
    bay_to: int = 1
    level_from: int = 1
    level_to: int = 1
    location_type: LocationType = LocationType.BIN
    pickable: bool = True
    pattern: str = "{aisle}-{bay:02d}-{level:02d}"


class SupplierIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    active: bool = True


class SupplierOut(ORM, SupplierIn):
    id: int


# ------------------------------------------------------------------ items
class ItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    description: str | None = None
    barcode: str | None = None
    category: str | None = None
    brand: str | None = None
    supplier_id: int | None = None
    uom: str = "EA"
    unit_cost: Decimal | None = None
    price: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str = "lb"
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dim_unit: str = "in"
    reorder_point: int = 0
    reorder_qty: int = 0
    lot_tracked: bool = False
    default_location_id: int | None = None
    image_url: str | None = None
    active: bool = True
    shopify_product_id: str | None = None
    shopify_variant_id: str | None = None
    shopify_inventory_item_id: str | None = None


class ItemOut(ORM, ItemIn):
    id: int
    created_at: datetime
    updated_at: datetime
    on_hand: int = 0
    allocated: int = 0
    available: int = 0
    default_location: Ref | None = None


# ------------------------------------------------------------------ inventory
class BalanceOut(ORM):
    id: int
    item: ItemRef
    location: Ref
    warehouse_id: int
    zone_code: str | None
    lot_number: str
    expiration_date: date | None
    status: str
    qty_on_hand: int
    qty_allocated: int
    qty_available: int
    updated_at: datetime


class AdjustIn(BaseModel):
    item_id: int
    location_id: int
    qty: int = Field(description="Positive to add, negative to remove")
    reason_code: str
    lot_number: str = ""
    status: InventoryStatus = InventoryStatus.AVAILABLE
    expiration_date: date | None = None
    notes: str | None = None


class MoveIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int
    qty: int = Field(gt=0)
    lot_number: str = ""
    status: InventoryStatus = InventoryStatus.AVAILABLE
    notes: str | None = None


class StatusChangeIn(BaseModel):
    item_id: int
    location_id: int
    qty: int = Field(gt=0)
    from_status: InventoryStatus
    to_status: InventoryStatus
    lot_number: str = ""
    reason_code: str | None = None
    notes: str | None = None


class TxnOut(ORM):
    id: int
    created_at: datetime
    txn_type: str
    item: ItemRef
    from_location: Ref | None
    to_location: Ref | None
    lot_number: str
    qty: int
    from_status: str | None
    to_status: str | None
    reason_code: str | None
    reference_type: str | None
    reference_number: str | None
    username: str | None
    notes: str | None


# ------------------------------------------------------------------ inbound
class InboundLineIn(BaseModel):
    item_id: int
    qty_expected: int = Field(gt=0)


class InboundIn(BaseModel):
    order_type: InboundType = InboundType.PO
    warehouse_id: int
    supplier_id: int | None = None
    reference: str | None = None
    expected_date: date | None = None
    notes: str | None = None
    lines: list[InboundLineIn] = Field(min_length=1)


class InboundLineOut(ORM):
    id: int
    line_no: int
    item: ItemRef
    qty_expected: int
    qty_received: int


class SupplierRef(ORM):
    id: int
    code: str
    name: str


class InboundSummary(ORM):
    id: int
    number: str
    order_type: str
    status: str
    warehouse_id: int
    supplier: SupplierRef | None
    reference: str | None
    expected_date: date | None
    created_at: datetime
    qty_expected: int = 0
    qty_received: int = 0


class InboundOut(InboundSummary):
    notes: str | None
    closed_at: datetime | None
    lines: list[InboundLineOut]


class ReceiveIn(BaseModel):
    line_id: int
    qty: int = Field(gt=0)
    location_id: int | None = None
    lot_number: str = ""
    expiration_date: date | None = None
    create_putaway: bool = True


# ------------------------------------------------------------------ outbound
class OrderLineIn(BaseModel):
    item_id: int
    qty_ordered: int = Field(gt=0)
    external_line_id: str | None = None


class OrderIn(BaseModel):
    warehouse_id: int
    external_id: str | None = None
    channel: str = "MANUAL"
    priority: int = Field(5, ge=1, le=9)
    customer_name: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None
    ship_name: str | None = None
    ship_address1: str | None = None
    ship_address2: str | None = None
    ship_city: str | None = None
    ship_state: str | None = None
    ship_postal_code: str | None = None
    ship_country: str | None = None
    ship_method: str | None = None
    requested_ship_date: date | None = None
    notes: str | None = None
    lines: list[OrderLineIn] = Field(min_length=1)


class AllocationOut(ORM):
    id: int
    location: Ref
    lot_number: str
    qty: int
    qty_picked: int
    status: str


class OrderLineOut(ORM):
    id: int
    line_no: int
    item: ItemRef
    external_line_id: str | None
    qty_ordered: int
    qty_allocated: int
    qty_picked: int
    qty_shipped: int
    allocations: list[AllocationOut]


class ShipmentOut(ORM):
    id: int
    number: str
    status: str
    carrier: str | None
    service: str | None
    tracking_number: str | None
    packages: int
    weight: Decimal | None
    packed_by: str | None
    packed_at: datetime
    shipped_at: datetime | None


class WaveRef(ORM):
    id: int
    number: str


class OrderSummary(ORM):
    id: int
    number: str
    external_id: str | None
    channel: str
    status: str
    priority: int
    warehouse_id: int
    wave: WaveRef | None
    customer_name: str | None
    ship_city: str | None
    ship_state: str | None
    ship_method: str | None
    requested_ship_date: date | None
    created_at: datetime
    shipped_at: datetime | None
    units: int = 0
    line_count: int = 0


class OrderOut(OrderSummary):
    customer_email: str | None
    customer_phone: str | None
    ship_name: str | None
    ship_address1: str | None
    ship_address2: str | None
    ship_postal_code: str | None
    ship_country: str | None
    notes: str | None
    lines: list[OrderLineOut]
    shipments: list[ShipmentOut]


class PackIn(BaseModel):
    carrier: str | None = None
    service: str | None = None
    packages: int = 1
    weight: Decimal | None = None


class ShipIn(BaseModel):
    tracking_number: str | None = None
    carrier: str | None = None


class WaveIn(BaseModel):
    warehouse_id: int
    order_ids: list[int]
    description: str | None = None


class WaveOut(ORM):
    id: int
    number: str
    warehouse_id: int
    status: str
    description: str | None
    created_at: datetime
    released_at: datetime | None
    order_count: int = 0
    open_tasks: int = 0
    total_tasks: int = 0


# ------------------------------------------------------------------ tasks
class TaskOut(ORM):
    id: int
    task_type: str
    status: str
    priority: int
    warehouse_id: int
    item: ItemRef
    lot_number: str
    qty: int
    qty_done: int
    from_location: Ref | None
    to_location: Ref | None
    order_id: int | None
    wave_id: int | None
    reference_number: str | None
    assigned_to: str | None
    created_at: datetime
    completed_at: datetime | None
    completed_by: str | None


class TaskCompleteIn(BaseModel):
    qty: int | None = None
    to_location_id: int | None = None


class TaskAssignIn(BaseModel):
    assigned_to: str | None


class MoveTaskIn(BaseModel):
    item_id: int
    from_location_id: int
    to_location_id: int | None = None
    qty: int = Field(gt=0)
    lot_number: str = ""
    task_type: TaskType = TaskType.MOVE
    priority: int = 5


# ------------------------------------------------------------------ cycle counts
class CountIn(BaseModel):
    warehouse_id: int
    location_ids: list[int] | None = None
    zone_id: int | None = None
    item_id: int | None = None
    description: str | None = None
    blind: bool = False


class CountEntryIn(BaseModel):
    line_id: int | None = None
    location_id: int | None = None
    item_id: int | None = None
    lot_number: str = ""
    counted_qty: int | None


class CountLineOut(ORM):
    id: int
    location: Ref
    item: ItemRef
    lot_number: str
    inv_status: str
    expected_qty: int | None
    counted_qty: int | None
    adjusted_qty: int | None
    counted_by: str | None


class CountSummary(ORM):
    id: int
    number: str
    warehouse_id: int
    status: str
    description: str | None
    blind: bool
    created_by: str | None
    created_at: datetime
    completed_at: datetime | None
    line_count: int = 0
    counted_lines: int = 0


class CountOut(CountSummary):
    lines: list[CountLineOut]
