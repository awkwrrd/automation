"""Integration endpoints (outbound push), message log, API keys and task confirmations."""
import json
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user, require_role
from ..errors import WMSError
from ..models import (ApiKey, AuthType, IntegrationEndpoint, IntegrationEvent, Location, MessageStatus,
                      OutboundMessage, Role, Task, User, utcnow)
from ..schemas import (ApiKeyCreated, ApiKeyIn, ApiKeyOut, ConfirmationResult, ConfirmationsIn, EndpointIn,
                       EndpointOut, MessageDetail, MessageOut, Page)
from ..security import new_api_key
from ..services import dispatcher, integrations
from ..services import tasks as task_svc
from ..services.common import get_or_404
from ._util import like, paginate

router = APIRouter(prefix="/automation", tags=["automation & integrations"])
admin = Depends(require_role(Role.ADMIN))

EVENT_HELP = {
    IntegrationEvent.WAVE_RELEASED: "A wave was released: its orders and pick tasks",
    IntegrationEvent.ORDER_RELEASED: "A single order was released to pick (outside a wave)",
    IntegrationEvent.PUTAWAY_CREATED: "Receiving created a putaway task",
    IntegrationEvent.TASK_CANCELLED: "A task previously sent to this endpoint was cancelled",
    IntegrationEvent.TEST: "Manual test message from the GUI",
}


def _hint(secret: str | None) -> str | None:
    if not secret:
        return None
    return "••••" + secret[-4:] if len(secret) > 8 else "••••"


def _ep_out(db: Session, ep: IntegrationEndpoint) -> EndpointOut:
    counts = dict(db.execute(select(OutboundMessage.status, func.count()).where(OutboundMessage.endpoint_id == ep.id)
                             .group_by(OutboundMessage.status)).all())
    return EndpointOut(
        id=ep.id, name=ep.name, url=ep.url, warehouse_id=ep.warehouse_id, events=ep.event_list,
        zone_ids=ep.zone_id_list, auth_type=ep.auth_type, auth_header=ep.auth_header,
        auth_value_hint=_hint(ep.auth_value), has_signing_secret=bool(ep.signing_secret),
        extra_headers=json.loads(ep.extra_headers) if ep.extra_headers else {},
        timeout_seconds=ep.timeout_seconds, max_attempts=ep.max_attempts, assign_tasks=ep.assign_tasks,
        active=ep.active, created_at=ep.created_at, pending=counts.get(MessageStatus.PENDING, 0),
        failed=counts.get(MessageStatus.FAILED, 0),
        last_sent_at=db.scalar(select(func.max(OutboundMessage.sent_at)).where(OutboundMessage.endpoint_id == ep.id)),
    )


def _apply(ep: IntegrationEndpoint, body: EndpointIn) -> None:
    ep.name, ep.url, ep.warehouse_id = body.name.strip(), body.url.strip(), body.warehouse_id
    ep.events = ",".join(dict.fromkeys(e.value for e in body.events))
    ep.zone_ids = ",".join(str(z) for z in body.zone_ids) or None
    ep.auth_type = body.auth_type
    ep.auth_header = (body.auth_header or "X-API-Key") if body.auth_type == AuthType.HEADER else None
    if body.auth_type == AuthType.NONE:
        ep.auth_value = None
    elif body.auth_value:
        ep.auth_value = body.auth_value
    if body.clear_signing_secret:
        ep.signing_secret = None
    elif body.signing_secret:
        ep.signing_secret = body.signing_secret
    ep.extra_headers = json.dumps(body.extra_headers) if body.extra_headers else None
    ep.timeout_seconds, ep.max_attempts = body.timeout_seconds, body.max_attempts
    ep.assign_tasks, ep.active = body.assign_tasks, body.active


# ------------------------------------------------------------------ endpoints
@router.get("/events", dependencies=[Depends(current_user)])
def events():
    return [{"value": e.value, "description": d} for e, d in EVENT_HELP.items()]


@router.get("/endpoints", response_model=list[EndpointOut], dependencies=[Depends(require_role(Role.SUPERVISOR))])
def list_endpoints(db: Session = Depends(get_db)):
    return [_ep_out(db, e) for e in db.scalars(select(IntegrationEndpoint).order_by(IntegrationEndpoint.name))]


@router.post("/endpoints", response_model=EndpointOut, status_code=201, dependencies=[admin])
def create_endpoint(body: EndpointIn, db: Session = Depends(get_db)):
    ep = IntegrationEndpoint()
    _apply(ep, body)
    try:
        db.add(ep)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"An endpoint named {body.name} already exists")
    return _ep_out(db, ep)


@router.put("/endpoints/{ep_id}", response_model=EndpointOut, dependencies=[admin])
def update_endpoint(ep_id: int, body: EndpointIn, db: Session = Depends(get_db)):
    ep = get_or_404(db, IntegrationEndpoint, ep_id, "Endpoint")
    _apply(ep, body)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"An endpoint named {body.name} already exists")
    return _ep_out(db, ep)


@router.delete("/endpoints/{ep_id}", dependencies=[admin])
def delete_endpoint(ep_id: int, db: Session = Depends(get_db)):
    ep = get_or_404(db, IntegrationEndpoint, ep_id, "Endpoint")
    for m in db.scalars(select(OutboundMessage).where(OutboundMessage.endpoint_id == ep.id)):
        db.delete(m)
    db.delete(ep)
    return {"ok": True}


@router.post("/endpoints/{ep_id}/generate-secret", dependencies=[admin])
def generate_secret(ep_id: int, db: Session = Depends(get_db)):
    """Create a new HMAC signing secret. It is returned once; copy it into the receiving system."""
    ep = get_or_404(db, IntegrationEndpoint, ep_id, "Endpoint")
    ep.signing_secret = "whsec_" + secrets.token_urlsafe(32)
    return {"signing_secret": ep.signing_secret}


@router.post("/endpoints/{ep_id}/test", response_model=MessageDetail, dependencies=[admin])
def test_endpoint(ep_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Send a `test` event right now (bypassing the queue) and return the result."""
    ep = get_or_404(db, IntegrationEndpoint, ep_id, "Endpoint")
    msg = integrations.enqueue(db, ep, IntegrationEvent.TEST, "TEST", ep.warehouse_id,
                               {"message": f"Test from {user.username}", "endpoint": ep.name})
    with httpx.Client() as client:
        if ep.active:
            dispatcher.deliver(db, msg, client)
        else:
            raise WMSError("Endpoint is inactive; activate it before testing")
    if msg.status == MessageStatus.PENDING:  # don't keep retrying a test message
        msg.status = MessageStatus.FAILED
    return _msg_out(msg, detail=True)


# ------------------------------------------------------------------ message log
def _msg_out(m: OutboundMessage, detail: bool = False):
    out = (MessageDetail if detail else MessageOut).model_validate(m)
    out.endpoint_name = m.endpoint.name if m.endpoint else ""
    return out


@router.get("/messages", response_model=Page[MessageOut], dependencies=[Depends(require_role(Role.SUPERVISOR))])
def list_messages(endpoint_id: int | None = None, status: str | None = None, event: str | None = None,
                  q: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    stmt = select(OutboundMessage).options(joinedload(OutboundMessage.endpoint)).order_by(OutboundMessage.id.desc())
    if endpoint_id:
        stmt = stmt.where(OutboundMessage.endpoint_id == endpoint_id)
    if status:
        stmt = stmt.where(OutboundMessage.status == status)
    if event:
        stmt = stmt.where(OutboundMessage.event == event)
    if q:
        stmt = stmt.where(or_(OutboundMessage.reference.ilike(like(q)), OutboundMessage.last_error.ilike(like(q))))
    rows, total = paginate(db, stmt, limit, offset)
    return Page(items=[_msg_out(r[0]) for r in rows], total=total)


@router.get("/messages/{msg_id}", response_model=MessageDetail, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def get_message(msg_id: int, db: Session = Depends(get_db)):
    return _msg_out(get_or_404(db, OutboundMessage, msg_id, "Message"), detail=True)


@router.post("/messages/{msg_id}/retry", response_model=MessageDetail, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def retry_message(msg_id: int, db: Session = Depends(get_db)):
    """Re-queue a FAILED / CANCELLED (or re-send a SENT) message. Same delivery id, so receivers can de-dupe."""
    m = get_or_404(db, OutboundMessage, msg_id, "Message")
    m.status, m.attempts, m.next_attempt_at, m.last_error = MessageStatus.PENDING, 0, utcnow(), None
    return _msg_out(m, detail=True)


@router.post("/messages/{msg_id}/cancel", response_model=MessageDetail, dependencies=[Depends(require_role(Role.SUPERVISOR))])
def cancel_message(msg_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, OutboundMessage, msg_id, "Message")
    if m.status != MessageStatus.PENDING:
        raise WMSError(f"Message is {m.status}")
    m.status = MessageStatus.CANCELLED
    return _msg_out(m, detail=True)


# ------------------------------------------------------------------ API keys
def _key_out(k: ApiKey, model=ApiKeyOut, **extra):
    return model.model_validate({**{c: getattr(k, c) for c in ("id", "name", "user_id", "prefix", "active",
                                                                 "created_at", "last_used_at")},
                                 "username": k.user.username, **extra})


@router.get("/api-keys", response_model=list[ApiKeyOut], dependencies=[admin])
def list_keys(db: Session = Depends(get_db)):
    return [_key_out(k) for k in db.scalars(select(ApiKey).options(joinedload(ApiKey.user)).order_by(ApiKey.id.desc()))]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201, dependencies=[admin])
def create_key(body: ApiKeyIn, db: Session = Depends(get_db)):
    """Create an API key acting as the given user (its role decides what the key may do).
    The plaintext key is returned once only."""
    user = get_or_404(db, User, body.user_id, "User")
    key, prefix, digest = new_api_key()
    rec = ApiKey(name=body.name, user_id=user.id, prefix=prefix, key_hash=digest)
    db.add(rec)
    db.flush()
    return _key_out(rec, ApiKeyCreated, key=key)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyOut, dependencies=[admin])
def revoke_key(key_id: int, db: Session = Depends(get_db)):
    rec = get_or_404(db, ApiKey, key_id, "API key")
    rec.active = False
    return _key_out(rec)


# ------------------------------------------------------------------ inbound: task confirmations
@router.post("/confirmations", response_model=list[ConfirmationResult])
def confirm_tasks(body: ConfirmationsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Bulk-confirm tasks done by automation (picks, putaways, moves).
    Each confirmation is applied independently; one failure does not undo the others.
    Re-sending an already-completed task returns ok=false with its status (safe to retry)."""
    results = []
    for c in body.confirmations:
        sp = db.begin_nested()
        try:
            task = db.get(Task, c.task_id)
            if task is None:
                raise WMSError("Task not found")
            dest_id = c.to_location_id
            if c.to_location_code:
                loc = db.scalar(select(Location).where(Location.warehouse_id == task.warehouse_id,
                                                       func.upper(Location.code) == c.to_location_code.strip().upper()))
                if loc is None:
                    raise WMSError(f"Location {c.to_location_code} not found")
                dest_id = loc.id
            task_svc.complete(db, task, c.qty, user.username, dest_id)
            db.flush()
            sp.commit()
            results.append(ConfirmationResult(task_id=c.task_id, ok=True, status=task.status, qty_done=task.qty_done))
        except WMSError as e:
            sp.rollback()
            t = db.get(Task, c.task_id)
            results.append(ConfirmationResult(task_id=c.task_id, ok=False, error=e.message,
                                              status=t.status if t else None, qty_done=t.qty_done if t else None))
    return results
