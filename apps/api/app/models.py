from __future__ import annotations

import uuid
from datetime import datetime

from typing import Any, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    # Store UTC consistently. SQLite (used in deterministic tests) returns naive timestamps;
    # PostgreSQL deployment uses the same UTC convention through its configured connection.
    return datetime.utcnow()


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("organization_id", "reference"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    reference: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32))
    tracking_code: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_minor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="ai_active")
    assigned_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (UniqueConstraint("conversation_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    __table_args__ = (UniqueConstraint("organization_id", "slug", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(180))
    version: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(48))
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    status: Mapped[str] = mapped_column(String(24), default="open")
    assignee_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ActionRequest(Base):
    __tablename__ = "action_requests"
    __table_args__ = (Index("ix_actions_org_status", "organization_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (UniqueConstraint("action_request_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    action_request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(24), default="succeeded")
    provider: Mapped[str] = mapped_column(String(24), default="sandbox")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(36))
    result: Mapped[str] = mapped_column(String(24))
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
