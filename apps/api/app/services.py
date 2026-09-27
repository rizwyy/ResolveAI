from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .models import (ActionRequest, AuditEvent, Conversation, CustomerProfile, Message, Order,
                     OutboxEvent, PolicyDocument, Refund, Ticket, Turn, now)


def canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit(db: Session, principal: Optional[Principal], org_id: str, action: str, resource_type: str,
          resource_id: str, result: str = "success", metadata: Optional[dict[str, Any]] = None) -> None:
    db.add(AuditEvent(organization_id=org_id, actor_id=principal.user_id if principal else None,
                      action=action, resource_type=resource_type, resource_id=resource_id,
                      result=result, metadata_json=metadata or {}))


def order_for_principal(db: Session, principal: Principal, reference: str) -> Order:
    order = db.scalar(select(Order).where(Order.organization_id == principal.organization_id, Order.reference == reference))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if principal.role == "customer" and order.customer_id != principal.customer_id:
        audit(db, principal, principal.organization_id, "order.read", "order", order.id, "denied")
        db.commit()
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def order_summary(order: Order) -> dict[str, Any]:
    return {"reference": order.reference, "status": order.status, "tracking_code": order.tracking_code,
            "amount_minor": order.amount_minor, "currency": order.currency, "refunded_minor": order.refunded_minor}


def create_action(db: Session, principal: Principal, conversation: Conversation, action_type: str,
                  payload: dict[str, Any]) -> ActionRequest:
    action = ActionRequest(organization_id=principal.organization_id, customer_id=conversation.customer_id,
        conversation_id=conversation.id, action_type=action_type, status="awaiting_customer_confirmation",
        payload=payload, payload_hash=canonical_hash(payload), requester_id=principal.user_id,
        expires_at=now() + timedelta(hours=24))
    db.add(action)
    db.flush()
    audit(db, principal, principal.organization_id, "action.proposed", "action_request", action.id,
          metadata={"type": action_type})
    return action


def eligible_refund(order: Order) -> tuple[bool, str]:
    if order.status != "delivered" or order.delivered_at is None:
        return False, "The order has not been delivered."
    if order.delivered_at < now() - timedelta(days=30):
        return False, "The 30-day demo refund window has passed."
    if order.refunded_minor >= order.amount_minor:
        return False, "This order has already been fully refunded."
    return True, "Eligible under demo policy v1."


def execute_sandbox_refund(db: Session, action: ActionRequest) -> Refund:
    """One transaction protects this simulated provider; a real provider needs reconciliation."""
    existing = db.scalar(select(Refund).where(Refund.action_request_id == action.id))
    if existing:
        return existing
    order = db.scalar(select(Order).where(Order.id == action.payload["order_id"]).with_for_update())
    if not order:
        raise HTTPException(status_code=409, detail="Order changed; create a new request")
    eligible, reason = eligible_refund(order)
    if not eligible:
        action.status = "failed"
        raise HTTPException(status_code=409, detail=reason)
    amount = int(action.payload["amount_minor"])
    if amount <= 0 or order.refunded_minor + amount > order.amount_minor:
        action.status = "failed"
        raise HTTPException(status_code=409, detail="Refund limit changed; create a new request")
    action.status = "executing"
    refund = Refund(organization_id=action.organization_id, order_id=order.id, action_request_id=action.id,
                    amount_minor=amount, currency=order.currency, idempotency_key=f"sandbox:{action.id}")
    order.refunded_minor += amount
    action.status = "succeeded"
    db.add(refund)
    audit(db, None, action.organization_id, "refund.sandbox_executed", "action_request", action.id,
          metadata={"amount_minor": amount})
    return refund


def handle_mock_turn(db: Session, turn: Turn) -> dict[str, Any]:
    message = db.get(Message, turn.message_id)
    conversation = db.get(Conversation, turn.conversation_id)
    if not message or not conversation:
        return {"kind": "error", "text": "This request could not be recovered."}
    if conversation.status == "human_owned":
        return {"kind": "handoff", "text": "A support specialist owns this conversation, so AI replies are paused."}
    user = db.get(CustomerProfile, conversation.customer_id)
    if not user:
        return {"kind": "error", "text": "Customer context was unavailable."}
    principal = Principal(user_id=user.user_id, email="queued-customer", organization_id=conversation.organization_id,
                          role="customer", customer_id=user.id)
    body = message.body.strip()
    lowered = body.lower()
    ref_match = re.search(r"\b(?:NS|HH)-\d{4}\b", body, re.I)
    reference = ref_match.group(0).upper() if ref_match else None
    if any(term in lowered for term in ("human", "agent", "person", "representative")):
        conversation.status = "human_owned"
        ticket = Ticket(organization_id=conversation.organization_id, customer_id=conversation.customer_id,
                        conversation_id=conversation.id, subject="Human handoff", description=body,
                        category="handoff", priority="normal")
        db.add(ticket); db.flush()
        audit(db, principal, conversation.organization_id, "conversation.handoff", "conversation", conversation.id)
        return {"kind": "handoff", "ticket_id": ticket.id, "text": "I’ve placed you in the support queue. A human now owns this conversation."}
    if "ticket" in lowered or "complaint" in lowered or "issue" in lowered:
        action = create_action(db, principal, conversation, "ticket_create", {
            "subject": body[:120], "description": body, "category": "general", "priority": "normal"})
        return {"kind": "confirmation", "action_id": action.id, "version": action.version,
                "text": "I can create a support ticket with your message. Please confirm the exact request below."}
    if "refund" in lowered or "return" in lowered:
        if not reference:
            return {"kind": "clarification", "text": "Please share the order reference (for example, NS-1042) so I can check eligibility."}
        try:
            order = order_for_principal(db, principal, reference)
        except HTTPException:
            return {"kind": "not_found", "text": "I can’t find an accessible order with that reference."}
        eligible, reason = eligible_refund(order)
        if not eligible:
            return {"kind": "policy", "text": f"A refund review cannot be proposed: {reason}"}
        action = create_action(db, principal, conversation, "refund_review", {
            "order_id": order.id, "order_reference": order.reference, "amount_minor": order.amount_minor - order.refunded_minor,
            "currency": order.currency, "policy_version": 1, "reason": body})
        return {"kind": "confirmation", "action_id": action.id, "version": action.version,
                "text": f"Order {order.reference} is eligible for a ${action.payload['amount_minor']/100:.2f} sandbox refund review. Confirm to send it to a supervisor."}
    if "policy" in lowered:
        policy = db.scalar(select(PolicyDocument).where(PolicyDocument.organization_id == conversation.organization_id,
                                                          PolicyDocument.published.is_(True)))
        return {"kind": "policy", "policy_id": policy.id if policy else None,
                "text": policy.body if policy else "No published demo policy is available."}
    if reference or "order" in lowered or "track" in lowered or "shipping" in lowered:
        if not reference:
            return {"kind": "clarification", "text": "Please share the order reference (for example, NS-1042) so I can look it up."}
        try:
            order = order_for_principal(db, principal, reference)
        except HTTPException:
            return {"kind": "not_found", "text": "I can’t find an accessible order with that reference."}
        audit(db, principal, conversation.organization_id, "order.read", "order", order.id)
        tracking = f" Tracking: {order.tracking_code}." if order.tracking_code else ""
        return {"kind": "order", "order": order_summary(order),
                "text": f"Order {order.reference} is {order.status.replace('_', ' ')}.{tracking}"}
    return {"kind": "clarification", "text": "I can check an order, explain a policy, open a ticket, start a refund review, or connect you with a human. What would you like to do?"}


def process_turn(db: Session, turn: Turn) -> Turn:
    if turn.status not in {"queued", "processing"}:
        return turn
    turn.status = "processing"; turn.attempts += 1; db.commit()
    try:
        result = handle_mock_turn(db, turn)
        db.add(Message(conversation_id=turn.conversation_id, role="assistant", body=result["text"], metadata_json=result))
        turn.status = "completed"; turn.result = result; turn.completed_at = now()
        outbox = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == turn.id))
        if outbox: outbox.status = "sent"; outbox.sent_at = now()
        db.commit()
    except Exception:
        db.rollback(); turn = db.get(Turn, turn.id)
        turn.status = "failed"; turn.error_code = "worker_failed"; db.commit()
    return turn
