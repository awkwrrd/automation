"""End-to-end workflow tests against the API (demo data seeded)."""


def item_by_sku(client, h, sku):
    return client.get("/api/items/lookup", params={"code": sku}, headers=h).json()


def loc(client, h, code):
    r = client.get("/api/locations/lookup", params={"code": code}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def test_auth_required(client):
    assert client.get("/api/items").status_code == 401


def test_operator_cannot_adjust(client, operator):
    r = client.post("/api/inventory/adjust", headers=operator,
                    json={"item_id": 1, "location_id": 1, "qty": 5, "reason_code": "FOUND"})
    assert r.status_code == 403


def test_item_crud_and_duplicate(client, admin):
    body = {"sku": "TEST-1", "name": "Test item", "reorder_point": 5}
    item = ok(client.post("/api/items", json=body, headers=admin), 201)
    assert item["on_hand"] == 0
    assert client.post("/api/items", json=body, headers=admin).status_code == 409
    body["name"] = "Renamed"
    assert ok(client.put(f"/api/items/{item['id']}", json=body, headers=admin))["name"] == "Renamed"


def test_receive_putaway(client, admin):
    item = item_by_sku(client, admin, "TEST-1")
    rcv = ok(client.post("/api/inbound", headers=admin, json={
        "warehouse_id": 1, "lines": [{"item_id": item["id"], "qty_expected": 10}]}), 201)
    line = rcv["lines"][0]
    task = ok(client.post(f"/api/inbound/{rcv['id']}/receive", headers=admin,
                          json={"line_id": line["id"], "qty": 6}))
    assert task["task_type"] == "PUTAWAY" and task["from_location"]["code"] == "DOCK-01"
    assert ok(client.get(f"/api/inbound/{rcv['id']}", headers=admin))["status"] == "RECEIVING"
    ok(client.post(f"/api/inbound/{rcv['id']}/receive", headers=admin, json={"line_id": line["id"], "qty": 4}))
    assert ok(client.get(f"/api/inbound/{rcv['id']}", headers=admin))["status"] == "RECEIVED"

    # complete first putaway into a specific bin, partial then rest
    dest = loc(client, admin, "B-06-03")
    t = ok(client.post(f"/api/tasks/{task['id']}/complete", headers=admin,
                       json={"qty": 2, "to_location_id": dest["id"]}))
    assert t["status"] == "IN_PROGRESS"
    t = ok(client.post(f"/api/tasks/{task['id']}/complete", headers=admin, json={}))
    assert t["status"] == "COMPLETE"
    bals = ok(client.get("/api/inventory/balances", params={"item_id": item["id"]}, headers=admin))["items"]
    by_loc = {b["location"]["code"]: b["qty_on_hand"] for b in bals}
    assert by_loc["B-06-03"] == 6 and by_loc["DOCK-01"] == 4


def test_lot_required(client, admin):
    lot_item = item_by_sku(client, admin, "SNK-GRN-BAR")
    r = client.post("/api/inventory/adjust", headers=admin, json={
        "item_id": lot_item["id"], "location_id": loc(client, admin, "A-01-01")["id"], "qty": 5,
        "reason_code": "FOUND"})
    assert r.status_code == 400 and "lot" in r.json()["detail"]


def test_adjust_move_status(client, admin):
    item = item_by_sku(client, admin, "TEST-1")
    b = loc(client, admin, "B-06-03")
    qa = loc(client, admin, "QA-01")
    ok(client.post("/api/inventory/adjust", headers=admin,
                   json={"item_id": item["id"], "location_id": b["id"], "qty": -1, "reason_code": "DAMAGED"}))
    ok(client.post("/api/inventory/move", headers=admin,
                   json={"item_id": item["id"], "from_location_id": b["id"], "to_location_id": qa["id"], "qty": 2}))
    ok(client.post("/api/inventory/status", headers=admin, json={
        "item_id": item["id"], "location_id": qa["id"], "qty": 2, "from_status": "AVAILABLE", "to_status": "HOLD"}))
    r = client.post("/api/inventory/move", headers=admin,
                    json={"item_id": item["id"], "from_location_id": b["id"], "to_location_id": qa["id"], "qty": 99})
    assert r.status_code == 400
    i = ok(client.get(f"/api/items/{item['id']}", headers=admin))
    assert i["on_hand"] == 9           # 10 received - 1 damaged
    assert i["available"] == 7          # 2 on HOLD are not available
    txns = ok(client.get("/api/inventory/transactions", params={"item_id": item["id"]}, headers=admin))["items"]
    assert {t["txn_type"] for t in txns} >= {"RECEIVE", "PUTAWAY", "ADJUST", "MOVE", "STATUS"}


def test_full_outbound_flow(client, admin, operator):
    item = item_by_sku(client, admin, "TEST-1")   # 3 available in B-06-03 (non-dock, pickable)
    order = ok(client.post("/api/orders", headers=admin, json={
        "warehouse_id": 1, "external_id": "SHOP-9001", "channel": "SHOPIFY", "customer_name": "Test Buyer",
        "lines": [{"item_id": item["id"], "qty_ordered": 3}]}), 201)
    dup = client.post("/api/orders", headers=admin, json={
        "warehouse_id": 1, "external_id": "SHOP-9001", "channel": "SHOPIFY",
        "lines": [{"item_id": item["id"], "qty_ordered": 1}]})
    assert dup.status_code == 409

    o = ok(client.post(f"/api/orders/{order['id']}/allocate", headers=admin))
    assert o["status"] == "ALLOCATED" and o["lines"][0]["qty_allocated"] == 3
    assert ok(client.get(f"/api/items/{item['id']}", headers=admin))["available"] == 4  # 7 - 3

    o = ok(client.post(f"/api/orders/{order['id']}/release", headers=admin))
    assert o["status"] == "RELEASED"
    picks = ok(client.get("/api/tasks", params={"order_id": order["id"], "open_only": True}, headers=operator))["items"]
    assert len(picks) >= 1 and all(p["to_location"]["code"] == "STAGE-01" for p in picks)
    for p in picks:
        ok(client.post(f"/api/tasks/{p['id']}/complete", headers=operator, json={}))
    o = ok(client.get(f"/api/orders/{order['id']}", headers=admin))
    assert o["status"] == "PICKED" and o["lines"][0]["qty_picked"] == 3
    # picked stock is staged & still reserved -> not available for other orders
    assert ok(client.get(f"/api/items/{item['id']}", headers=admin))["available"] == 4

    ship = ok(client.post(f"/api/orders/{order['id']}/pack", headers=operator,
                          json={"carrier": "UPS", "service": "Ground", "weight": "1.2"}))
    assert ship["status"] == "PACKED"
    ship = ok(client.post(f"/api/orders/{order['id']}/ship", headers=operator, json={"tracking_number": "1Z999"}))
    assert ship["status"] == "SHIPPED" and ship["tracking_number"] == "1Z999"
    o = ok(client.get(f"/api/orders/{order['id']}", headers=admin))
    assert o["status"] == "SHIPPED" and o["lines"][0]["qty_shipped"] == 3
    i = ok(client.get(f"/api/items/{item['id']}", headers=admin))
    assert i["on_hand"] == 6 and i["allocated"] == 0


def test_short_pick_and_cancel(client, admin):
    item = item_by_sku(client, admin, "HD-GRY-L")
    before = ok(client.get(f"/api/items/{item['id']}", headers=admin))
    order = ok(client.post("/api/orders", headers=admin, json={
        "warehouse_id": 1, "lines": [{"item_id": item["id"], "qty_ordered": 4}]}), 201)
    ok(client.post(f"/api/orders/{order['id']}/release", headers=admin))
    pick = ok(client.get("/api/tasks", params={"order_id": order["id"], "open_only": True}, headers=admin))["items"][0]
    ok(client.post(f"/api/tasks/{pick['id']}/complete", headers=admin, json={"qty": 1}))   # short by 3
    o = ok(client.get(f"/api/orders/{order['id']}", headers=admin))
    assert o["status"] == "PICKED"
    assert o["lines"][0]["qty_picked"] == 1 and o["lines"][0]["qty_allocated"] == 1
    ok(client.post(f"/api/orders/{order['id']}/cancel", headers=admin))
    after = ok(client.get(f"/api/items/{item['id']}", headers=admin))
    assert after["on_hand"] == before["on_hand"] and after["allocated"] == 0
    # cancelled stock sits un-reserved in staging, so it's not counted as sellable until put back
    assert after["available"] == before["available"] - 1


def test_insufficient_stock_partial_allocation(client, admin):
    item = item_by_sku(client, admin, "CNDL-LAV")
    order = ok(client.post("/api/orders", headers=admin, json={
        "warehouse_id": 1, "lines": [{"item_id": item["id"], "qty_ordered": 1000}]}), 201)
    o = ok(client.post(f"/api/orders/{order['id']}/allocate", headers=admin))
    assert o["status"] == "PARTIALLY_ALLOCATED"
    ok(client.post(f"/api/orders/{order['id']}/deallocate", headers=admin))
    assert ok(client.get(f"/api/orders/{order['id']}", headers=admin))["status"] == "NEW"


def test_wave(client, admin):
    orders = ok(client.get("/api/orders", params={"status": "NEW", "unwaved": True, "q": "#100"}, headers=admin))["items"]
    ids = [o["id"] for o in orders[:3]]
    wave = ok(client.post("/api/waves", headers=admin, json={"warehouse_id": 1, "order_ids": ids}), 201)
    assert wave["order_count"] == 3
    res = ok(client.post(f"/api/waves/{wave['id']}/release", headers=admin))
    assert res["tasks_created"] >= 3
    w = ok(client.get(f"/api/waves/{wave['id']}", headers=admin))
    assert w["status"] == "RELEASED" and w["open_tasks"] == res["tasks_created"]
    for t in ok(client.get("/api/tasks", params={"wave_id": wave["id"], "open_only": True}, headers=admin))["items"]:
        ok(client.post(f"/api/tasks/{t['id']}/complete", headers=admin, json={}))
    assert ok(client.get(f"/api/waves/{wave['id']}", headers=admin))["status"] == "COMPLETE"


def test_cycle_count(client, admin):
    item = item_by_sku(client, admin, "STKR-PK")
    bal = ok(client.get("/api/inventory/balances", params={"item_id": item["id"]}, headers=admin))["items"][0]
    count = ok(client.post("/api/counts", headers=admin, json={
        "warehouse_id": 1, "location_ids": [bal["location"]["id"]], "blind": True}), 201)
    line = next(l for l in count["lines"] if l["item"]["id"] == item["id"])
    assert client.post(f"/api/counts/{count['id']}/complete", headers=admin).status_code == 400  # uncounted
    entries = [{"line_id": l["id"], "counted_qty": l["expected_qty"]} for l in count["lines"]]
    for e in entries:
        if e["line_id"] == line["id"]:
            e["counted_qty"] = bal["qty_on_hand"] - 5
    ok(client.post(f"/api/counts/{count['id']}/record", headers=admin, json=entries))
    done = ok(client.post(f"/api/counts/{count['id']}/complete", headers=admin))
    assert done["status"] == "COMPLETED"
    assert next(l for l in done["lines"] if l["id"] == line["id"])["adjusted_qty"] == -5
    txns = ok(client.get("/api/inventory/transactions", params={"item_id": item["id"], "txn_type": "COUNT"},
                         headers=admin))["items"]
    assert txns[0]["qty"] == -5 and txns[0]["reference_number"] == done["number"]


def test_csv_roundtrip(client, admin):
    csv = client.get("/api/items/export.csv", headers=admin).text
    assert csv.startswith("sku,name")
    data = "sku,name,price,reorder_point\nCSV-NEW,Imported thing,9.99,3\nTEST-1,,,7\n"
    res = ok(client.post("/api/items/import", headers=admin, files={"file": ("i.csv", data, "text/csv")}))
    assert res == {"created": 1, "updated": 1, "errors": []}
    assert item_by_sku(client, admin, "TEST-1")["reorder_point"] == 7


def test_generate_locations_and_dashboard(client, admin):
    res = ok(client.post("/api/locations/generate", headers=admin, json={
        "warehouse_id": 1, "aisles": ["C"], "bay_from": 1, "bay_to": 2, "level_from": 1, "level_to": 2}))
    assert res["created"] == 4
    assert ok(client.post("/api/locations/generate", headers=admin, json={
        "warehouse_id": 1, "aisles": ["C"], "bay_from": 1, "bay_to": 2}))["skipped_existing"] == 2
    d = ok(client.get("/api/dashboard", headers=admin))
    assert d["units_on_hand"] > 0 and len(d["throughput"]) == 7
