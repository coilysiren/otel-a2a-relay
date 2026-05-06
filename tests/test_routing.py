"""Tests for peer-routing on the relay.

Stubs httpx so the test does not need a running peer agent.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otel_a2a_relay.server import create_app


class _StubPeer(httpx.MockTransport):
    """httpx transport that records the request and returns a fixed Task."""

    def __init__(self, response_body: dict[str, Any]) -> None:
        self.received: dict[str, Any] | None = None
        self.received_headers: dict[str, str] | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            self.received = (
                request.read().decode() if request.content is not None else ""  # type: ignore[assignment]
            )
            self.received_headers = dict(request.headers)
            return httpx.Response(200, json=response_body)

        super().__init__(handler)


@pytest.fixture
def routed_app() -> Iterator[tuple[TestClient, InMemorySpanExporter, _StubPeer]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    peer_response = {
        "jsonrpc": "2.0",
        "id": "abc",
        "result": {
            "id": "task-routed",
            "contextId": "ctx-1",
            "kind": "task",
            "status": {"state": "completed", "timestamp": "2026-01-01T00:00:00Z"},
            "history": [],
        },
    }
    stub = _StubPeer(peer_response)
    http_client = httpx.Client(transport=stub)
    app = create_app(
        provider=provider,
        peers={"B": "http://stub-peer/"},
        http_client=http_client,
    )
    with TestClient(app) as client:
        yield client, exporter, stub
    http_client.close()


def _spans_by_name(exporter: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {s.name: s for s in exporter.get_finished_spans()}


def test_forward_path_emits_relay_and_forward_spans(
    routed_app: tuple[TestClient, InMemorySpanExporter, _StubPeer],
) -> None:
    client, exporter, _ = routed_app
    r = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "abc",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m-1",
                    "taskId": "task-routed",
                    "contextId": "ctx-1",
                    "parts": [{"kind": "text", "text": "ping"}],
                    "metadata": {"agent.id": "A", "agent.target": "B"},
                }
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["id"] == "task-routed"

    spans = _spans_by_name(exporter)
    assert "a2a.task" in spans
    assert "a2a.relay.forward" in spans

    relay_task = spans["a2a.task"]
    relay_attrs = relay_task.attributes or {}
    assert relay_attrs["a2a.relay.mode"] == "forward"
    assert relay_attrs["a2a.peer.target"] == "B"
    assert relay_attrs["a2a.message.text"] == "ping"

    fwd = spans["a2a.relay.forward"]
    fwd_attrs = fwd.attributes or {}
    assert fwd_attrs["peer.agent.id"] == "B"
    assert fwd_attrs["peer.url"] == "http://stub-peer/"
    assert fwd_attrs["http.status_code"] == 200


def test_forward_injects_traceparent(
    routed_app: tuple[TestClient, InMemorySpanExporter, _StubPeer],
) -> None:
    client, _, stub = routed_app
    client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "abc",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m-1",
                    "taskId": "task-routed",
                    "contextId": "ctx-1",
                    "metadata": {"agent.id": "A", "agent.target": "B"},
                }
            },
        },
    )
    assert stub.received_headers is not None
    assert "traceparent" in {k.lower() for k in stub.received_headers}


def test_synthesize_path_when_no_peer_registered() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(provider=provider, peers={})
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
                        "taskId": "task-synth",
                        "contextId": "ctx-2",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    body = r.json()
    assert body["result"]["status"]["state"] == "completed"
    spans = _spans_by_name(exporter)
    assert "a2a.relay.forward" not in spans
    relay_attrs = spans["a2a.task"].attributes or {}
    assert relay_attrs["a2a.relay.mode"] == "synthesize"


def test_tasks_get_returns_stored_task() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "task-stored",
                        "contextId": "ctx-3",
                        "metadata": {"agent.id": "A"},
                    }
                },
            },
        )
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tasks/get",
                "params": {"id": "task-stored"},
            },
        )
    body = r.json()
    assert body["result"]["id"] == "task-stored"
    assert body["result"]["contextId"] == "ctx-3"


def test_tasks_get_unknown_returns_error() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/get",
                "params": {"id": "missing"},
            },
        )
    body = r.json()
    assert body["error"]["code"] == -32001


def test_tasks_cancel_marks_canceled_and_emits_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(provider=provider, peers={})
    with TestClient(app) as client:
        client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "task-cancel",
                        "contextId": "ctx-4",
                        "metadata": {"agent.id": "A"},
                    }
                },
            },
        )
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tasks/cancel",
                "params": {"id": "task-cancel"},
            },
        )
    body = r.json()
    assert body["result"]["status"]["state"] == "canceled"
    span_names = [s.name for s in exporter.get_finished_spans()]
    assert "a2a.task.cancel" in span_names


def test_message_stream_synthesizes_when_no_peer() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(provider=provider, peers={})
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "message/stream",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-stream-syn",
                        "contextId": "ctx-s",
                        "metadata": {"agent.id": "A", "agent.target": "Z"},
                    }
                },
            },
        ) as r:
            lines = list(r.iter_lines())
    data_lines = [line for line in lines if line.startswith("data: ")]
    assert len(data_lines) == 1
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert "a2a.task" in spans
    attrs = spans["a2a.task"].attributes or {}
    assert attrs["a2a.relay.mode"] == "synthesize-stream"


def test_tasks_listing_endpoint() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        for tid in ("t1", "t2"):
            client.post(
                "/",
                json={
                    "jsonrpc": "2.0",
                    "id": tid,
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": tid,
                            "taskId": tid,
                            "contextId": "ctx",
                            "metadata": {"agent.id": "A"},
                        }
                    },
                },
            )
        r = client.get("/tasks")
    ids = sorted(t["id"] for t in r.json()["tasks"])
    assert ids == ["t1", "t2"]
