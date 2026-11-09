# Pushing work to a robotics platform (e.g. SOFTBOT)

The WMS **pushes** events to external systems over HTTPS (JSON `POST`). Your system acknowledges with any
`2xx`, does the work, and reports results back through the confirmations API using an API key.

```
 WMS                                   SOFTBOT (your receiver)
  │  wave released ──► outbox (DB) ──► POST /your/url   {event: "wave.released", tasks: [...]}
  │                                    ◄── 200 {"accepted": true}       (ack fast, work async)
  │                                         … robots execute …
  │  ◄── POST /api/automation/confirmations  X-API-Key: wms_…   [{task_id, qty}, …]
  ▼  tasks COMPLETE, order → PICKED, ready to pack
```

## 1. Configure it in the GUI (Admin)

1. **Service user:** *Configuration → Users → New user*. Username `softbot`, role **OPERATOR**, any long password
   (it never logs in interactively). Its role limits what the API key can do.
2. **API key (inbound):** *Configuration → Integrations → New API key*. Name it (e.g. `softbot-prod`) and link it
   to `softbot`. **Copy the key now**, because it is shown only once. Your SOFTBOT sends it as `X-API-Key: wms_…`.
3. **Endpoint (outbound):** *Configuration → Integrations → New endpoint*:

   | Field | What to enter |
   |---|---|
   | Name | `SOFTBOT`. Tasks sent to it show **→ SOFTBOT** in the Task Queue |
   | URL | Where SOFTBOT listens, e.g. `https://softbot.local:9000/wms/events` |
   | Events | Usually `wave.released`, `order.released`, `task.cancelled` (+ `putaway.created` if robots do putaway, `test` for the test button) |
   | Warehouse | The site the robots work in |
   | Zones | Tick only the zones the robots serve (e.g. an AMR zone). Tasks in other zones stay with people. None ticked = all zones |
   | Task ownership | Leave ticked so robot tasks are assigned to the endpoint and floor staff leave them alone |
   | Authentication | How SOFTBOT authenticates the WMS: *Bearer token*, *API key header* (custom header name), or *Basic* |
   | Signing secret | Click **Generate** and copy it into SOFTBOT. Every request is then HMAC-signed (see §4) |
   | Timeout / Max attempts | Defaults 10 s / 8 attempts. Retries back off 10 s, 20 s, 40 s … up to 15 min |
   | Extra headers | Optional static headers as JSON, e.g. `{"X-Site": "DC1"}` |

4. Click **Send test**. You should see `SENT · HTTP 200` and SOFTBOT should log a `test` event.
5. Release a wave (*Orders → select → Create wave*). Watch *Configuration → Message Log* for its delivery.

> **Zones are the routing switch.** To make a location robot-served, put it in the robot zone
> (*Configuration → Locations*, or **Bulk generate** with that zone). Allocation is unchanged. Only
> who executes the pick differs.

Set `WMS_PUBLIC_URL` in `.env` to the address SOFTBOT should use to reach the WMS (default
`http://localhost:8000`). It is included in every payload as `callbacks.confirm_tasks`.

> **Running the WMS with Docker Compose?** Inside the container, `localhost` means the container itself.
> If SOFTBOT (or `tools/mock_softbot.py`) runs on the same PC, use `http://host.docker.internal:9000/...`
> as the endpoint URL. If it runs on another machine, use that machine's IP or hostname. Compose reads `.env`
> from the project folder, so `WMS_PUBLIC_URL` set there is passed into the container.

## 2. Try it with the reference receiver

`tools/mock_softbot.py` is a working receiver (standard library only). Use it as the skeleton for your SOFTBOT:

```bash
python tools/mock_softbot.py --port 9000 --secret <signing secret> --token <bearer token> --auto-confirm --api-key wms_... --wms http://localhost:8000
```
Point the endpoint URL at `http://localhost:9000/wms/events`, release a wave, and it prints the tasks,
waits `--delay` seconds, then confirms them, so the tasks complete in the WMS.

## 3. What the WMS sends

Every request: `POST <url>` with `Content-Type: application/json` and these headers:

| Header | Meaning |
|---|---|
| `X-WMS-Event` | `wave.released`, `order.released`, `putaway.created`, `task.cancelled`, `test` |
| `X-WMS-Delivery` | Unique message id. **Retries reuse it**, so store it and ignore duplicates |
| `X-WMS-Timestamp` | Unix seconds when sent |
| `X-WMS-Signature` | `sha256=<hex>` if a signing secret is set (§4) |
| `Authorization` / your header | Per the endpoint's authentication setting |

Example `wave.released` (trimmed to one order and one task):

```json
{
  "event": "wave.released",
  "delivery_id": 2,
  "schema_version": "1.0",
  "occurred_at": "2026-11-09T14:58:03.643361Z",
  "warehouse": {
    "id": 1,
    "code": "DC1"
  },
  "data": {
    "wave": {
      "id": 1,
      "number": "WAV000001",
      "description": null,
      "released_at": "2026-11-09T14:58:03.637165Z"
    },
    "orders": [
      {
        "id": 3,
        "number": "ORD000003",
        "external_id": "#1003",
        "channel": "SHOPIFY",
        "priority": 5,
        "customer_name": "Chris Wong",
        "ship_method": "Ground",
        "requested_ship_date": null,
        "ship_to": {
          "name": "Chris Wong",
          "address1": "114 Main St",
          "address2": null,
          "city": "Denver",
          "state": "CO",
          "postal_code": "00000",
          "country": "US"
        },
        "lines": [
          {
            "line_no": 1,
            "sku": "MUG-12OZ",
            "qty_ordered": 4
          },
          {
            "line_no": 2,
            "sku": "CNDL-CED",
            "qty_ordered": 1
          },
          {
            "line_no": 3,
            "sku": "CNDL-LAV",
            "qty_ordered": 1
          }
        ]
      }
    ],
    "tasks": [
      {
        "task_id": 17,
        "task_type": "PICK",
        "priority": 5,
        "item": {
          "id": 9,
          "sku": "MUG-12OZ",
          "name": "Ceramic Mug 12oz",
          "barcode": "000511466046",
          "uom": "EA",
          "weight": 0.9,
          "weight_unit": "lb",
          "lot_tracked": false
        },
        "lot_number": null,
        "qty": 4,
        "from_location": {
          "id": 11,
          "code": "A-03-03",
          "zone": "FWD",
          "type": "BIN",
          "aisle": "A",
          "bay": "03",
          "level": "03",
          "position": null,
          "sequence": 110
        },
        "to_location": {
          "id": 55,
          "code": "STAGE-01",
          "zone": "SHP",
          "type": "STAGING",
          "aisle": null,
          "bay": null,
          "level": null,
          "position": null,
          "sequence": 550
        },
        "order_id": 3,
        "order_number": "ORD000003",
        "reference": "ORD000003"
      }
    ]
  },
  "callbacks": {
    "confirm_tasks": "http://localhost:8000/api/automation/confirmations"
  }
}
```

- `data.tasks[].qty` is the quantity **still to do**. `from_location` / `to_location` carry code, zone, aisle,
  bay, level and `sequence` (walk order). A pick's `to_location` is the outbound staging lane.
- `order.released`: same as above but `data.order` (one order) instead of `wave` and `orders`.
- `putaway.created`: `data.receipt` + `data.tasks` (from the dock to the suggested storage location; routed by the destination zone).
- `task.cancelled`: `data.reason` + `data.tasks[] = {task_id, task_type, order_id, reference, sku, qty, qty_done}`.
  Sent when an order is cancelled/unallocated or a supervisor cancels a task. Stop any work on those ids.

**Delivery guarantees**
- Messages are written in the same DB transaction as the change (no lost or phantom events).
- **In order per endpoint.** If one message is retrying, later ones wait, so `task.cancelled` never overtakes the release it refers to.
- **At-least-once.** De-duplicate on `X-WMS-Delivery`.
- `2xx` = delivered. `408`, `429`, `5xx`, timeouts and connection errors are retried. Other `4xx` fail immediately
  (fix the cause, then **Retry** in the Message Log). After *max attempts* the message is `FAILED`.
- Reply quickly (well under the timeout) and do the robot work asynchronously.
- Run the WMS as a single process (`uvicorn` with one worker) so only one dispatcher sends.

## 4. Verifying the signature

`signature = "sha256=" + hex(HMAC_SHA256(secret, timestamp + "." + raw_body))`. Use the **raw** body bytes
before JSON parsing, compare in constant time, and reject timestamps more than ~5 minutes old.

```python
import hashlib, hmac, time
def verify(secret: str, headers, raw_body: bytes) -> bool:
    ts = headers["X-WMS-Timestamp"]
    expected = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers.get("X-WMS-Signature", "")) and abs(time.time() - int(ts)) < 300
```
```js
const crypto = require("crypto");
function verify(secret, headers, rawBody /* Buffer */) {
  const ts = headers["x-wms-timestamp"];
  const expected = "sha256=" + crypto.createHmac("sha256", secret).update(ts + ".").update(rawBody).digest("hex");
  const got = Buffer.from(headers["x-wms-signature"] || "");
  return got.length === expected.length && crypto.timingSafeEqual(got, Buffer.from(expected))
    && Math.abs(Date.now() / 1000 - Number(ts)) < 300;
}
```

## 5. Reporting work back: `POST /api/automation/confirmations`

```http
POST /api/automation/confirmations
X-API-Key: wms_...
Content-Type: application/json

{"confirmations": [
  {"task_id": 17},                                  // done, full remaining qty, default staging lane
  {"task_id": 18, "qty": 0},                        // pick: nothing found -> short pick, reservation released
  {"task_id": 19, "qty": 1, "to_location_code": "STAGE-02"},  // partial / different drop location
  {"task_id": 31, "to_location_code": "A-04-02"}    // putaway/move: where it was actually put
]}
```
Response (one result per confirmation, applied independently):
```json
[{"task_id": 17, "ok": true,  "status": "COMPLETE", "qty_done": 4, "error": null},
 {"task_id": 18, "ok": true,  "status": "COMPLETE", "qty_done": 0, "error": null},
 {"task_id": 99, "ok": false, "status": null, "qty_done": null, "error": "Task not found"}]
```
- `qty` omitted = the whole remaining quantity. For picks, less than remaining = **short pick**: the rest is
  un-reserved and the order can be re-allocated. Putaways and moves can be confirmed in several partial calls.
- Re-sending a finished task returns `ok: false, status: "COMPLETE"`, so retrying a timed-out call is safe.
- Picks must drop to a STAGING location. Once all picks are done the order is `PICKED` and appears in *Pack & Ship*.
- All other APIs (inventory lookups, `GET /api/tasks?assigned_to=SOFTBOT&open_only=true` to reconcile, etc.)
  also accept the API key. Full interactive reference: `http://<wms>/docs`.

## 6. Operating it

- **Message Log** (*Configuration → Message Log*): every delivery with status, attempts, HTTP code, error,
  full payload and response. **Retry** / **Re-send** a message, or **Cancel** a pending one.
- The *Integrations* list shows each endpoint's pending and failed counts and the last delivery time.
- Deactivating an endpoint pauses delivery. Its messages wait and send when it is re-activated.
- A supervisor can still execute a robot task by hand in the Task Queue (manual override). The dialog warns that it belongs to automation.
