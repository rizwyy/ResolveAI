from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CustomerProfile, Membership, Order, Organization, PolicyDocument, Ticket, User, now


def seed_database(db: Session) -> None:
    """Deterministic, additive demo data. It never deletes existing records."""
    if db.scalar(select(Organization).where(Organization.name == "Northstar Outfitters")):
        return
    north = Organization(name="Northstar Outfitters")
    harbor = Organization(name="Harbor Home")
    db.add_all([north, harbor])
    db.flush()

    people = [
        ("ava.customer@northstar.test", "Ava Customer", north, "customer"),
        ("liam.customer@northstar.test", "Liam Customer", north, "customer"),
        ("maya.agent@northstar.test", "Maya Agent", north, "support_agent"),
        ("sam.supervisor@northstar.test", "Sam Supervisor", north, "supervisor"),
        ("noah.customer@harbor.test", "Noah Customer", harbor, "customer"),
        ("zoe.customer@harbor.test", "Zoe Customer", harbor, "customer"),
        ("riley.agent@harbor.test", "Riley Agent", harbor, "support_agent"),
        ("taylor.supervisor@harbor.test", "Taylor Supervisor", harbor, "supervisor"),
    ]
    profiles = {}
    for email, name, org, role in people:
        user = User(email=email, name=name)
        db.add(user)
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role=role))
        if role == "customer":
            profile = CustomerProfile(organization_id=org.id, user_id=user.id)
            db.add(profile)
            db.flush()
            profiles[email] = profile

    delivered = now() - timedelta(days=8)
    db.add_all([
        Order(organization_id=north.id, customer_id=profiles["ava.customer@northstar.test"].id,
              reference="NS-1042", status="delivered", tracking_code="TRACK-NS-1042", amount_minor=8900,
              currency="USD", delivered_at=delivered),
        Order(organization_id=north.id, customer_id=profiles["liam.customer@northstar.test"].id,
              reference="NS-1043", status="in_transit", tracking_code="TRACK-NS-1043", amount_minor=4600,
              currency="USD"),
        Order(organization_id=harbor.id, customer_id=profiles["noah.customer@harbor.test"].id,
              reference="HH-2042", status="delivered", tracking_code="TRACK-HH-2042", amount_minor=12900,
              currency="USD", delivered_at=delivered),
        Order(organization_id=harbor.id, customer_id=profiles["zoe.customer@harbor.test"].id,
              reference="HH-2043", status="processing", tracking_code=None, amount_minor=3800, currency="USD"),
    ])
    for org in (north, harbor):
        db.add(PolicyDocument(organization_id=org.id, slug="refunds", title="Demo refund policy", version=1,
            body="Demo policy: full refunds are available for paid, delivered orders within 30 days. Duplicate refunds are not allowed. Every refund requires supervisor approval.", published=True))
        db.add(PolicyDocument(organization_id=org.id, slug="shipping", title="Demo shipping policy", version=1,
            body="Demo policy: tracking information is shown only to the customer who owns the order or authorized staff in the same organization.", published=True))
    db.add(Ticket(organization_id=north.id, customer_id=profiles["liam.customer@northstar.test"].id,
                  subject="Sample delayed delivery", description="Synthetic seed ticket", category="delivery", priority="normal"))
    db.commit()
