"""Shopify connector (GraphQL Admin API, version pinned per store; default 2026-10).

What it does
- Products:     import variants -> WMS items (matched by variant id, then SKU). Shopify is the product master.
- Orders:       poll orders updated since the last sync -> WMS outbound orders (no public URL / webhooks needed).
                Cancellations in Shopify cancel the WMS order if it hasn't shipped.
- Fulfillment:  when the WMS ships an order, create the Shopify fulfillment with tracking.
- Inventory:    push WMS on-hand (AVAILABLE status, incl. stock picked but not yet shipped) to the mapped
                Shopify location as `on_hand`; Shopify then shows available = on_hand - committed.
                Off by default until stock levels have been reconciled.

Auth
- CLIENT_CREDENTIALS: Dev Dashboard app in the same Shopify organization as the store. Client id + secret are
  exchanged at /admin/oauth/access_token for a 24h token, cached and refreshed automatically.
- ACCESS_TOKEN: a token from an existing legacy custom app (shpat_...). New ones can't be created since 2026-01.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..errors import WMSError
from ..models import (
    ORDER_CATEGORIES,
    InventoryBalance,
    InventoryStatus,
    Item,
    Location,
    OrderStatus,
    OutboundLine,
    OutboundOrder,
    ShipmentStatus,
    ShopifyAuthMode,
    ShopifyStore,
    ShopifySyncRun,
    utcnow,
)
from . import outbound
from .common import next_number

log = logging.getLogger("wms.shopify")
SYNC_USER = "shopify"
REQUIRED_SCOPES = ["read_products", "read_orders", "read_inventory", "write_inventory", "read_locations",
                   "write_merchant_managed_fulfillment_orders", "read_merchant_managed_fulfillment_orders"]

# Overridable in tests
http_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=30)
sleep: Callable[[float], None] = time.sleep
_lock = threading.Lock()


class ShopifyError(WMSError):
    pass


def normalize_domain(value: str) -> str:
    d = value.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    if not d.endswith(".myshopify.com"):
        d = f"{d}.myshopify.com"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", d):
        raise WMSError("Shop domain must look like your-store.myshopify.com")
    return d


def gid_num(gid: str | None) -> str | None:
    return gid.rsplit("/", 1)[-1] if gid else None


# ------------------------------------------------------------------ GraphQL documents (checked against 2026-10)
Q_TEST = """query WmsConnectionTest {
  shop { name myshopifyDomain }
  currentAppInstallation { accessScopes { handle } }
  locations(first: 50) { nodes { id name isActive fulfillsOnlineOrders } }
}"""

Q_VARIANTS = """query WmsVariants($after: String) {
  productVariants(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id sku barcode title displayName price
      inventoryItem { id tracked unitCost { amount } measurement { weight { unit value } } }
      product { id title productType vendor status }
    }
  }
}"""

Q_ORDERS = """query WmsOrders($after: String, $q: String) {
  orders(first: 10, after: $after, sortKey: UPDATED_AT, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id legacyResourceId name createdAt updatedAt cancelledAt closed test
      displayFulfillmentStatus displayFinancialStatus email phone note tags
      customer { displayName }
      shippingAddress { name firstName lastName address1 address2 city provinceCode zip countryCodeV2 phone }
      shippingLine { title }
      lineItems(first: 50) {
        pageInfo { hasNextPage }
        nodes { id sku name quantity currentQuantity unfulfilledQuantity requiresShipping variant { id } }
      }
    }
  }
}"""

Q_FULFILLMENT_ORDERS = """query WmsFulfillmentOrders($id: ID!) {
  order(id: $id) {
    id
    fulfillmentOrders(first: 20) {
      nodes { id status lineItems(first: 50) { nodes { id remainingQuantity lineItem { id } } } }
    }
  }
}"""

M_FULFILL = """mutation WmsFulfill($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment { id status }
    userErrors { field message }
  }
}"""

M_SET_INVENTORY = """mutation WmsSetInventory($input: InventorySetQuantitiesInput!, $idempotencyKey: String!) {
  inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup { reason changes { name delta quantityAfterChange } }
    userErrors { code field message }
  }
}"""


# ------------------------------------------------------------------ client
class ShopifyClient:
    def __init__(self, db: Session, store: ShopifyStore, http: httpx.Client):
        self.db, self.store, self.http = db, store, http

    @property
    def base(self) -> str:
        return f"https://{self.store.shop_domain}/admin"

    def token(self, force: bool = False) -> str:
        s = self.store
        if s.auth_mode == ShopifyAuthMode.ACCESS_TOKEN:
            if not s.access_token:
                raise ShopifyError("No access token configured")
            return s.access_token
        if not force and s.access_token and s.token_expires_at and s.token_expires_at > utcnow() + timedelta(minutes=5):
            return s.access_token
        if not (s.client_id and s.client_secret):
            raise ShopifyError("Client ID and client secret are required")
        r = self.http.post(f"{self.base}/oauth/access_token",
                           data={"grant_type": "client_credentials", "client_id": s.client_id,
                                 "client_secret": s.client_secret})
        if r.status_code != 200:
            hint = (" The app and the store must be in the same Shopify organization, and the app must be "
                    "installed on the store." if "shop_not_permitted" in r.text or r.status_code in (400, 401) else "")
            raise ShopifyError(f"Token request failed (HTTP {r.status_code}): {r.text[:300]}.{hint}")
        body = r.json()
        s.access_token = body["access_token"]
        s.token_expires_at = utcnow() + timedelta(seconds=int(body.get("expires_in", 86399)))
        s.granted_scopes = body.get("scope") or s.granted_scopes
        return s.access_token

    def gql(self, query: str, variables: dict | None = None) -> dict:
        url = f"{self.base}/api/{self.store.api_version or '2026-10'}/graphql.json"
        refreshed = False
        for attempt in range(6):
            r = self.http.post(url, json={"query": query, "variables": variables or {}},
                               headers={"X-Shopify-Access-Token": self.token(), "Content-Type": "application/json"})
            if r.status_code == 401 and not refreshed and self.store.auth_mode == ShopifyAuthMode.CLIENT_CREDENTIALS:
                self.store.access_token = None
                refreshed = True
                continue
            if r.status_code == 429 or r.status_code >= 500:
                sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code != 200:
                raise ShopifyError(f"Shopify API HTTP {r.status_code}: {r.text[:500]}")
            body = r.json()
            errors = body.get("errors") or []
            if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                sleep(2 ** attempt)
                continue
            if errors:
                raise ShopifyError("Shopify API error: " + "; ".join(e.get("message", str(e)) for e in errors)[:800])
            return body["data"]
        raise ShopifyError("Shopify API kept throttling / failing; try again later")


# ------------------------------------------------------------------ run bookkeeping
def run_job(store_id: int, kind: str, trigger: str, fn: Callable[[Session, ShopifyStore, ShopifyClient], dict],
            *, log_if_idle: bool = True) -> ShopifySyncRun | None:
    """Run one sync job in its own session with a log row. Only one job runs at a time."""
    if not _lock.acquire(timeout=0 if trigger == "SCHEDULED" else 60):
        if trigger == "SCHEDULED":
            return None
        raise WMSError("Another Shopify sync is running; try again shortly", 409)
    try:
        with SessionLocal() as db, http_factory() as http:
            store = db.get(ShopifyStore, store_id)
            if store is None:
                raise WMSError("Shopify store not configured", 404)
            run = ShopifySyncRun(store_id=store_id, kind=kind, trigger=trigger)
            try:
                summary = fn(db, store, ShopifyClient(db, store, http))
                run.status, run.summary = "OK", json.dumps(summary, default=str)
                store.last_error = None
            except Exception as e:  # recorded, never raised from the scheduler
                db.rollback()
                store = db.get(ShopifyStore, store_id)
                msg = e.message if isinstance(e, WMSError) else f"{type(e).__name__}: {e}"
                if not isinstance(e, WMSError):
                    log.exception("shopify %s failed", kind)
                run.status, run.error = "ERROR", msg[:2000]
                store.last_error = f"{kind}: {msg}"[:2000]
            run.finished_at = utcnow()
            busy = run.status == "ERROR" or any(v for k, v in json.loads(run.summary or "{}").items()
                                                 if isinstance(v, int) and k not in ("checked", "pages"))
            if log_if_idle or busy:
                db.add(run)
            db.commit()
            if run in db:
                db.refresh(run)
            return run
    finally:
        _lock.release()


# ------------------------------------------------------------------ jobs
def test_connection(db: Session, store: ShopifyStore, client: ShopifyClient) -> dict:
    data = client.gql(Q_TEST)
    scopes = sorted(s["handle"] for s in data["currentAppInstallation"]["accessScopes"])
    store.granted_scopes = ",".join(scopes)
    return {
        "shop": data["shop"]["name"], "domain": data["shop"]["myshopifyDomain"],
        "locations": [{"id": l["id"], "name": l["name"], "active": l["isActive"]} for l in data["locations"]["nodes"]],
        "scopes": scopes, "missing_scopes": [s for s in REQUIRED_SCOPES if s not in scopes],
    }


_WEIGHT = {"POUNDS": "lb", "KILOGRAMS": "kg", "GRAMS": "g", "OUNCES": "oz"}


def import_products(db: Session, store: ShopifyStore, client: ShopifyClient) -> dict:
    stats = {"created": 0, "updated": 0, "skipped_no_sku": 0, "pages": 0}
    messages: list[str] = []
    after = None
    while True:
        page = client.gql(Q_VARIANTS, {"after": after})["productVariants"]
        stats["pages"] += 1
        for v in page["nodes"]:
            sku = (v.get("sku") or "").strip()
            item = db.scalar(select(Item).where(Item.shopify_variant_id == v["id"]))
            if item is None and sku:
                item = db.scalar(select(Item).where(func.upper(Item.sku) == sku.upper()))
            if item is None and not sku:
                stats["skipped_no_sku"] += 1
                if len(messages) < 50:
                    messages.append(f"{v['displayName']}: no SKU in Shopify, skipped")
                continue
            prod = v["product"]
            name = prod["title"] if v["title"] in ("Default Title", "") else f"{prod['title']} - {v['title']}"
            inv = v.get("inventoryItem") or {}
            weight = ((inv.get("measurement") or {}).get("weight")) or {}
            fields = {
                "name": name[:255], "barcode": v.get("barcode") or None, "price": v.get("price"),
                "category": prod.get("productType") or None, "brand": prod.get("vendor") or None,
                "shopify_product_id": prod["id"], "shopify_variant_id": v["id"],
                "shopify_inventory_item_id": inv.get("id"),
            }
            if inv.get("unitCost"):
                fields["unit_cost"] = inv["unitCost"]["amount"]
            if weight.get("value") is not None:
                fields["weight"], fields["weight_unit"] = weight["value"], _WEIGHT.get(weight.get("unit"), "lb")
            if item is None:
                db.add(Item(sku=sku, active=prod.get("status") != "ARCHIVED", **fields))
                stats["created"] += 1
            else:
                for k, val in fields.items():
                    setattr(item, k, val)
                stats["updated"] += 1
            db.flush()
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return {**stats, "messages": messages}


def _category(tags: list[str]) -> str:
    known = {c.lower(): c for c in ORDER_CATEGORIES}
    for t in tags or []:
        if t.strip().lower() in known:
            return known[t.strip().lower()]
    return "STANDARD"


def _item_for_line(db: Session, li: dict, stats: dict) -> Item:
    variant_id = (li.get("variant") or {}).get("id")
    sku = (li.get("sku") or "").strip()
    item = db.scalar(select(Item).where(Item.shopify_variant_id == variant_id)) if variant_id else None
    if item is None and sku:
        item = db.scalar(select(Item).where(func.upper(Item.sku) == sku.upper()))
        if item is not None and variant_id and not item.shopify_variant_id:
            item.shopify_variant_id = variant_id
    if item is None:  # unknown product: create a placeholder so the order still imports
        item = Item(sku=sku or f"SHOPIFY-{gid_num(variant_id) or gid_num(li['id'])}", name=li["name"][:255],
                    shopify_variant_id=variant_id)
        db.add(item)
        db.flush()
        stats["items_created"] += 1
    return item


def _wanted_lines(order: dict) -> list[dict]:
    return [li for li in order["lineItems"]["nodes"] if li["requiresShipping"] and li["unfulfilledQuantity"] > 0]


def import_orders(db: Session, store: ShopifyStore, client: ShopifyClient) -> dict:
    if not store.warehouse_id:
        raise WMSError("Choose the WMS warehouse that Shopify orders go to")
    stats = {"created": 0, "updated": 0, "cancelled": 0, "skipped": 0, "items_created": 0, "checked": 0}
    messages: list[str] = []
    since = store.orders_since or (utcnow() - timedelta(days=1))
    q = f"created_at:>='{since.replace(microsecond=0).isoformat()}Z'"
    if store.orders_cursor:
        q += f" AND updated_at:>='{store.orders_cursor}'"
    after, newest = None, store.orders_cursor
    while True:
        page = client.gql(Q_ORDERS, {"after": after, "q": q})["orders"]
        for o in page["nodes"]:
            stats["checked"] += 1
            newest = max(newest or "", o["updatedAt"])
            existing = db.scalar(select(OutboundOrder).where(OutboundOrder.shopify_order_id == o["id"]))
            if existing is not None:
                if existing.shopify_updated_at == o["updatedAt"]:
                    continue
                _update_order(db, existing, o, stats, messages)
                existing.shopify_updated_at = o["updatedAt"]
                continue
            reason = _skip_reason(store, o)
            if reason:
                stats["skipped"] += 1
                if len(messages) < 50:
                    messages.append(f"{o['name']}: skipped ({reason})")
                continue
            _create_order(db, store, o, stats)
            if o["lineItems"]["pageInfo"]["hasNextPage"]:
                messages.append(f"{o['name']}: more than 50 lines; only the first 50 were imported")
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    store.orders_cursor = newest
    return {**stats, "messages": messages}


def _skip_reason(store: ShopifyStore, o: dict) -> str | None:
    if o["cancelledAt"]:
        return "cancelled"
    if o["test"] and not store.import_test_orders:
        return "test order"
    if o["displayFinancialStatus"] in ("VOIDED", "REFUNDED", "EXPIRED"):
        return f"payment {o['displayFinancialStatus'].lower()}"
    if not _wanted_lines(o):
        return "nothing left to ship"
    return None


def _create_order(db: Session, store: ShopifyStore, o: dict, stats: dict) -> OutboundOrder:
    a = o.get("shippingAddress") or {}
    cust = (o.get("customer") or {}).get("displayName") or a.get("name")
    order = OutboundOrder(
        number=next_number(db, "order"), channel="SHOPIFY", external_id=o["name"], shopify_order_id=o["id"],
        shopify_updated_at=o["updatedAt"], warehouse_id=store.warehouse_id, category=_category(o.get("tags")),
        customer_name=cust, customer_email=o.get("email"), customer_phone=o.get("phone") or a.get("phone"),
        ship_name=a.get("name") or cust, ship_address1=a.get("address1"), ship_address2=a.get("address2"),
        ship_city=a.get("city"), ship_state=a.get("provinceCode"), ship_postal_code=a.get("zip"),
        ship_country=a.get("countryCodeV2"), ship_method=(o.get("shippingLine") or {}).get("title"),
        notes=o.get("note"),
    )
    for i, li in enumerate(_wanted_lines(o), start=1):
        item = _item_for_line(db, li, stats)
        order.lines.append(OutboundLine(line_no=i, item_id=item.id, qty_ordered=li["unfulfilledQuantity"],
                                        external_line_id=li["id"]))
    db.add(order)
    db.flush()
    stats["created"] += 1
    return order


def _update_order(db: Session, order: OutboundOrder, o: dict, stats: dict, messages: list[str]) -> None:
    if o["cancelledAt"]:
        if order.status not in (OrderStatus.SHIPPED, OrderStatus.CANCELLED):
            outbound.cancel(db, order, SYNC_USER)
            order.notes = ((order.notes or "") + "\nCancelled in Shopify.").strip()
            stats["cancelled"] += 1
            messages.append(f"{o['name']}: cancelled in Shopify -> {order.number} cancelled")
        return
    wanted = {li["id"]: li for li in _wanted_lines(o)}
    current = {l.external_line_id: l for l in order.lines}
    changed = {k for k in set(wanted) | set(current)
               if (wanted[k]["unfulfilledQuantity"] if k in wanted else 0) != (current[k].qty_ordered if k in current else 0)}
    if order.status == OrderStatus.NEW and not any(a for l in order.lines for a in l.allocations):
        a = o.get("shippingAddress") or {}
        order.ship_name, order.ship_address1, order.ship_address2 = a.get("name"), a.get("address1"), a.get("address2")
        order.ship_city, order.ship_state, order.ship_postal_code = a.get("city"), a.get("provinceCode"), a.get("zip")
        order.ship_country, order.notes = a.get("countryCodeV2"), o.get("note")
        order.category = _category(o.get("tags"))
        if changed:
            for line in list(order.lines):
                order.lines.remove(line)
            db.flush()
            for i, li in enumerate(wanted.values(), start=1):
                item = _item_for_line(db, li, stats)
                order.lines.append(OutboundLine(line_no=i, item_id=item.id, qty_ordered=li["unfulfilledQuantity"],
                                                external_line_id=li["id"]))
        stats["updated"] += 1
    elif changed and order.status not in (OrderStatus.SHIPPED, OrderStatus.CANCELLED):
        messages.append(f"{o['name']}: items changed in Shopify after {order.number} was released "
                        f"({order.status}); review manually")


def process_fulfillments(db: Session, store: ShopifyStore, client: ShopifyClient) -> dict:
    stats = {"fulfilled": 0, "failed": 0}
    messages: list[str] = []
    pending = db.scalars(select(OutboundOrder).where(OutboundOrder.shopify_fulfillment_status == "PENDING")
                         .order_by(OutboundOrder.id).limit(50)).all()
    for order in pending:
        try:
            _fulfill(store, client, order)
            order.shopify_fulfillment_status, order.shopify_fulfillment_error = "DONE", None
            stats["fulfilled"] += 1
        except WMSError as e:
            order.shopify_fulfillment_status, order.shopify_fulfillment_error = "FAILED", e.message[:2000]
            stats["failed"] += 1
            messages.append(f"{order.number} ({order.external_id}): {e.message}")
        db.flush()
    return {**stats, "messages": messages}


def _fulfill(store: ShopifyStore, client: ShopifyClient, order: OutboundOrder) -> None:
    shipment = next((s for s in sorted(order.shipments, key=lambda s: s.id, reverse=True)
                     if s.status == ShipmentStatus.SHIPPED), None)
    to_ship = {l.external_line_id: l.qty_shipped for l in order.lines if l.external_line_id and l.qty_shipped > 0}
    if not to_ship:
        raise WMSError("Nothing shipped to report")
    data = client.gql(Q_FULFILLMENT_ORDERS, {"id": order.shopify_order_id})
    if not data.get("order"):
        raise WMSError("Order not found in Shopify")
    groups = []
    for fo in data["order"]["fulfillmentOrders"]["nodes"]:
        if fo["status"] not in ("OPEN", "IN_PROGRESS"):
            continue
        items = []
        for foli in fo["lineItems"]["nodes"]:
            want = to_ship.get(foli["lineItem"]["id"], 0)
            qty = min(want, foli["remainingQuantity"])
            if qty > 0:
                items.append({"id": foli["id"], "quantity": qty})
                to_ship[foli["lineItem"]["id"]] = want - qty
        if items:
            groups.append({"fulfillmentOrderId": fo["id"], "fulfillmentOrderLineItems": items})
    if not groups:
        raise WMSError("No open fulfillment orders in Shopify for these items (already fulfilled or on hold?)")
    fulfillment: dict = {"lineItemsByFulfillmentOrder": groups, "notifyCustomer": bool(store.notify_customer)}
    if shipment and (shipment.tracking_number or shipment.carrier):
        fulfillment["trackingInfo"] = {k: v for k, v in (("company", shipment.carrier),
                                                         ("number", shipment.tracking_number)) if v}
    res = client.gql(M_FULFILL, {"fulfillment": fulfillment})["fulfillmentCreate"]
    if res["userErrors"]:
        raise WMSError("Shopify refused fulfillment: " + "; ".join(e["message"] for e in res["userErrors"]))


def on_hand_by_item(db: Session, warehouse_id: int) -> dict[int, int]:
    """Sellable stock not yet shipped: AVAILABLE status, any location in the warehouse (incl. staging)."""
    rows = db.execute(
        select(InventoryBalance.item_id, func.sum(InventoryBalance.qty_on_hand))
        .join(Location, Location.id == InventoryBalance.location_id)
        .where(Location.warehouse_id == warehouse_id, InventoryBalance.status == InventoryStatus.AVAILABLE)
        .group_by(InventoryBalance.item_id)).all()
    return {i: int(q or 0) for i, q in rows}


def push_inventory(db: Session, store: ShopifyStore, client: ShopifyClient, *, full: bool = False) -> dict:
    wh = store.warehouse
    if wh is None or not wh.shopify_location_id:
        raise WMSError("Map the WMS warehouse to a Shopify location first")
    qty = on_hand_by_item(db, wh.id)
    items = db.scalars(select(Item).where(Item.shopify_inventory_item_id.is_not(None))).all()
    todo = [(it, qty.get(it.id, 0)) for it in items if full or it.shopify_synced_qty != qty.get(it.id, 0)]
    stats = {"pushed": 0, "errors": 0, "checked": len(items)}
    messages: list[str] = []
    for start in range(0, len(todo), 100):
        batch = todo[start:start + 100]
        res = client.gql(M_SET_INVENTORY, {
            "input": {
                "name": "on_hand", "reason": "correction",
                "referenceDocumentUri": f"wms://dockyard/inventory-sync/{utcnow().strftime('%Y%m%dT%H%M%S')}",
                "quantities": [{"inventoryItemId": it.shopify_inventory_item_id, "locationId": wh.shopify_location_id,
                                "quantity": q, "changeFromQuantity": None} for it, q in batch],
            },
            "idempotencyKey": str(uuid.uuid4()),
        })["inventorySetQuantities"]
        bad_rows = set()
        for e in res["userErrors"]:
            stats["errors"] += 1
            field = e.get("field") or []
            idx = next((int(f) for f in field if str(f).isdigit()), None)
            if idx is not None:
                bad_rows.add(idx)
            sku = batch[idx][0].sku if idx is not None and idx < len(batch) else "?"
            if len(messages) < 50:
                messages.append(f"{sku}: {e['message']}")
        if res["userErrors"] and not bad_rows:
            continue  # whole batch rejected
        for i, (it, q) in enumerate(batch):
            if i not in bad_rows:
                it.shopify_synced_qty = q
                stats["pushed"] += 1
    return {**stats, "messages": messages}


# ------------------------------------------------------------------ scheduler
class ShopifyScheduler:
    """Fulfillments every tick (30s); orders + inventory every store.poll_minutes."""
    TICK = 30

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._thread:
            self._thread = threading.Thread(target=self._run, name="wms-shopify", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.TICK):
            try:
                tick()
            except Exception:
                log.exception("shopify scheduler error")


def tick(now: datetime | None = None) -> None:
    now = now or utcnow()
    with SessionLocal() as db:
        stores = [(s.id, s.fulfill_on_ship, s.import_orders, s.push_inventory, s.last_sync_at, s.poll_minutes)
                  for s in db.scalars(select(ShopifyStore).where(ShopifyStore.active.is_(True)))]
    for sid, fulfill, orders, inventory, last, poll in stores:
        if fulfill:
            run_job(sid, "FULFILLMENTS", "SCHEDULED", process_fulfillments, log_if_idle=False)
        if last is None or now - last >= timedelta(minutes=max(1, poll or 5)):
            if orders:
                run_job(sid, "ORDERS", "SCHEDULED", import_orders, log_if_idle=False)
            if inventory:
                run_job(sid, "INVENTORY", "SCHEDULED", push_inventory, log_if_idle=False)
            with SessionLocal() as db:
                s = db.get(ShopifyStore, sid)
                if s:
                    s.last_sync_at = now
                    db.commit()


scheduler = ShopifyScheduler()
