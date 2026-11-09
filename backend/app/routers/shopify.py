"""Shopify connection settings, manual sync actions and sync log."""
import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_role
from ..errors import WMSError
from ..models import OutboundOrder, Role, ShopifyAuthMode, ShopifyStore, ShopifySyncRun, Warehouse
from ..services import shopify as svc
from ..services.common import get_or_404
from ._util import paginate

router = APIRouter(prefix="/shopify", tags=["shopify"])
admin = Depends(require_role(Role.ADMIN))
supervisor = Depends(require_role(Role.SUPERVISOR))


class StoreIn(BaseModel):
    shop_domain: str
    auth_mode: ShopifyAuthMode = ShopifyAuthMode.CLIENT_CREDENTIALS
    client_id: str | None = None
    client_secret: str | None = Field(None, description="Omit/null to keep the stored value")
    access_token: str | None = Field(None, description="ACCESS_TOKEN mode only. Omit/null to keep")
    api_version: str = Field("2026-10", pattern=r"^\d{4}-\d{2}$|^unstable$")
    warehouse_id: int | None = None
    shopify_location_id: str | None = Field(None, description="gid://shopify/Location/...; saved on the warehouse")
    active: bool = False
    poll_minutes: int = Field(5, ge=1, le=1440)
    import_orders: bool = True
    orders_since: datetime | None = None
    import_test_orders: bool = True
    fulfill_on_ship: bool = True
    notify_customer: bool = True
    push_inventory: bool = False


class StoreOut(BaseModel):
    id: int
    shop_domain: str
    auth_mode: str
    client_id: str | None
    has_client_secret: bool
    has_access_token: bool
    token_expires_at: datetime | None
    granted_scopes: list[str]
    api_version: str
    warehouse_id: int | None
    shopify_location_id: str | None
    active: bool
    poll_minutes: int
    import_orders: bool
    orders_since: datetime | None
    orders_cursor: str | None
    import_test_orders: bool
    fulfill_on_ship: bool
    notify_customer: bool
    push_inventory: bool
    last_sync_at: datetime | None
    last_error: str | None
    pending_fulfillments: int = 0
    failed_fulfillments: int = 0


class RunOut(BaseModel):
    id: int
    kind: str
    trigger: str
    status: str
    summary: dict | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


def _store(db: Session) -> ShopifyStore | None:
    return db.scalar(select(ShopifyStore).order_by(ShopifyStore.id).limit(1))


def _out(db: Session, s: ShopifyStore) -> StoreOut:
    count = lambda st: len(db.scalars(select(OutboundOrder.id).where(OutboundOrder.shopify_fulfillment_status == st)).all())
    return StoreOut(
        id=s.id, shop_domain=s.shop_domain, auth_mode=s.auth_mode, client_id=s.client_id,
        has_client_secret=bool(s.client_secret),
        has_access_token=bool(s.access_token) if s.auth_mode == ShopifyAuthMode.ACCESS_TOKEN else False,
        token_expires_at=s.token_expires_at if s.auth_mode == ShopifyAuthMode.CLIENT_CREDENTIALS else None,
        granted_scopes=[x for x in (s.granted_scopes or "").split(",") if x], api_version=s.api_version,
        warehouse_id=s.warehouse_id, shopify_location_id=s.warehouse.shopify_location_id if s.warehouse else None,
        active=s.active, poll_minutes=s.poll_minutes, import_orders=s.import_orders, orders_since=s.orders_since,
        orders_cursor=s.orders_cursor, import_test_orders=s.import_test_orders, fulfill_on_ship=s.fulfill_on_ship,
        notify_customer=s.notify_customer, push_inventory=s.push_inventory, last_sync_at=s.last_sync_at,
        last_error=s.last_error, pending_fulfillments=count("PENDING"), failed_fulfillments=count("FAILED"),
    )


def _run_out(r: ShopifySyncRun) -> RunOut:
    return RunOut(id=r.id or 0, kind=r.kind, trigger=r.trigger, status=r.status,
                  summary=json.loads(r.summary) if r.summary else None, error=r.error,
                  started_at=r.started_at or r.finished_at, finished_at=r.finished_at)


def _need_store(db: Session) -> ShopifyStore:
    s = _store(db)
    if s is None:
        raise WMSError("Connect a Shopify store first", 404)
    return s


@router.get("/store", response_model=StoreOut | None, dependencies=[supervisor])
def get_store(db: Session = Depends(get_db)):
    s = _store(db)
    return _out(db, s) if s else None


@router.put("/store", response_model=StoreOut, dependencies=[admin])
def save_store(body: StoreIn, db: Session = Depends(get_db)):
    s = _store(db) or ShopifyStore()
    domain = svc.normalize_domain(body.shop_domain)
    creds_changed = domain != s.shop_domain or body.auth_mode != s.auth_mode or body.client_id != s.client_id \
        or bool(body.client_secret) or bool(body.access_token)
    s.shop_domain, s.auth_mode, s.client_id, s.api_version = domain, body.auth_mode, body.client_id, body.api_version
    if body.client_secret:
        s.client_secret = body.client_secret
    if body.auth_mode == ShopifyAuthMode.ACCESS_TOKEN:
        if body.access_token:
            s.access_token = body.access_token
        s.token_expires_at = None
    elif creds_changed:
        s.access_token, s.token_expires_at = None, None  # fetch a fresh 24h token with the new credentials
    if body.orders_since != s.orders_since:
        s.orders_cursor = None  # re-scan from the new start date
    for k in ("warehouse_id", "active", "poll_minutes", "import_orders", "orders_since", "import_test_orders",
              "fulfill_on_ship", "notify_customer", "push_inventory"):
        setattr(s, k, getattr(body, k))
    if body.auth_mode == ShopifyAuthMode.CLIENT_CREDENTIALS and not (s.client_id and s.client_secret):
        raise WMSError("Client ID and client secret are required")
    if body.auth_mode == ShopifyAuthMode.ACCESS_TOKEN and not s.access_token:
        raise WMSError("Access token is required")
    if body.warehouse_id:
        wh = get_or_404(db, Warehouse, body.warehouse_id, "Warehouse")
        wh.shopify_location_id = body.shopify_location_id or None
    if s.active and not body.warehouse_id:
        raise WMSError("Choose a warehouse before turning on automatic sync")
    db.add(s)
    db.flush()
    return _out(db, s)


@router.delete("/store", dependencies=[admin])
def disconnect(db: Session = Depends(get_db)):
    s = _need_store(db)
    for r in db.scalars(select(ShopifySyncRun).where(ShopifySyncRun.store_id == s.id)):
        db.delete(r)
    db.delete(s)
    return {"ok": True}


def _manual(db: Session, kind: str, fn) -> RunOut:
    sid = _need_store(db).id
    db.commit()  # make sure settings saved in this request are visible to the job's own session
    return _run_out(svc.run_job(sid, kind, "MANUAL", fn))


@router.post("/test", response_model=RunOut, dependencies=[admin])
def test(db: Session = Depends(get_db)):
    return _manual(db, "TEST", svc.test_connection)


@router.post("/import-products", response_model=RunOut, dependencies=[supervisor])
def import_products(db: Session = Depends(get_db)):
    return _manual(db, "PRODUCTS", svc.import_products)


@router.post("/sync-orders", response_model=RunOut, dependencies=[supervisor])
def sync_orders(db: Session = Depends(get_db)):
    return _manual(db, "ORDERS", svc.import_orders)


@router.post("/push-inventory", response_model=RunOut, dependencies=[supervisor])
def push_inventory(full: bool = False, db: Session = Depends(get_db)):
    return _manual(db, "INVENTORY", lambda d, s, c: svc.push_inventory(d, s, c, full=full))


@router.post("/fulfillments", response_model=RunOut, dependencies=[supervisor])
def fulfillments(db: Session = Depends(get_db)):
    return _manual(db, "FULFILLMENTS", svc.process_fulfillments)


@router.post("/orders/{order_id}/retry-fulfillment", dependencies=[supervisor])
def retry_fulfillment(order_id: int, db: Session = Depends(get_db)):
    o = get_or_404(db, OutboundOrder, order_id, "Order")
    if not o.shopify_order_id or o.status != "SHIPPED":
        raise WMSError("Only shipped Shopify orders can be fulfilled")
    o.shopify_fulfillment_status, o.shopify_fulfillment_error = "PENDING", None
    return {"ok": True}


@router.get("/runs", dependencies=[supervisor])
def runs(kind: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0,
         db: Session = Depends(get_db)):
    stmt = select(ShopifySyncRun).order_by(ShopifySyncRun.id.desc())
    if kind:
        stmt = stmt.where(ShopifySyncRun.kind == kind)
    if status:
        stmt = stmt.where(ShopifySyncRun.status == status)
    rows, total = paginate(db, stmt, limit, offset)
    return {"items": [_run_out(r[0]) for r in rows], "total": total}
