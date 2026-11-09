"""Outbound integration (push to a robotics platform) + API-key confirmations."""
import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.db import SessionLocal
from app.models import OutboundMessage
from app.services.dispatcher import dispatch_once


class Receiver(BaseHTTPRequestHandler):
    """Stand-in for SOFTBOT: records requests, replies with queued status codes (default 200)."""
    received: list[tuple[dict, bytes]] = []
    replies: list[int] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Receiver.received.append(({k.lower(): v for k, v in self.headers.items()}, body))
        code = Receiver.replies.pop(0) if Receiver.replies else 200
        self.send_response(code)
        self.end_headers()
        self.wfile.write(b'{"accepted": true}')

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def receiver():
    srv = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/wms/events"
    srv.shutdown()


@pytest.fixture(scope="module")
def http():
    with httpx.Client() as c:
        yield c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def drain(http):
    """Deliver everything that is due right now."""
    while dispatch_once(http):
        pass


def make_due():
    """Pretend backoff time has passed."""
    with SessionLocal() as db:
        for m in db.query(OutboundMessage).filter(OutboundMessage.status == "PENDING"):
            m.next_attempt_at = None
        db.commit()


@pytest.fixture(scope="module")
def setup(client, admin, receiver):
    """A robot zone with its own locations and stock, an item in the manual zone, and an endpoint
    that only receives tasks for the robot zone."""
    zone = ok(client.post("/api/zones", headers=admin, json={
        "warehouse_id": 1, "code": "AMR", "name": "Robot storage", "zone_type": "PICK"}), 201)
    ok(client.post("/api/locations/generate", headers=admin, json={
        "warehouse_id": 1, "zone_id": zone["id"], "aisles": ["R9"], "bay_from": 1, "bay_to": 2,
        "level_from": 1, "level_to": 1}))
    robo_loc = client.get("/api/locations/lookup", params={"code": "R9-01-01"}, headers=admin).json()
    manual_loc = client.get("/api/locations/lookup", params={"code": "B-05-01"}, headers=admin).json()
    robo_item = ok(client.post("/api/items", headers=admin, json={"sku": "AMR-1", "name": "Robot item"}), 201)
    manual_item = ok(client.post("/api/items", headers=admin, json={"sku": "MAN-1", "name": "Manual item"}), 201)
    for item, loc in ((robo_item, robo_loc), (manual_item, manual_loc)):
        ok(client.post("/api/inventory/adjust", headers=admin, json={
            "item_id": item["id"], "location_id": loc["id"], "qty": 50, "reason_code": "FOUND"}))
    ep = ok(client.post("/api/automation/endpoints", headers=admin, json={
        "name": "SOFTBOT", "url": receiver, "warehouse_id": 1, "zone_ids": [zone["id"]],
        "events": ["wave.released", "order.released", "task.cancelled", "test"],
        "auth_type": "BEARER", "auth_value": "softbot-token-123", "signing_secret": "s3cret-signing-key",
        "extra_headers": {"X-Site": "DC1"}}), 201)
    yield {"ep": ep, "robo_item": robo_item, "manual_item": manual_item, "zone": zone}
    # don't let this endpoint influence other test modules
    body = {**ep, "active": False}
    for k in ("id", "auth_value_hint", "has_signing_secret", "created_at", "pending", "failed", "last_sent_at"):
        body.pop(k, None)
    ok(client.put(f"/api/automation/endpoints/{ep['id']}", headers=admin, json=body))


def new_order(client, admin, setup, lines):
    return ok(client.post("/api/orders", headers=admin, json={
        "warehouse_id": 1, "customer_name": "Robo Customer",
        "lines": [{"item_id": setup[k]["id"], "qty_ordered": q} for k, q in lines]}), 201)


def test_secrets_are_masked(client, admin, setup):
    eps = ok(client.get("/api/automation/endpoints", headers=admin))
    ep = next(e for e in eps if e["name"] == "SOFTBOT")
    assert ep["auth_value_hint"] == "••••-123" and ep["has_signing_secret"] is True
    assert "softbot-token-123" not in json.dumps(eps) and "s3cret" not in json.dumps(eps)


def test_test_button(client, admin, setup):
    Receiver.received.clear()
    res = ok(client.post(f"/api/automation/endpoints/{setup['ep']['id']}/test", headers=admin))
    assert res["status"] == "SENT" and res["response_code"] == 200
    headers, body = Receiver.received[-1]
    assert headers["x-wms-event"] == "test" and json.loads(body)["event"] == "test"


def test_wave_release_pushes_only_robot_zone_tasks(client, admin, setup, http):
    Receiver.received.clear()
    o1 = new_order(client, admin, setup, [("robo_item", 3), ("manual_item", 2)])
    o2 = new_order(client, admin, setup, [("robo_item", 1)])
    wave = ok(client.post("/api/waves", headers=admin, json={"warehouse_id": 1, "order_ids": [o1["id"], o2["id"]]}), 201)
    ok(client.post(f"/api/waves/{wave['id']}/release", headers=admin))

    # queued in the outbox, nothing sent until the dispatcher runs
    assert Receiver.received == []
    msgs = ok(client.get("/api/automation/messages", headers=admin, params={"event": "wave.released"}))["items"]
    assert msgs[0]["status"] == "PENDING" and msgs[0]["reference"] == wave["number"]
    drain(http)

    headers, body = Receiver.received[-1]
    payload = json.loads(body)
    assert headers["authorization"] == "Bearer softbot-token-123" and headers["x-site"] == "DC1"
    assert headers["x-wms-event"] == "wave.released" and headers["x-wms-delivery"] == str(payload["delivery_id"])
    expected = "sha256=" + hmac.new(b"s3cret-signing-key", headers["x-wms-timestamp"].encode() + b"." + body,
                                    hashlib.sha256).hexdigest()
    assert headers["x-wms-signature"] == expected

    data = payload["data"]
    assert payload["warehouse"]["code"] == "DC1" and data["wave"]["number"] == wave["number"]
    assert {t["item"]["sku"] for t in data["tasks"]} == {"AMR-1"}           # manual-zone pick excluded
    assert sorted(t["qty"] for t in data["tasks"]) == [1, 3]
    assert all(t["from_location"]["zone"] == "AMR" and t["to_location"]["type"] == "STAGING" for t in data["tasks"])
    assert {o["number"] for o in data["orders"]} == {o1["number"], o2["number"]}
    assert payload["callbacks"]["confirm_tasks"].endswith("/api/automation/confirmations")

    tasks = ok(client.get("/api/tasks", headers=admin, params={"wave_id": wave["id"]}))["items"]
    robot = [t for t in tasks if t["item"]["sku"] == "AMR-1"]
    manual = [t for t in tasks if t["item"]["sku"] == "MAN-1"]
    assert all(t["assigned_to"] == "SOFTBOT" and t["dispatch_endpoint_id"] == setup["ep"]["id"] for t in robot)
    assert all(t["dispatch_endpoint_id"] is None for t in manual)
    setup["wave_tasks"] = [t["id"] for t in robot]
    setup["wave_orders"] = [o1, o2]


def test_confirm_with_api_key(client, admin, setup):
    users = ok(client.get("/api/users", headers=admin))
    svc = ok(client.post("/api/users", headers=admin, json={
        "username": "softbot", "full_name": "SOFTBOT service", "role": "OPERATOR", "password": "x" * 20}), 201) \
        if not any(u["username"] == "softbot" for u in users) else next(u for u in users if u["username"] == "softbot")
    key = ok(client.post("/api/automation/api-keys", headers=admin, json={"name": "softbot", "user_id": svc["id"]}), 201)
    assert key["key"].startswith("wms_")
    kh = {"X-API-Key": key["key"]}

    t_full, t_short = setup["wave_tasks"]
    res = ok(client.post("/api/automation/confirmations", headers=kh, json={"confirmations": [
        {"task_id": t_full},                               # full qty, default staging drop
        {"task_id": t_short, "qty": 0},                    # robot found nothing: short pick
        {"task_id": 999999},                               # unknown task does not break the batch
    ]}))
    assert [r["ok"] for r in res] == [True, True, False] and "not found" in res[2]["error"]
    again = ok(client.post("/api/automation/confirmations", headers={"Authorization": f"Bearer {key['key']}"},
                           json={"confirmations": [{"task_id": t_full}]}))
    assert again[0]["ok"] is False and again[0]["status"] == "COMPLETE"   # idempotent-safe retry

    task = ok(client.get(f"/api/tasks/{t_full}", headers=admin))
    assert task["completed_by"] == "softbot"
    # operator-role key cannot reach admin endpoints
    assert client.get("/api/automation/api-keys", headers=kh).status_code == 403
    ok(client.post(f"/api/automation/api-keys/{key['id']}/revoke", headers=admin))
    assert client.get("/api/items", headers=kh).status_code == 401


def test_cancel_notifies_robot_in_order(client, admin, setup, http):
    Receiver.received.clear()
    o = new_order(client, admin, setup, [("robo_item", 2)])
    ok(client.post(f"/api/orders/{o['id']}/release", headers=admin))
    Receiver.replies[:] = [503]                      # SOFTBOT briefly down
    drain(http)
    ok(client.post(f"/api/orders/{o['id']}/cancel", headers=admin))
    drain(http)                                      # release msg is backing off -> cancel must wait behind it
    assert len(Receiver.received) == 1
    msgs = ok(client.get("/api/automation/messages", headers=admin, params={"q": o["number"]}))["items"]
    by_event = {m["event"]: m for m in msgs}
    assert by_event["order.released"]["status"] == "PENDING" and by_event["order.released"]["attempts"] == 1
    assert by_event["order.released"]["last_error"] == "HTTP 503"
    assert by_event["task.cancelled"]["status"] == "PENDING" and by_event["task.cancelled"]["attempts"] == 0

    make_due()
    drain(http)
    events = [json.loads(b)["event"] for _, b in Receiver.received]
    assert events == ["order.released", "order.released", "task.cancelled"]
    cancelled = json.loads(Receiver.received[-1][1])["data"]
    assert cancelled["tasks"][0]["sku"] == "AMR-1" and "cancel" in cancelled["reason"].lower()


def test_permanent_failure_and_retry(client, admin, setup, http):
    Receiver.received.clear()
    o = new_order(client, admin, setup, [("robo_item", 1)])
    ok(client.post(f"/api/orders/{o['id']}/release", headers=admin))
    Receiver.replies[:] = [400]
    drain(http)
    msg = ok(client.get("/api/automation/messages", headers=admin, params={"q": o["number"]}))["items"][0]
    assert msg["status"] == "FAILED" and msg["attempts"] == 1
    detail = ok(client.get(f"/api/automation/messages/{msg['id']}", headers=admin))
    assert json.loads(detail["payload"])["event"] == "order.released"
    ok(client.post(f"/api/automation/messages/{msg['id']}/retry", headers=admin))
    drain(http)
    assert ok(client.get(f"/api/automation/messages/{msg['id']}", headers=admin))["status"] == "SENT"
    assert [h["x-wms-delivery"] for h, _ in Receiver.received] == [str(msg["id"])] * 2  # same id -> receiver can de-dupe


def test_existing_db_gets_new_columns(tmp_path):
    """Upgrading: a database created before this feature gains the new nullable task column."""
    from sqlalchemy import create_engine, inspect, text
    from app.db import add_missing_columns
    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, task_type VARCHAR(24))"))
    added = add_missing_columns(eng)
    assert "tasks.dispatch_endpoint_id" in added
    assert "dispatch_endpoint_id" in {c["name"] for c in inspect(eng).get_columns("tasks")}
