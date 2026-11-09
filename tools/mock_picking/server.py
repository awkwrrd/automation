"""Stand-in for a picking system (KFX, AutoStore, ...) during proofs of concept.

Accepts what an outbound signal_to_http SOFTBOT sends and answers like a healthy system:
  POST <any path>          JSON body -> 200 {"accepted": true, ...} and the message is recorded
  POST /token              OAuth2 client-credentials token endpoint (for AuthType "OAuth2")
  GET  /                   web page listing the received messages (newest first, auto-refresh)
  GET  /_messages          the same as JSON;  DELETE /_messages clears them
  GET  /health             200 "ok"

Authentication is accepted whatever it is (none, x-api-key, Basic, Bearer) and shown on the page.
Set --api-key / --basic to *require* a specific credential instead. With an API key set (also via the
MOCK_API_KEY environment variable) the messages page needs it too: open /?key=<key>. Use this whenever
the mock is reachable from the internet (e.g. through a tunnel).

Testing failure handling: add ?status=503 (or any code) to the SOFTBOT's URL path, or start with
--status 500 / --delay 5 to make every response fail or be slow.

Standard library only:  python tools/mock_picking/server.py --port 9100
"""
import argparse
import base64
import html
import json
import os
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MESSAGES: deque = deque(maxlen=500)
LOCK = threading.Lock()
SEQ = [0]
TOKENS: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def describe_auth(headers) -> str:
    auth = headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            user = base64.b64decode(auth[6:]).decode().split(":", 1)[0]
            return f"Basic (user '{user}')"
        except Exception:
            return "Basic (unreadable)"
    if auth.startswith("Bearer "):
        tok = auth[7:]
        return "Bearer (token issued here)" if tok in TOKENS else "Bearer (unknown token)"
    for h in ("x-api-key", "X-Api-Key", "api-key", "ApiKey"):
        if headers.get(h):
            return f"API key header '{h}'"
    return "none"


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Mock picking system</title>
<style>body{{font:14px system-ui,sans-serif;margin:0;background:#f3f5f8;color:#1a2230}}
header{{background:#111a2b;color:#fff;padding:14px 20px}}main{{padding:16px 20px;max-width:1100px}}
.m{{background:#fff;border:1px solid #e1e5eb;border-radius:8px;margin-bottom:12px}}
.h{{padding:10px 14px;border-bottom:1px solid #e1e5eb;display:flex;gap:14px;flex-wrap:wrap;font-size:13px}}
pre{{margin:0;padding:12px 14px;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;
word-break:break-word;max-height:320px;overflow:auto}}.b{{font-weight:600}}.ok{{color:#1a7f4b}}.bad{{color:#c4321f}}
.muted{{color:#7a8494}}@media (prefers-color-scheme:dark){{body{{background:#0d1320;color:#e4e9f1}}
.m{{background:#151d2c;border-color:#263247}}.h{{border-color:#263247}}}}</style></head><body>
<header><b>Mock picking system</b> &middot; {count} message(s) received &middot; refreshes every 5 s</header>
<main>{body}</main></body></html>"""


def render_page() -> str:
    with LOCK:
        msgs = list(MESSAGES)[::-1]
    if not msgs:
        body = "<p class='muted'>Nothing received yet. Point the outbound SOFTBOT's BaseUrl at this server.</p>"
    else:
        parts = []
        for m in msgs:
            cls = "ok" if 200 <= m["status"] < 300 else "bad"
            parts.append(
                f"<div class='m'><div class='h'><span class='b'>#{m['id']}</span><span>{m['received_at']}</span>"
                f"<span class='b'>{html.escape(m['method'])} {html.escape(m['path'])}</span>"
                f"<span>auth: {html.escape(m['auth'])}</span><span class='{cls}'>replied {m['status']}</span>"
                f"<span class='muted'>{html.escape(m.get('summary') or '')}</span></div>"
                f"<pre>{html.escape(m['body_pretty'])}</pre></div>")
        body = "".join(parts)
    return PAGE.format(count=len(msgs), body=body)


def summarize(obj) -> str:
    """One-line hint of what the message is, for common shapes."""
    if not isinstance(obj, dict):
        return ""
    for k in ("OrderNumber", "orderNumber", "order_number", "OrderId", "orderId", "MessageType", "Event", "event"):
        if k in obj:
            return f"{k}: {obj[k]}"
    return ", ".join(list(obj.keys())[:6])


def make_handler(args):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MockPicking/1.0"

        def _send(self, code: int, obj=None, text: str | None = None, ctype="application/json"):
            data = text.encode() if text is not None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype if text is None or ctype != "application/json" else "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _viewer_ok(self) -> bool:
            if not args.api_key:
                return True
            q = parse_qs(urlparse(self.path).query)
            return args.api_key in (q.get("key", [None])[0], self.headers.get(args.api_key_header))

        def do_GET(self):
            p = urlparse(self.path).path
            if p not in ("/health",) and not self._viewer_ok():
                return self._send(401, text="API key required: open /?key=<your key>", ctype="text/plain")
            if p == "/health":
                return self._send(200, text="ok", ctype="text/plain")
            if p == "/_messages":
                with LOCK:
                    return self._send(200, list(MESSAGES)[::-1])
            if p in ("/", "/index.html"):
                return self._send(200, text=render_page(), ctype="text/html; charset=utf-8")
            return self._send(404, {"error": "not found"})

        def do_DELETE(self):
            if not self._viewer_ok():
                return self._send(401, {"error": "API key required"})
            if urlparse(self.path).path == "/_messages":
                with LOCK:
                    MESSAGES.clear()
                return self._send(200, {"cleared": True})
            return self._send(404, {"error": "not found"})

        def do_PUT(self):
            self.do_POST()

        def do_POST(self):
            url = urlparse(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            if url.path.rstrip("/").endswith("/token") and b"grant_type" in raw:
                return self._token(raw)
            q = parse_qs(url.query)
            status = int(q.get("status", [args.status])[0])
            if args.delay:
                time.sleep(args.delay)
            auth = describe_auth(self.headers)
            if args.api_key and self.headers.get(args.api_key_header) != args.api_key:
                status = 401
            if args.basic and self.headers.get("Authorization") != "Basic " + base64.b64encode(args.basic.encode()).decode():
                status = 401
            try:
                body = json.loads(raw) if raw else None
                pretty = json.dumps(body, indent=2)
            except ValueError:
                body, pretty = None, raw.decode(errors="replace")
            with LOCK:
                SEQ[0] += 1
                mid = SEQ[0]
                MESSAGES.append({"id": mid, "received_at": now(), "method": self.command, "path": self.path,
                                 "auth": auth, "status": status, "summary": summarize(body),
                                 "content_type": self.headers.get("Content-Type"), "body_pretty": pretty})
            print(f"[{now()}] #{mid} {self.command} {self.path} auth={auth} -> {status} {summarize(body)}", flush=True)
            if 200 <= status < 300:
                return self._send(status, {"accepted": True, "id": mid, "received_at": now()})
            return self._send(status, {"accepted": False, "id": mid, "error": f"simulated HTTP {status}"})

        def _token(self, raw: bytes):
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            if form.get("grant_type") != "client_credentials":
                return self._send(400, {"error": "unsupported_grant_type"})
            token = secrets.token_urlsafe(24)
            TOKENS.add(token)
            print(f"[{now()}] issued OAuth2 token (scope={form.get('scope')!r}, auth={describe_auth(self.headers)})",
                  flush=True)
            return self._send(200, {"access_token": token, "token_type": "Bearer", "expires_in": 3600,
                                    "scope": form.get("scope", "")})

        def log_message(self, *a):
            pass

    return Handler


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9100)
    p.add_argument("--status", type=int, default=200, help="status code for every message (default 200)")
    p.add_argument("--delay", type=float, default=0.0, help="seconds to wait before answering")
    p.add_argument("--api-key", default=os.environ.get("MOCK_API_KEY") or None,
                   help="require this API key (otherwise any auth is accepted); env MOCK_API_KEY")
    p.add_argument("--api-key-header", default=os.environ.get("MOCK_API_KEY_HEADER", "x-api-key"))
    p.add_argument("--basic", help="require Basic auth 'user:password'")
    a = p.parse_args()
    print(f"Mock picking system on http://{a.host}:{a.port}/  (messages page at /, Ctrl+C to stop)", flush=True)
    if a.api_key:
        print(f"API key required: header '{a.api_key_header}' on POSTs; open the page as /?key=<key>", flush=True)
    ThreadingHTTPServer((a.host, a.port), make_handler(a)).serve_forever()


if __name__ == "__main__":
    main()
