"""Tests for the REST API endpoints (ASGI transport, no network)."""

from __future__ import annotations

import pytest_asyncio
from backend.main import app
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    # Avoid real RPC during the health check.
    from backend.blockchain.client import MantleClient

    async def _connected(self):  # noqa: ARG001
        return True

    monkeypatch.setattr(MantleClient, "is_connected", _connected)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "service" in resp.json()


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"] is True
    assert body["rpc"] is True


async def test_create_and_list_alert(client):
    payload = {"telegram_id": 4242, "token": "mETH", "threshold_usd": 10000}
    resp = await client.post("/alerts", json=payload)
    assert resp.status_code == 201, resp.text
    rule = resp.json()
    assert rule["token_symbol"] == "METH"
    assert rule["threshold_usd"] == 10000

    resp = await client.get("/alerts", params={"telegram_id": 4242})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_create_alert_validation_error(client):
    payload = {"telegram_id": 4242, "token": "mETH", "threshold_usd": 1}
    resp = await client.post("/alerts", json=payload)
    assert resp.status_code == 400


async def test_delete_alert(client):
    create = await client.post(
        "/alerts", json={"telegram_id": 9090, "token": "MNT", "threshold_usd": 20000}
    )
    rule_id = create.json()["id"]
    resp = await client.delete(f"/alerts/{rule_id}", params={"telegram_id": 9090})
    assert resp.status_code == 200
    # Now the list should be empty.
    resp = await client.get("/alerts", params={"telegram_id": 9090})
    assert resp.json() == []


async def test_history_empty(client):
    resp = await client.get("/history", params={"telegram_id": 4242})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_user_not_found(client):
    resp = await client.get("/users/999999")
    assert resp.status_code == 404


async def test_openapi_available(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"]
