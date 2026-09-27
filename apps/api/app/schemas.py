from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    pass


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class Confirmation(BaseModel):
    version: int = Field(ge=1)


class Decision(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class HumanReply(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TicketUpdate(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "closed"]] = None
    assignee_id: Optional[str] = None
    priority: Optional[Literal["low", "normal", "high", "urgent"]] = None


class TurnResponse(BaseModel):
    id: str
    status: str
    result: Optional[dict[str, Any]] = None
    completed_at: Optional[datetime] = None
