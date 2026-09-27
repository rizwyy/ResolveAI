from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def headers(email: str, **extra):
    return {"X-Demo-Identity": email, **extra}


def setup_module():
    Base.metadata.drop_all(bind=engine)


def test_customer_order_isolation_and_ticket_confirmation():
    with TestClient(app) as client:
        ava = headers("ava.customer@northstar.test")
        assert client.get("/api/v1/orders/NS-1042", headers=ava).status_code == 200
        assert client.get("/api/v1/orders/NS-1043", headers=ava).status_code == 404
        conversation = client.post("/api/v1/conversations", headers=ava, json={}).json()["id"]
        sent = client.post(f"/api/v1/conversations/{conversation}/messages", headers=headers(
            "ava.customer@northstar.test", **{"Idempotency-Key": "ticket-key"}), json={"body": "I need a ticket for my broken item"})
        assert sent.status_code == 202
        assert client.post("/api/v1/internal/worker/run", headers=headers("maya.agent@northstar.test")).json()["processed"] == 1
        detail = client.get(f"/api/v1/conversations/{conversation}", headers=ava).json()
        action = detail["pending_actions"][0]
        assert client.post(f"/api/v1/actions/{action['id']}/confirm", headers=ava, json={"version": 1}).status_code == 200
        tickets = client.get("/api/v1/tickets", headers=headers("maya.agent@northstar.test")).json()
        assert any(ticket["subject"].startswith("I need") for ticket in tickets)


def test_refund_requires_confirmation_and_supervisor_once():
    with TestClient(app) as client:
        ava = headers("ava.customer@northstar.test")
        conversation = client.post("/api/v1/conversations", headers=ava, json={}).json()["id"]
        response = client.post(f"/api/v1/conversations/{conversation}/messages", headers=headers(
            "ava.customer@northstar.test", **{"Idempotency-Key": "refund-key"}), json={"body": "I want a refund for NS-1042"})
        assert response.status_code == 202
        client.post("/api/v1/internal/worker/run", headers=headers("maya.agent@northstar.test"))
        action = client.get(f"/api/v1/conversations/{conversation}", headers=ava).json()["pending_actions"][0]
        assert client.post(f"/api/v1/actions/{action['id']}/confirm", headers=ava, json={"version": 1}).json()["status"] == "awaiting_supervisor_approval"
        supervisor = headers("sam.supervisor@northstar.test")
        approval = client.get("/api/v1/approvals", headers=supervisor).json()[0]
        approved = client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=supervisor, json={"reason": "Policy applies"})
        assert approved.status_code == 200 and approved.json()["status"] == "succeeded"
        assert client.post(f"/api/v1/approvals/{approval['id']}/approve", headers=supervisor, json={"reason": "Replay"}).status_code == 409


def test_local_auth_is_rejected_in_cloud_mode(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "cloud")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    try:
        try: get_settings()
        except RuntimeError as exc: assert "forbidden" in str(exc)
        else: assert False, "cloud mode accepted local auth"
    finally:
        monkeypatch.delenv("APP_ENV", raising=False); monkeypatch.delenv("AUTH_PROVIDER", raising=False); get_settings.cache_clear()
