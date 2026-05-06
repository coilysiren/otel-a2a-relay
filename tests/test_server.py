"""End-to-end tests for the A2A relay's HTTP surface.

Uses an in-memory span exporter to verify the relay emits the v0.1 a2a.task
span shape on `message/send`, without needing a Phoenix instance.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otel_a2a_relay.server import create_app


@pytest.fixture
def captured_spans() -> Iterator[tuple[TestClient, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app(provider=provider)
    with TestClient(app) as client:
        yield client, exporter


def _spans_by_name(exporter: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {s.name: s for s in exporter.get_finished_spans()}


def test_healthz(captured_spans: tuple[TestClient, InMemorySpanExporter]) -> None:
    client, _ = captured_spans
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "protocol": "0.1", "peers": []}


def test_message_send_returns_completed_task(
    captured_spans: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, _ = captured_spans
    r = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "hi"}],
                    "messageId": "msg-1",
                    "taskId": "task-abc",
                    "contextId": "ctx-xyz",
                    "metadata": {"agent.id": "A"},
                }
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["kind"] == "task"
    assert result["id"] == "task-abc"
    assert result["contextId"] == "ctx-xyz"
    assert result["status"]["state"] == "completed"


def test_message_send_emits_v0_1_task_span(
    captured_spans: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, exporter = captured_spans
    client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "msg-1",
                    "taskId": "task-abc",
                    "contextId": "ctx-xyz",
                    "metadata": {"agent.id": "A"},
                }
            },
        },
    )
    spans = _spans_by_name(exporter)
    assert "a2a.task" in spans
    span = spans["a2a.task"]
    attrs = span.attributes or {}
    assert attrs["session.id"] == "ctx-xyz"
    assert attrs["a2a.task.id"] == "task-abc"
    assert attrs["agent.id"] == "relay"
    assert attrs["graph.node.id"] == "relay"
    assert attrs["graph.node.parent_id"] == "A"
    assert attrs["openinference.span.kind"] == "AGENT"
    assert attrs["a2a.task.state"] == "completed"
    event_names = [e.name for e in span.events]
    assert event_names == ["a2a.task.state_change", "a2a.task.state_change"]


def test_unknown_method_returns_jsonrpc_error(
    captured_spans: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, _ = captured_spans
    r = client.post(
        "/",
        json={"jsonrpc": "2.0", "id": 7, "method": "tasks/nonsense", "params": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 7
    assert body["error"]["code"] == -32601
