"""Delivers outbound integration messages over HTTPS.

- Ordered: per endpoint, messages go strictly oldest-first; a retrying message holds back
  later ones (so a robot never sees `task.cancelled` before the `wave.released` it refers to).
- Retries with exponential backoff (10s, 20s, 40s ... capped at 15 min) up to the endpoint's
  max_attempts, then FAILED (visible in the message log, can be re-sent).
- 4xx responses other than 408/429 are treated as permanent and fail immediately.
- Each request carries X-WMS-Event, X-WMS-Delivery (message id; use it to de-duplicate),
  X-WMS-Timestamp and, if a signing secret is set, X-WMS-Signature:
      sha256=HMAC_SHA256(secret, "<timestamp>.<raw body>")
Run a single app process (one uvicorn worker) so only one dispatcher is active.
"""
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import timedelta

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import AuthType, IntegrationEndpoint, MessageStatus, OutboundMessage, utcnow

log = logging.getLogger("wms.dispatcher")
MAX_BACKOFF = timedelta(minutes=15)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def build_headers(ep: IntegrationEndpoint, msg: OutboundMessage, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"{settings.app_name.replace(' ', '')}/1.0",
        "X-WMS-Event": msg.event,
        "X-WMS-Delivery": str(msg.id),
        "X-WMS-Timestamp": ts,
    }
    if ep.signing_secret:
        headers["X-WMS-Signature"] = sign(ep.signing_secret, ts, body)
    if ep.auth_type == AuthType.BEARER and ep.auth_value:
        headers["Authorization"] = f"Bearer {ep.auth_value}"
    elif ep.auth_type == AuthType.BASIC and ep.auth_value:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(ep.auth_value.encode()).decode()
    elif ep.auth_type == AuthType.HEADER and ep.auth_value:
        headers[ep.auth_header or "X-API-Key"] = ep.auth_value
    if ep.extra_headers:
        try:
            headers.update({str(k): str(v) for k, v in json.loads(ep.extra_headers).items()})
        except (ValueError, AttributeError):
            log.warning("endpoint %s has invalid extra_headers JSON", ep.name)
    return headers


def deliver(db: Session, msg: OutboundMessage, client: httpx.Client) -> bool:
    ep = db.get(IntegrationEndpoint, msg.endpoint_id)
    now = utcnow()
    if ep is None or not ep.active:
        msg.next_attempt_at = now + timedelta(seconds=30)  # hold until the endpoint is re-enabled
        msg.last_error = "Endpoint is inactive; message held"
        return False
    body = msg.payload.encode()
    msg.attempts += 1
    msg.last_attempt_at = now
    permanent = False
    try:
        r = client.post(ep.url, content=body, headers=build_headers(ep, msg, body), timeout=ep.timeout_seconds)
        msg.response_code = r.status_code
        msg.response_body = r.text[:2000]
        if 200 <= r.status_code < 300:
            msg.status = MessageStatus.SENT
            msg.sent_at = utcnow()
            msg.last_error = None
            return True
        msg.last_error = f"HTTP {r.status_code}"
        permanent = 400 <= r.status_code < 500 and r.status_code not in (408, 429)
    except httpx.HTTPError as e:
        msg.response_code = None
        msg.last_error = f"{type(e).__name__}: {e}"[:1000]
    if permanent or msg.attempts >= ep.max_attempts:
        msg.status = MessageStatus.FAILED
    else:
        msg.next_attempt_at = now + min(timedelta(seconds=10 * 2 ** (msg.attempts - 1)), MAX_BACKOFF)
    return False


def dispatch_once(client: httpx.Client, session_factory=SessionLocal) -> int:
    """Attempt the oldest due message of every endpoint. Returns how many were attempted."""
    with session_factory() as db:
        head = (select(OutboundMessage.endpoint_id, func.min(OutboundMessage.id).label("mid"))
                .where(OutboundMessage.status == MessageStatus.PENDING)
                .group_by(OutboundMessage.endpoint_id).subquery())
        due = db.scalars(
            select(OutboundMessage).join(head, OutboundMessage.id == head.c.mid)
            .where(or_(OutboundMessage.next_attempt_at.is_(None), OutboundMessage.next_attempt_at <= utcnow()))
        ).all()
        attempted = 0
        for msg in due:
            ep = db.get(IntegrationEndpoint, msg.endpoint_id)
            if ep is not None and not ep.active:
                continue  # leave it parked, don't busy-loop
            deliver(db, msg, client)
            db.commit()
            attempted += 1
        return attempted


class Dispatcher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="wms-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        with httpx.Client(follow_redirects=False) as client:
            while not self._stop.is_set():
                try:
                    while dispatch_once(client) and not self._stop.is_set():
                        pass
                except Exception:  # never let the thread die
                    log.exception("dispatcher error")
                self._stop.wait(settings.dispatch_interval)


dispatcher = Dispatcher()
