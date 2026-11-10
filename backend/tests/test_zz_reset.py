"""Runs last (it wipes the shared test database)."""
from app import reset


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def test_reset_keeps_configuration(client, admin):
    before_locs = ok(client.get("/api/locations", headers=admin, params={"limit": 1}))["total"]
    assert ok(client.get("/api/items", headers=admin))["total"] > 0
    assert reset.main(["--yes"]) == 0
    assert ok(client.get("/api/items", headers=admin))["total"] == 0
    assert ok(client.get("/api/orders", headers=admin))["total"] == 0
    assert ok(client.get("/api/inventory/balances", headers=admin))["total"] == 0
    assert ok(client.get("/api/inventory/transactions", headers=admin))["total"] == 0
    assert ok(client.get("/api/tasks", headers=admin))["total"] == 0
    # configuration survives; the admin's login still works
    assert ok(client.get("/api/locations", headers=admin, params={"limit": 1}))["total"] == before_locs
    assert len(ok(client.get("/api/warehouses", headers=admin))) == 1
    assert ok(client.get("/api/automation/endpoints", headers=admin))
    store = ok(client.get("/api/shopify/store", headers=admin))
    assert store and store["orders_cursor"] is None
    # numbering restarts
    o = ok(client.post("/api/items", headers=admin, json={"sku": "FRESH-1", "name": "Fresh"}), 201)
    order = ok(client.post("/api/orders", headers=admin, json={"warehouse_id": 1,
                                                              "lines": [{"item_id": o["id"], "qty_ordered": 1}]}), 201)
    assert order["number"] == "ORD000001"


def test_reset_all(client, admin):
    assert reset.main(["--all", "--yes"]) == 0
    # recreated from scratch: fresh admin + (in tests) demo data again; old token still valid for same username
    assert ok(client.get("/api/items", headers=admin))["total"] > 0
    assert ok(client.get("/api/automation/endpoints", headers=admin)) == []
    assert ok(client.get("/api/shopify/store", headers=admin)) is None
