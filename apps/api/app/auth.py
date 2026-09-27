from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import CustomerProfile, Membership, User


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    organization_id: str
    role: str
    customer_id: Optional[str]

    @property
    def is_staff(self) -> bool:
        return self.role in {"support_agent", "supervisor", "administrator"}


def current_principal(
    x_demo_identity: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> Principal:
    settings = get_settings()
    if settings.auth_provider != "local":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Cognito validation required")
    if not x_demo_identity:
        raise HTTPException(status_code=401, detail="Choose a local demo identity")
    user = db.scalar(select(User).where(User.email == x_demo_identity))
    if not user:
        raise HTTPException(status_code=401, detail="Unknown local demo identity")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    if not membership:
        raise HTTPException(status_code=403, detail="No organization membership")
    customer = db.scalar(
        select(CustomerProfile).where(
            CustomerProfile.user_id == user.id,
            CustomerProfile.organization_id == membership.organization_id,
        )
    )
    return Principal(user.id, user.email, membership.organization_id, membership.role, customer.id if customer else None)


def require_staff(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.is_staff:
        raise HTTPException(status_code=403, detail="Staff permission required")
    return principal


def require_supervisor(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.role not in {"supervisor", "administrator"}:
        raise HTTPException(status_code=403, detail="Supervisor permission required")
    return principal
