"""Tests for dynamic peer registration + star-topology enforcement.

Both are relay-management surface (out of A2A→OTel protocol scope, see
docs/protocol.md). The endpoints exist so the LUCA-flow demo can spin
workers up and down without restarting the relay, and the enforcement
exists so a misbehaving worker can't bypass the orchestrator.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from otel_a2a_relay_core.server import create_app


def _stub_client() -> httpx.Client:
    """A stub that returns a fixed completed-task envelope for any forwarded request."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "result": {
                    "id": "task-x",
                    "contextId": "ctx",
                    "kind": "task",
                    "status": {"state": "completed", "timestamp": "2026-01-01T00:00:00Z"},
                    "history": [],
                },
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_register_peer_adds_to_registry() -> None:
    app = create_app(provider=TracerProvider(), peers={}, peer_roles={})
    with TestClient(app) as client:
        r = client.post(
            "/peers",
            json={"id": "worker-a", "url": "http://stub/", "role": "worker"},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True, "id": "worker-a", "url": "http://stub/", "role": "worker"}

        h = client.get("/healthz").json()
        assert "worker-a" in h["peers"]
        assert h["roles"]["worker-a"] == "worker"


def test_register_peer_rejects_unknown_role() -> None:
    app = create_app(provider=TracerProvider(), peers={}, peer_roles={})
    with TestClient(app) as client:
        r = client.post(
            "/peers",
            json={"id": "x", "url": "http://stub/", "role": "supervisor"},
        )
    assert r.status_code == 400
    assert "must be one of" in r.json()["error"]


def test_register_peer_rejects_missing_fields() -> None:
    app = create_app(provider=TracerProvider(), peers={}, peer_roles={})
    with TestClient(app) as client:
        r = client.post("/peers", json={"id": "x"})
    assert r.status_code == 400


def test_deregister_peer_removes_from_registry() -> None:
    peers = {"worker-a": "http://stub/"}
    roles = {"worker-a": "worker"}
    app = create_app(provider=TracerProvider(), peers=peers, peer_roles=roles)
    with TestClient(app) as client:
        r = client.delete("/peers/worker-a")
        assert r.status_code == 200
        h = client.get("/healthz").json()
    assert "worker-a" not in h["peers"]
    assert "worker-a" not in h["roles"]
    assert peers == {} and roles == {}


def test_star_enforcement_allows_worker_to_orchestrator() -> None:
    """worker → orchestrator: allowed."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    http_client = _stub_client()
    app = create_app(
        provider=provider,
        peers={"orchestrator": "http://stub/"},
        peer_roles={"orchestrator": "orchestrator", "worker-a": "worker"},
        http_client=http_client,
        star_enforce=True,
    )
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-1",
                        "contextId": "ctx",
                        "metadata": {
                            "agent.id": "worker-a",
                            "agent.target": "orchestrator",
                        },
                    }
                },
            },
        )
    assert r.status_code == 200
    assert "error" not in r.json()
    http_client.close()


def test_star_enforcement_allows_orchestrator_to_worker() -> None:
    """orchestrator → worker: allowed."""
    http_client = _stub_client()
    app = create_app(
        provider=TracerProvider(),
        peers={"worker-a": "http://stub/"},
        peer_roles={"orchestrator": "orchestrator", "worker-a": "worker"},
        http_client=http_client,
        star_enforce=True,
    )
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-1",
                        "contextId": "ctx",
                        "metadata": {
                            "agent.id": "orchestrator",
                            "agent.target": "worker-a",
                        },
                    }
                },
            },
        )
    assert r.status_code == 200
    assert "error" not in r.json()
    http_client.close()


@pytest.mark.parametrize(
    "sender_role,target_role",
    [
        ("worker", "validator"),
        ("worker", "planner"),
        ("worker", "worker"),
        ("validator", "planner"),
    ],
)
def test_star_enforcement_rejects_non_orchestrator_routes(
    sender_role: str, target_role: str
) -> None:
    """Anything that doesn't touch the orchestrator: rejected."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(
        provider=provider,
        peers={"sender": "http://s/", "target": "http://t/"},
        peer_roles={"sender": sender_role, "target": target_role},
        star_enforce=True,
    )
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-1",
                        "contextId": "ctx",
                        "metadata": {
                            "agent.id": "sender",
                            "agent.target": "target",
                        },
                    }
                },
            },
        )
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == -32010
    assert "star-topology violation" in body["error"]["message"]

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert "a2a.relay.reject" in span_names


def test_star_enforcement_off_allows_all() -> None:
    """With star_enforce=False (default), legacy behavior preserved."""
    http_client = _stub_client()
    app = create_app(
        provider=TracerProvider(),
        peers={"target": "http://stub/"},
        peer_roles={"sender": "worker", "target": "validator"},
        http_client=http_client,
        star_enforce=False,
    )
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-1",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "sender", "agent.target": "target"},
                    }
                },
            },
        )
    body = r.json()
    assert "error" not in body
    http_client.close()


def test_unregistered_peers_not_enforced() -> None:
    """If neither sender nor target carries a role, enforcement skips
    (preserves the existing dogfood with anonymous A/B agents)."""
    http_client = _stub_client()
    app = create_app(
        provider=TracerProvider(),
        peers={"B": "http://stub/"},
        peer_roles={},  # neither A nor B has a registered role
        http_client=http_client,
        star_enforce=True,
    )
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-1",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    assert "error" not in r.json()
    http_client.close()
