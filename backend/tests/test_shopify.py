"""Shopify connector against a fake Shopify (token endpoint + GraphQL Admin API)."""
import json
import re
from urllib.parse import parse_qs

import httpx
import pytest

from app.services import shopify as shop_svc

DOMAIN = "wms-dev.myshopify.com"
LOC = "gid://shopify/Location/111"


class FakeShopify:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []      # (operation name, variables)
        self.queries: dict[str, str] = {}
        self.token_requests: list[dict] = []
        self.tokens_issued = 0
        self.reject_token: str | None = None
        self.fail_next: list[str] = []               # "401" / "THROTTLED" injected into the next GraphQL calls
        self.variants = [
            self._variant(1, "TS-BLK-S", "Classic Tee", "Black / S", "24.00", 7.0, "OUNCES"),
            self._variant(2, "NEW-SKU-1", "Brand New Thing", "Default Title", "10.00", 1.5, "POUNDS"),
            self._variant(3, None, "Gift Card", "Default Title", "25.00", None, None),
        ]
        self.orders: list[dict] = []
        self.fulfillment_orders: dict[str, list[dict]] = {}
        self.inventory_errors: list[dict] = []

    @staticmethod
    def _variant(n, sku, ptitle, vtitle, price, wval, wunit):
        return {"id": f"gid://shopify/ProductVariant/{n}", "sku": sku, "barcode": f"9{n:011d}", "title": vtitle,
                "displayName": f"{ptitle} - {vtitle}", "price": price,
                "inventoryItem": {"id": f"gid://shopify/InventoryItem/{n}", "tracked": True,
                                  "unitCost": {"amount": "3.10"},
                                  "measurement": {"weight": {"unit": wunit, "value": wval} if wunit else None}},
                "product": {"id": f"gid://shopify/Product/{n}", "title": ptitle, "productType": "Apparel",
                            "vendor": "Northwind", "status": "ACTIVE"}}

    def order(self, n, *, lines, tags=(), cancelled=False, fulfillment="UNFULFILLED", updated="2026-11-09T10:00:00Z"):
        o = {"id": f"gid://shopify/Order/{n}", "legacyResourceId": str(n), "name": f"#{n}",
             "createdAt": "2026-11-09T09:00:00Z", "updatedAt": updated,
             "cancelledAt": "2026-11-09T11:00:00Z" if cancelled else None, "closed": False, "test": True,
             "displayFulfillmentStatus": fulfillment, "displayFinancialStatus": "PAID", "email": "buyer@example.com",
             "phone": None, "note": "Leave at door", "tags": list(tags), "customer": {"displayName": "Riley Buyer"},
             "shippingAddress": {"name": "Riley Buyer", "firstName": "Riley", "lastName": "Buyer",
                                 "address1": "5 Elm St", "address2": None, "city": "Dayton", "provinceCode": "OH",
                                 "zip": "45402", "countryCodeV2": "US", "phone": "555-0100"},
             "shippingLine": {"title": "UPS Ground"},
             "lineItems": {"pageInfo": {"hasNextPage": False}, "nodes": [
                 {"id": f"gid://shopify/LineItem/{n}{i}", "sku": sku, "name": name, "quantity": q, "currentQuantity": q,
                  "unfulfilledQuantity": q, "requiresShipping": True,
                  "variant": {"id": f"gid://shopify/ProductVariant/{vid}"} if vid else None}
                 for i, (sku, name, q, vid) in enumerate(lines, start=1)]}}
        self.orders = [x for x in self.orders if x["id"] != o["id"]] + [o]
        self.fulfillment_orders[o["id"]] = [{"id": f"gid://shopify/FulfillmentOrder/{n}", "status": "OPEN",
                                             "lineItems": {"nodes": [
                                                 {"id": f"gid://shopify/FulfillmentOrderLineItem/{n}{i}",
                                                  "remainingQuantity": li["unfulfilledQuantity"],
                                                  "lineItem": {"id": li["id"]}}
                                                 for i, li in enumerate(o["lineItems"]["nodes"], start=1)]}}]
        return o

    # ---------------------------------------------------------------- transport
    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == DOMAIN
        if request.url.path == "/admin/oauth/access_token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.reject_token:
                return httpx.Response(400, text=self.reject_token)
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": f"tok-{self.tokens_issued}",
                                             "scope": "read_products,read_orders", "expires_in": 86399})
        assert re.fullmatch(r"/admin/api/2026-10/graphql.json", request.url.path), request.url.path
        assert request.headers["X-Shopify-Access-Token"].startswith(("tok-", "shpat_"))
        body = json.loads(request.content)
        op = re.search(r"(?:query|mutation)\s+(\w+)", body["query"]).group(1)
        self.calls.append((op, body.get("variables") or {}))
        self.queries[op] = body["query"]
        if self.fail_next:
            kind = self.fail_next.pop(0)
            if kind == "401":
                return httpx.Response(401, text="Invalid API key or access token")
            return httpx.Response(200, json={"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]})
        return httpx.Response(200, json={"data": getattr(self, "op_" + op)(body.get("variables") or {})})

    def op_WmsConnectionTest(self, v):
        return {"shop": {"name": "WMS Dev", "myshopifyDomain": DOMAIN},
                "currentAppInstallation": {"accessScopes": [{"handle": h} for h in
                                                            ("read_products", "read_orders", "read_inventory",
                                                             "write_inventory", "read_locations")]},
                "locations": {"nodes": [{"id": LOC, "name": "Main warehouse", "isActive": True,
                                         "fulfillsOnlineOrders": True}]}}

    def op_WmsVariants(self, v):
        # two pages to exercise pagination
        page = self.variants[:2] if v.get("after") is None else self.variants[2:]
        return {"productVariants": {"pageInfo": {"hasNextPage": v.get("after") is None, "endCursor": "c1"},
                                    "nodes": page}}

    def op_WmsOrders(self, v):
        m = re.search(r"updated_at:>='([^']+)'", v.get("q") or "")
        nodes = [o for o in sorted(self.orders, key=lambda o: o["updatedAt"]) if not m or o["updatedAt"] >= m.group(1)]
        return {"orders": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}

    def op_WmsFulfillmentOrders(self, v):
        return {"order": {"id": v["id"], "fulfillmentOrders": {"nodes": self.fulfillment_orders.get(v["id"], [])}}}

    def op_WmsFulfill(self, v):
        return {"fulfillmentCreate": {"fulfillment": {"id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"},
                                      "userErrors": []}}

    def op_WmsSetInventory(self, v):
        errs, self.inventory_errors = self.inventory_errors, []
        return {"inventorySetQuantities": {"inventoryAdjustmentGroup": {"reason": "correction", "changes": []},
                                           "userErrors": errs}}

    stock: dict = {"gid://shopify/InventoryItem/1": 40, "gid://shopify/InventoryItem/2": 7}

    def op_WmsLocation(self, v):
        return {"location": {"id": LOC, "name": "Main warehouse", "isActive": True} if v["id"] == LOC else None}

    def op_WmsStockLevels(self, v):
        assert v["loc"] == LOC
        return {"nodes": [{"id": i, "tracked": True,
                           "inventoryLevel": {"quantities": [{"name": "on_hand", "quantity": self.stock[i]}]}
                           if i in self.stock else None} for i in v["ids"]]}

    def ops(self, name):
        return [vars_ for op, vars_ in self.calls if op == name]


@pytest.fixture(scope="module")
def fake():
    f = FakeShopify()
    orig_factory, orig_sleep = shop_svc.http_factory, shop_svc.sleep
    shop_svc.http_factory = lambda: httpx.Client(transport=httpx.MockTransport(f.handle))
    shop_svc.sleep = lambda s: None
    yield f
    shop_svc.http_factory, shop_svc.sleep = orig_factory, orig_sleep


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


STORE = {"shop_domain": "https://WMS-Dev.myshopify.com/admin", "auth_mode": "CLIENT_CREDENTIALS",
         "client_id": "cid-123", "client_secret": "csecret-456", "warehouse_id": 1, "shopify_location_id": LOC,
         "orders_since": "2026-11-01T00:00:00", "push_inventory": False}


def test_connect_and_test(client, admin, fake):
    s = ok(client.put("/api/shopify/store", headers=admin, json=STORE))
    assert s["shop_domain"] == DOMAIN and s["has_client_secret"] and "csecret" not in json.dumps(s)
    run = ok(client.post("/api/shopify/test", headers=admin))
    assert run["status"] == "OK", run
    assert fake.token_requests[-1] == {"grant_type": "client_credentials", "client_id": "cid-123",
                                       "client_secret": "csecret-456"}
    assert run["summary"]["shop"] == "WMS Dev" and run["summary"]["locations"][0]["id"] == LOC
    assert "write_merchant_managed_fulfillment_orders" in run["summary"]["missing_scopes"]
    # token is cached: a second call doesn't request a new one
    ok(client.post("/api/shopify/test", headers=admin))
    assert fake.tokens_issued == 1
    # saving without re-sending the secret keeps it
    s = ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None}))
    assert s["has_client_secret"]


def test_token_refresh_and_throttle(client, admin, fake):
    fake.fail_next = ["401", "THROTTLED"]
    run = ok(client.post("/api/shopify/test", headers=admin))
    assert run["status"] == "OK"
    assert fake.tokens_issued == 2                      # 401 -> fresh token -> throttled -> retried


def test_bad_credentials_message(client, admin, fake):
    fake.reject_token = '{"error":"shop_not_permitted"}'
    ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": "rotated"}))
    run = ok(client.post("/api/shopify/test", headers=admin))
    assert run["status"] == "ERROR" and "same Shopify organization" in run["error"]
    fake.reject_token = ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                         '<title>400 - Oauth error app_not_installed</title></head><body>...</body></html>')
    run = ok(client.post("/api/shopify/test", headers=admin))
    fake.reject_token = None
    assert "not installed on wms-dev.myshopify.com" in run["error"] and "<html" not in run["error"]
    assert ok(client.get("/api/shopify/store", headers=admin))["last_error"].startswith("TEST:")


def test_import_products(client, admin, fake):
    run = ok(client.post("/api/shopify/import-products", headers=admin))
    assert run["status"] == "OK", run
    assert run["summary"]["created"] == 1 and run["summary"]["updated"] == 1 and run["summary"]["skipped_no_sku"] == 1
    tee = client.get("/api/items/lookup", params={"code": "TS-BLK-S"}, headers=admin).json()
    assert tee["shopify_variant_id"] == "gid://shopify/ProductVariant/1"
    assert tee["shopify_inventory_item_id"] == "gid://shopify/InventoryItem/1"
    assert tee["weight_unit"] == "oz" and tee["name"] == "Classic Tee - Black / S"
    new = client.get("/api/items/lookup", params={"code": "NEW-SKU-1"}, headers=admin).json()
    assert new["name"] == "Brand New Thing" and new["price"] == "10.00" and new["brand"] == "Northwind"


def test_import_orders(client, admin, fake):
    fake.order(2001, tags=["Consolidation", "vip"], lines=[("TS-BLK-S", "Classic Tee - Black / S", 2, 1),
                                                           ("MYSTERY-1", "Mystery item", 1, 99)])
    fake.order(2002, lines=[("TS-BLK-S", "Tee", 1, 1)], cancelled=True)
    fake.order(2003, lines=[("TS-BLK-S", "Tee", 1, 1)], fulfillment="FULFILLED")
    fake.orders[-1]["lineItems"]["nodes"][0]["unfulfilledQuantity"] = 0
    run = ok(client.post("/api/shopify/sync-orders", headers=admin))
    assert run["status"] == "OK", run
    s = run["summary"]
    assert (s["created"], s["skipped"], s["items_created"]) == (1, 2, 1)
    assert fake.ops("WmsOrders")[0]["q"] == "created_at:>='2026-11-01T00:00:00Z'"

    orders = ok(client.get("/api/orders", headers=admin, params={"q": "#2001"}))["items"]
    assert len(orders) == 1
    o = ok(client.get(f"/api/orders/{orders[0]['id']}", headers=admin))
    assert o["channel"] == "SHOPIFY" and o["category"] == "CONSOLIDATION" and o["shopify_order_id"].endswith("/2001")
    assert (o["ship_city"], o["ship_state"], o["ship_postal_code"], o["ship_method"]) == ("Dayton", "OH", "45402", "UPS Ground")
    assert {l["item"]["sku"]: l["qty_ordered"] for l in o["lines"]} == {"TS-BLK-S": 2, "MYSTERY-1": 1}

    # re-sync: no duplicates; the cursor narrows the query
    run = ok(client.post("/api/shopify/sync-orders", headers=admin))
    assert run["summary"]["created"] == 0
    assert "updated_at:>='2026-11-09T11:" not in fake.ops("WmsOrders")[-1]["q"]
    assert "AND updated_at:>='2026-11-09T10:00:00Z'" in fake.ops("WmsOrders")[-1]["q"]

    # quantity edited in Shopify while still NEW -> lines refreshed
    fake.order(2001, tags=["consolidation"], updated="2026-11-09T12:00:00Z",
               lines=[("TS-BLK-S", "Classic Tee - Black / S", 3, 1)])
    run = ok(client.post("/api/shopify/sync-orders", headers=admin))
    assert run["summary"]["updated"] == 1
    o = ok(client.get(f"/api/orders/{o['id']}", headers=admin))
    assert [(l["item"]["sku"], l["qty_ordered"]) for l in o["lines"]] == [("TS-BLK-S", 3)]


def test_cancel_in_shopify(client, admin, fake):
    fake.order(2004, lines=[("TS-BLK-S", "Tee", 1, 1)], updated="2026-11-09T13:00:00Z")
    ok(client.post("/api/shopify/sync-orders", headers=admin))
    oid = ok(client.get("/api/orders", headers=admin, params={"q": "#2004"}))["items"][0]["id"]
    ok(client.post(f"/api/orders/{oid}/release", headers=admin))
    fake.order(2004, lines=[("TS-BLK-S", "Tee", 1, 1)], cancelled=True, updated="2026-11-09T14:00:00Z")
    run = ok(client.post("/api/shopify/sync-orders", headers=admin))
    assert run["summary"]["cancelled"] == 1
    assert ok(client.get(f"/api/orders/{oid}", headers=admin))["status"] == "CANCELLED"


def test_ship_creates_fulfillment(client, admin, fake):
    oid = ok(client.get("/api/orders", headers=admin, params={"q": "#2001"}))["items"][0]["id"]
    item = client.get("/api/items/lookup", params={"code": "TS-BLK-S"}, headers=admin).json()
    o = ok(client.post(f"/api/orders/{oid}/release", headers=admin))
    assert o["status"] == "RELEASED", o
    for t in ok(client.get("/api/tasks", headers=admin, params={"order_id": oid, "open_only": True}))["items"]:
        ok(client.post(f"/api/tasks/{t['id']}/complete", headers=admin, json={}))
    ok(client.post(f"/api/orders/{oid}/pack", headers=admin, json={"carrier": "UPS", "service": "Ground"}))
    ok(client.post(f"/api/orders/{oid}/ship", headers=admin, json={"tracking_number": "1Z999AA10123456784"}))
    o = ok(client.get(f"/api/orders/{oid}", headers=admin))
    assert o["status"] == "SHIPPED" and o["shopify_fulfillment_status"] == "PENDING"
    assert ok(client.get("/api/shopify/store", headers=admin))["pending_fulfillments"] == 1

    run = ok(client.post("/api/shopify/fulfillments", headers=admin))
    assert run["summary"]["fulfilled"] == 1, run
    sent = fake.ops("WmsFulfill")[-1]["fulfillment"]
    assert sent["trackingInfo"] == {"company": "UPS", "number": "1Z999AA10123456784"} and sent["notifyCustomer"] is True
    assert sent["lineItemsByFulfillmentOrder"] == [{
        "fulfillmentOrderId": "gid://shopify/FulfillmentOrder/2001",
        "fulfillmentOrderLineItems": [{"id": "gid://shopify/FulfillmentOrderLineItem/20011", "quantity": 3}]}]
    assert ok(client.get(f"/api/orders/{oid}", headers=admin))["shopify_fulfillment_status"] == "DONE"
    assert item["id"]


def test_fulfillment_failure_and_retry(client, admin, fake):
    oid = ok(client.get("/api/orders", headers=admin, params={"q": "#2001"}))["items"][0]["id"]
    fake.fulfillment_orders["gid://shopify/Order/2001"][0]["status"] = "CLOSED"
    ok(client.post(f"/api/shopify/orders/{oid}/retry-fulfillment", headers=admin))
    run = ok(client.post("/api/shopify/fulfillments", headers=admin))
    assert run["summary"]["failed"] == 1 and "No open fulfillment orders" in run["summary"]["messages"][0]
    o = ok(client.get(f"/api/orders/{oid}", headers=admin))
    assert o["shopify_fulfillment_status"] == "FAILED" and o["shopify_fulfillment_error"]


def test_push_inventory(client, admin, fake):
    tee = client.get("/api/items/lookup", params={"code": "TS-BLK-S"}, headers=admin).json()
    run = ok(client.post("/api/shopify/push-inventory", headers=admin))
    assert run["status"] == "OK", run
    sent = fake.ops("WmsSetInventory")[-1]
    assert "@idempotent(key: $idempotencyKey)" in fake.queries["WmsSetInventory"] and sent["idempotencyKey"]
    assert sent["input"]["name"] == "on_hand" and sent["input"]["reason"] == "correction"
    rows = {q["inventoryItemId"]: q for q in sent["input"]["quantities"]}
    tee_row = rows["gid://shopify/InventoryItem/1"]
    assert tee_row["locationId"] == LOC and "changeFromQuantity" in tee_row and tee_row["changeFromQuantity"] is None
    assert tee_row["quantity"] == tee["on_hand"] - 0       # all AVAILABLE stock in DC1 (none on hold)
    assert rows["gid://shopify/InventoryItem/2"]["quantity"] == 0

    calls = len(fake.ops("WmsSetInventory"))
    run = ok(client.post("/api/shopify/push-inventory", headers=admin))      # nothing changed
    assert run["summary"]["pushed"] == 0 and len(fake.ops("WmsSetInventory")) == calls
    fake.inventory_errors = [{"code": "ITEM_NOT_STOCKED_AT_LOCATION", "field": ["input", "quantities", "1", "locationId"],
                              "message": "The item is not stocked at the location."}]
    run = ok(client.post("/api/shopify/push-inventory", headers=admin, params={"full": True}))
    assert run["summary"]["pushed"] == len(rows) - 1 and run["summary"]["errors"] == 1
    assert "not stocked" in run["summary"]["messages"][0]


def test_scheduler_tick(client, admin, fake):
    from datetime import datetime, timedelta
    ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None, "active": True,
                                                              "orders_since": "2026-11-01T00:00:00"}))
    fake.order(2005, lines=[("NEW-SKU-1", "Brand New Thing", 1, 2)], updated="2026-11-09T15:00:00Z")
    shop_svc.tick(datetime(2026, 11, 9, 15, 5))
    assert ok(client.get("/api/orders", headers=admin, params={"q": "#2005"}))["total"] == 1
    runs = ok(client.get("/api/shopify/runs", headers=admin, params={"kind": "ORDERS"}))["items"]
    assert runs[0]["trigger"] == "SCHEDULED" and runs[0]["summary"]["created"] == 1
    before = len(fake.ops("WmsOrders"))
    shop_svc.tick(datetime(2026, 11, 9, 15, 6))            # within poll interval -> no order poll
    assert len(fake.ops("WmsOrders")) == before
    shop_svc.tick(datetime(2026, 11, 9, 15, 5) + timedelta(minutes=6))
    assert len(fake.ops("WmsOrders")) == before + 1
    ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None, "active": False}))


def test_empty_store_is_explained(client, admin, fake):
    saved_variants, saved_orders = fake.variants, fake.orders
    fake.variants, fake.orders = [], []
    try:
        ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None,
                                                                  "orders_since": "2026-11-08T00:00:00"}))
        run = ok(client.post("/api/shopify/import-products", headers=admin))
        assert run["summary"]["variants_found"] == 0 and "no products" in run["summary"]["messages"][0]
        run = ok(client.post("/api/shopify/sync-orders", headers=admin))
        assert run["summary"]["checked"] == 0 and "no orders created since 2026-11-08" in run["summary"]["messages"][0]
    finally:
        fake.variants, fake.orders = saved_variants, saved_orders


def test_import_stock(client, admin, fake):
    tee = client.get("/api/items/lookup", params={"code": "TS-BLK-S"}, headers=admin).json()   # has WMS stock
    new = client.get("/api/items/lookup", params={"code": "NEW-SKU-1"}, headers=admin).json()  # none yet
    assert new["on_hand"] == 0
    bin_ = client.get("/api/locations/lookup", params={"code": "B-06-01"}, headers=admin).json()
    run = ok(client.post("/api/shopify/import-stock", headers=admin, params={"location_id": bin_["id"]}))
    assert run["status"] == "OK", run
    s = run["summary"]
    assert s["imported_items"] == 1 and s["imported_units"] == 7 and s["skipped_has_stock"] == 1
    new = client.get(f"/api/items/{new['id']}", headers=admin).json()
    assert new["on_hand"] == 7
    bals = ok(client.get("/api/inventory/balances", headers=admin, params={"item_id": new["id"]}))["items"]
    assert [(b["location"]["code"], b["qty_on_hand"]) for b in bals] == [("B-06-01", 7)]
    txn = ok(client.get("/api/inventory/transactions", headers=admin, params={"item_id": new["id"]}))["items"][0]
    assert txn["reason_code"] == "SHOPIFY_IMPORT" and txn["qty"] == 7
    # running again doesn't double up
    run = ok(client.post("/api/shopify/import-stock", headers=admin, params={"location_id": bin_["id"]}))
    assert run["summary"]["imported_items"] == 0 and run["summary"]["skipped_has_stock"] == 2
    assert client.get(f"/api/items/{tee['id']}", headers=admin).json()["on_hand"] == tee["on_hand"]


def test_wrong_location_is_explained(client, admin, fake):
    bin_ = client.get("/api/locations/lookup", params={"code": "B-06-01"}, headers=admin).json()
    ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None,
                                                              "shopify_location_id": "gid://shopify/Location/999"}))
    try:
        for path, params in (("/api/shopify/import-stock", {"location_id": bin_["id"]}), ("/api/shopify/push-inventory", {})):
            run = ok(client.post(path, headers=admin, params=params))
            assert run["status"] == "ERROR" and "switch stores" in run["error"], run
    finally:
        ok(client.put("/api/shopify/store", headers=admin, json={**STORE, "client_secret": None}))
    fake.stock.pop("gid://shopify/InventoryItem/2", None)
    run = ok(client.post("/api/shopify/import-stock", headers=admin, params={"location_id": bin_["id"]}))
    assert "Main warehouse" in run["summary"]["messages"][0]
