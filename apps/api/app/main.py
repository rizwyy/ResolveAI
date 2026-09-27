from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal, current_principal, require_staff, require_supervisor
from .config import get_settings
from .db import Base, engine, get_db
from .models import (ActionRequest, AuditEvent, Conversation, Message, Order, OutboxEvent,
                     PolicyDocument, Ticket, Turn, now)
from .schemas import Confirmation, ConversationCreate, Decision, HumanReply, MessageCreate, TicketUpdate
from .seed import seed_database
from .services import (audit, canonical_hash, execute_sandbox_refund, order_for_principal, order_summary,
                       process_turn)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().validate_mode()
    Base.metadata.create_all(bind=engine)  # Alembic owns cloud migrations; local demo bootstrap only.
    with next(get_db()) as db:
        seed_database(db)
    yield


app = FastAPI(title="ResolveAI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origin_list,
                   allow_credentials=False, allow_methods=["GET", "POST", "PATCH"],
                   allow_headers=["Content-Type", "Idempotency-Key", "X-Demo-Identity"])


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


def require_conversation(db: Session, principal: Principal, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if principal.role == "customer" and conversation.customer_id != principal.customer_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def serialize_conversation(db: Session, conversation: Conversation) -> dict[str, Any]:
    messages = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
    actions = list(db.scalars(select(ActionRequest).where(ActionRequest.conversation_id == conversation.id)
                              .where(ActionRequest.status.in_(["awaiting_customer_confirmation", "awaiting_supervisor_approval"]))))
    return {"id": conversation.id, "status": conversation.status, "assigned_user_id": conversation.assigned_user_id,
            "version": conversation.version, "messages": [{"id": m.id, "role": m.role, "body": m.body,
            "metadata": m.metadata_json, "created_at": m.created_at} for m in messages],
            "pending_actions": [{"id": a.id, "type": a.action_type, "status": a.status, "payload": a.payload,
                                  "version": a.version, "expires_at": a.expires_at} for a in actions]}


@app.get("/healthz")
def health() -> dict[str, str]: return {"status": "ok"}


@app.get("/readyz")
def readiness(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(select(1)); return {"status": "ready"}


@app.get("/api/v1/me")
def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {"email": principal.email, "user_id": principal.user_id, "organization_id": principal.organization_id,
            "role": principal.role, "customer_id": principal.customer_id, "local_demo": get_settings().auth_provider == "local"}


@app.get("/api/v1/demo-identities")
def demo_identities(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    if get_settings().auth_provider != "local": raise HTTPException(status_code=404, detail="Not available")
    rows = db.execute(select(Order))  # keeps route tied to seeded DB without returning credentials
    del rows
    from .models import Membership, User
    return [{"email": user.email, "name": user.name, "role": membership.role}
            for user, membership in db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id))]


@app.post("/api/v1/conversations", status_code=201)
def create_conversation(_input: ConversationCreate, principal: Principal = Depends(current_principal),
                        db: Session = Depends(get_db)) -> dict[str, str]:
    if not principal.customer_id: raise HTTPException(status_code=403, detail="Customers create conversations")
    conversation = Conversation(organization_id=principal.organization_id, customer_id=principal.customer_id)
    db.add(conversation); db.flush(); audit(db, principal, principal.organization_id, "conversation.created", "conversation", conversation.id); db.commit()
    return {"id": conversation.id}


@app.get("/api/v1/conversations")
def list_conversations(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(Conversation).where(Conversation.organization_id == principal.organization_id).order_by(Conversation.updated_at.desc())
    if principal.role == "customer": query = query.where(Conversation.customer_id == principal.customer_id)
    rows = list(db.scalars(query.limit(100)))
    return [{"id": row.id, "status": row.status, "created_at": row.created_at, "assigned_user_id": row.assigned_user_id} for row in rows]


@app.get("/api/v1/conversations/{conversation_id}")
def get_conversation(conversation_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    return serialize_conversation(db, require_conversation(db, principal, conversation_id))


@app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
def submit_message(conversation_id: str, payload: MessageCreate, idempotency_key: str = Header(..., alias="Idempotency-Key"),
                   principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict[str, str]:
    conversation = require_conversation(db, principal, conversation_id)
    if principal.role != "customer": raise HTTPException(status_code=403, detail="Use human reply for staff messages")
    if conversation.status == "human_owned": raise HTTPException(status_code=409, detail="A human owns this conversation")
    payload_hash = hashlib.sha256(payload.body.encode()).hexdigest()
    existing = db.scalar(select(Turn).where(Turn.conversation_id == conversation.id, Turn.idempotency_key == idempotency_key))
    if existing:
        if existing.payload_hash != payload_hash: raise HTTPException(status_code=409, detail="Idempotency key payload conflict")
        return {"turn_id": existing.id, "status": existing.status}
    message = Message(conversation_id=conversation.id, actor_id=principal.user_id, role="user", body=payload.body)
    db.add(message); db.flush()
    turn = Turn(organization_id=principal.organization_id, conversation_id=conversation.id, message_id=message.id,
                idempotency_key=idempotency_key, payload_hash=payload_hash)
    db.add(turn); db.flush(); db.add(OutboxEvent(organization_id=principal.organization_id, event_type="turn.queued", aggregate_id=turn.id))
    conversation.version += 1; db.commit()
    return {"turn_id": turn.id, "status": "queued"}


@app.get("/api/v1/turns/{turn_id}")
def get_turn(turn_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    turn = db.get(Turn, turn_id)
    if not turn or turn.organization_id != principal.organization_id: raise HTTPException(status_code=404, detail="Turn not found")
    return {"id": turn.id, "status": turn.status, "result": turn.result, "completed_at": turn.completed_at}


@app.post("/api/v1/internal/worker/run")
def run_worker_for_demo(principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, int]:
    turns = list(db.scalars(select(Turn).where(Turn.status == "queued").limit(20)))
    for turn in turns: process_turn(db, turn)
    return {"processed": len(turns)}


@app.get("/api/v1/orders/{reference}")
def get_order(reference: str, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    order = order_for_principal(db, principal, reference.upper()); audit(db, principal, principal.organization_id, "order.read", "order", order.id); db.commit()
    return order_summary(order)


@app.get("/api/v1/policies")
def list_policies(principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    policies = db.scalars(select(PolicyDocument).where(PolicyDocument.organization_id == principal.organization_id, PolicyDocument.published.is_(True)))
    return [{"id": p.id, "title": p.title, "version": p.version, "body": p.body} for p in policies]


@app.post("/api/v1/actions/{action_id}/confirm")
def confirm_action(action_id: str, payload: Confirmation, principal: Principal = Depends(current_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    action = db.get(ActionRequest, action_id)
    if not action or action.organization_id != principal.organization_id or action.customer_id != principal.customer_id:
        raise HTTPException(status_code=404, detail="Action request not found")
    if action.status != "awaiting_customer_confirmation": raise HTTPException(status_code=409, detail="Action cannot be confirmed")
    if action.version != payload.version or action.expires_at <= now():
        action.status = "expired"; db.commit(); raise HTTPException(status_code=409, detail="Proposal is stale; create a new request")
    if canonical_hash(action.payload) != action.payload_hash: raise HTTPException(status_code=409, detail="Proposal integrity check failed")
    action.confirmed_at = now()
    if action.action_type == "ticket_create":
        ticket = Ticket(organization_id=action.organization_id, customer_id=action.customer_id, conversation_id=action.conversation_id,
            subject=action.payload["subject"], description=action.payload["description"], category=action.payload["category"], priority=action.payload["priority"])
        db.add(ticket); db.flush(); action.status = "succeeded"; result = {"status": action.status, "ticket_id": ticket.id}
    elif action.action_type == "refund_review":
        action.status = "awaiting_supervisor_approval"; result = {"status": action.status}
    else: raise HTTPException(status_code=409, detail="Unknown action type")
    audit(db, principal, principal.organization_id, "action.confirmed", "action_request", action.id); db.commit(); return result


@app.get("/api/v1/approvals")
def approvals(principal: Principal = Depends(require_supervisor), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(ActionRequest).where(ActionRequest.organization_id == principal.organization_id,
                     ActionRequest.status == "awaiting_supervisor_approval"))
    return [{"id": a.id, "type": a.action_type, "payload": a.payload, "expires_at": a.expires_at, "requester_id": a.requester_id} for a in rows]


@app.post("/api/v1/approvals/{action_id}/approve")
def approve(action_id: str, payload: Decision, principal: Principal = Depends(require_supervisor), db: Session = Depends(get_db)) -> dict[str, Any]:
    action = db.scalar(select(ActionRequest).where(ActionRequest.id == action_id).with_for_update())
    if not action or action.organization_id != principal.organization_id: raise HTTPException(status_code=404, detail="Approval not found")
    if action.requester_id == principal.user_id: raise HTTPException(status_code=403, detail="You cannot approve your own request")
    if action.status != "awaiting_supervisor_approval" or action.expires_at <= now(): raise HTTPException(status_code=409, detail="Approval is no longer pending")
    action.status = "approved"; action.approved_by_id = principal.user_id; action.decision_reason = payload.reason
    refund = execute_sandbox_refund(db, action); audit(db, principal, principal.organization_id, "action.approved", "action_request", action.id)
    db.commit(); return {"status": action.status, "refund_id": refund.id, "provider": "sandbox"}


@app.post("/api/v1/approvals/{action_id}/reject")
def reject(action_id: str, payload: Decision, principal: Principal = Depends(require_supervisor), db: Session = Depends(get_db)) -> dict[str, str]:
    action = db.scalar(select(ActionRequest).where(ActionRequest.id == action_id).with_for_update())
    if not action or action.organization_id != principal.organization_id: raise HTTPException(status_code=404, detail="Approval not found")
    if action.status != "awaiting_supervisor_approval": raise HTTPException(status_code=409, detail="Approval is no longer pending")
    action.status = "rejected"; action.approved_by_id = principal.user_id; action.decision_reason = payload.reason
    audit(db, principal, principal.organization_id, "action.rejected", "action_request", action.id); db.commit(); return {"status": action.status}


@app.get("/api/v1/tickets")
def list_tickets(principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.scalars(select(Ticket).where(Ticket.organization_id == principal.organization_id).order_by(Ticket.created_at.desc()))
    return [{"id": t.id, "subject": t.subject, "status": t.status, "priority": t.priority, "assignee_id": t.assignee_id, "created_at": t.created_at} for t in rows]


@app.patch("/api/v1/tickets/{ticket_id}")
def update_ticket(ticket_id: str, payload: TicketUpdate, principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, Any]:
    ticket = db.get(Ticket, ticket_id)
    if not ticket or ticket.organization_id != principal.organization_id: raise HTTPException(status_code=404, detail="Ticket not found")
    for field, value in payload.model_dump(exclude_none=True).items(): setattr(ticket, field, value)
    audit(db, principal, principal.organization_id, "ticket.updated", "ticket", ticket.id); db.commit()
    return {"id": ticket.id, "status": ticket.status, "priority": ticket.priority}


@app.post("/api/v1/conversations/{conversation_id}/take")
def take_conversation(conversation_id: str, principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, str]:
    conversation = require_conversation(db, principal, conversation_id); conversation.status = "human_owned"; conversation.assigned_user_id = principal.user_id; conversation.version += 1
    audit(db, principal, principal.organization_id, "conversation.taken", "conversation", conversation.id); db.commit(); return {"status": conversation.status}


@app.post("/api/v1/conversations/{conversation_id}/reply")
def human_reply(conversation_id: str, payload: HumanReply, principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, str]:
    conversation = require_conversation(db, principal, conversation_id)
    if conversation.status != "human_owned": raise HTTPException(status_code=409, detail="Take ownership before replying")
    db.add(Message(conversation_id=conversation.id, actor_id=principal.user_id, role="human", body=payload.body)); db.commit(); return {"status": "sent"}


@app.post("/api/v1/conversations/{conversation_id}/release")
def release_conversation(conversation_id: str, principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, str]:
    conversation = require_conversation(db, principal, conversation_id); conversation.status = "ai_active"; conversation.assigned_user_id = None; conversation.version += 1
    audit(db, principal, principal.organization_id, "conversation.released", "conversation", conversation.id); db.commit(); return {"status": conversation.status}


@app.get("/api/v1/metrics")
def metrics(principal: Principal = Depends(require_staff), db: Session = Depends(get_db)) -> dict[str, Any]:
    org = principal.organization_id
    return {"conversations": db.scalar(select(func.count()).select_from(Conversation).where(Conversation.organization_id == org)),
            "tickets_open": db.scalar(select(func.count()).select_from(Ticket).where(Ticket.organization_id == org, Ticket.status.in_(["open", "in_progress"]))),
            "pending_approvals": db.scalar(select(func.count()).select_from(ActionRequest).where(ActionRequest.organization_id == org, ActionRequest.status == "awaiting_supervisor_approval")),
            "failed_turns": db.scalar(select(func.count()).select_from(Turn).where(Turn.organization_id == org, Turn.status == "failed")),
            "telemetry": "local demo; no CloudWatch metrics"}


@app.get("/api/v1/audit")
def audit_events(principal: Principal = Depends(require_supervisor), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    events = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == principal.organization_id).order_by(AuditEvent.created_at.desc()).limit(100))
    return [{"action": e.action, "resource_type": e.resource_type, "result": e.result, "created_at": e.created_at, "metadata": e.metadata_json} for e in events]
