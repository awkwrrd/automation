"""Reference receiver for WMS outbound events -- a starting point for a SOFTBOT.

Standard library only. It:
  1. listens for POSTs from the WMS,
  2. checks the bearer token and the X-WMS-Signature HMAC,
  3. de-duplicates by X-WMS-Delivery,
  4. prints each event and its tasks,
  5. optionally (--auto-confirm) reports every task as done via the WMS confirmations API,
     the same way a robot controller would after executing the work.

Usage:
  python tools/mock_softbot.py --port 9000 --secret <signing secret> --token <bearer token>
  python tools/mock_softbot.py --port 9000 --secret ... --auto-confirm --api-key wms_... [--wms http://localhost:8000]

Then in the WMS: Configuration -> Integrations -> New endpoint, URL http://localhost:9000/wms/events
"""
import argparse
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

seen_deliveries: set[str] = set()
MAX_CLOCK_SKEW = 300  # seconds; rejects replayed old messages


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def confirm(wms: str, api_key: str, tasks: list[dict]) -> None:
    """POST /api/automation/confirmations -- what a robot controller calls when work is done."""
    body = json.dumps({"confirmations": [{"task_id": t["task_id"], "qty": t["qty"]} for t in tasks]}).encode()
    req = urllib.request.Request(f"{wms}/api/automation/confirmations", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=10) as r:
        for res in json.loads(r.read()):
            print(f"    confirm task {res['task_id']}: {'OK' if res['ok'] else 'FAILED'} "
                  f"{res.get('status') or ''} {res.get('error') or ''}")


def make_handler(args):
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, obj: dict) -> None:
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if args.token and self.headers.get("Authorization") != f"Bearer {args.token}":
                return self._reply(401, {"error": "bad token"})
            ts = self.headers.get("X-WMS-Timestamp", "")
            if args.secret:
                if not verify_signature(args.secret, ts, body, self.headers.get("X-WMS-Signature")):
                    return self._reply(401, {"error": "bad signature"})
                if not ts.isdigit() or abs(time.time() - int(ts)) > MAX_CLOCK_SKEW:
                    return self._reply(401, {"error": "stale timestamp"})
            delivery = self.headers.get("X-WMS-Delivery", "")
            if delivery in seen_deliveries:  # WMS retried something we already processed
                return self._reply(200, {"duplicate": True})
            seen_deliveries.add(delivery)

            msg = json.loads(body)
            data = msg["data"]
            print(f"\n<= {msg['event']}  delivery={msg['delivery_id']}  warehouse={(msg.get('warehouse') or {}).get('code')}")
            if msg["event"] == "wave.released":
                print(f"   wave {data['wave']['number']}: {len(data['orders'])} order(s), {len(data['tasks'])} task(s)")
            for t in data.get("tasks", []):
                if "item" in t:
                    print(f"   task {t['task_id']:>5} {t['task_type']:<8} {t['qty']:>4} x {t['item']['sku']:<14} "
                          f"{(t['from_location'] or {}).get('code', ''):>10} -> {(t['to_location'] or {}).get('code', '')}"
                          f"   order {t.get('order_number') or '-'}")
                else:
                    print(f"   CANCEL task {t['task_id']} ({t['sku']} x {t['qty']}): {data.get('reason')}")

            # acknowledge fast; do the work asynchronously (never make the WMS wait on robots)
            self._reply(200, {"accepted": True, "delivery_id": msg["delivery_id"]})
            work = [t for t in data.get("tasks", []) if "item" in t]
            if args.auto_confirm and work and msg["event"] != "test":
                threading.Timer(args.delay, confirm, (args.wms.rstrip("/"), args.api_key, work)).start()

        def log_message(self, *a):
            pass

    return Handler


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--secret", help="endpoint signing secret (verifies X-WMS-Signature)")
    p.add_argument("--token", help="expected bearer token (endpoint auth type 'Bearer')")
    p.add_argument("--auto-confirm", action="store_true", help="confirm every received task back to the WMS")
    p.add_argument("--api-key", help="WMS API key used for confirmations")
    p.add_argument("--wms", default="http://localhost:8000", help="WMS base URL")
    p.add_argument("--delay", type=float, default=3.0, help="seconds to 'execute' before confirming")
    a = p.parse_args()
    if a.auto_confirm and not a.api_key:
        p.error("--auto-confirm needs --api-key")
    print(f"Mock SOFTBOT listening on http://0.0.0.0:{a.port}/  (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(a)).serve_forever()
