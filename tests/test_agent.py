"""Tests for the peer agent."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otel_a2a_relay.agent import create_app


@pytest.fixture
def agent_b() -> Iterator[tuple[TestClient, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = create_app("B", provider=provider)
    with TestClient(app) as client:
        yield client, exporter


def test_message_send_returns_echo_reply(
    agent_b: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, _ = agent_b
    r = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "x",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m-1",
                    "taskId": "t-1",
                    "contextId": "ctx",
                    "parts": [{"kind": "text", "text": "ping"}],
                    "metadata": {"agent.id": "A"},
                }
            },
        },
    )
    body = r.json()
    assert body["result"]["status"]["state"] == "completed"
    history = body["result"]["history"]
    reply = history[-1]
    assert reply["role"] == "agent"
    assert reply["parts"][0]["text"] == "echo from B: ping"


def test_message_send_emits_task_span_with_input_output(
    agent_b: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, exporter = agent_b
    client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "x",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m-1",
                    "taskId": "t-1",
                    "contextId": "ctx",
                    "parts": [{"kind": "text", "text": "hello"}],
                    "metadata": {"agent.id": "A"},
                }
            },
        },
    )
    spans = {s.name: s for s in exporter.get_finished_spans()}
    span = spans["a2a.task"]
    attrs = span.attributes or {}
    assert attrs["agent.id"] == "B"
    assert attrs["graph.node.parent_id"] == "A"
    assert attrs["a2a.message.text"] == "hello"
    assert attrs["a2a.message.reply_text"] == "echo from B: hello"
    assert attrs["a2a.task.state"] == "completed"


def test_agent_card_endpoint(
    agent_b: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, _ = agent_b
    r = client.get("/.well-known/agent.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "B-echo-agent"
    assert card["protocolVersion"] == "0.2.5"
    assert any(s["id"] == "echo" for s in card.get("skills", []))


def test_tasks_get_after_message_send(
    agent_b: tuple[TestClient, InMemorySpanExporter],
) -> None:
    client, _ = agent_b
    client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "x",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m-1",
                    "taskId": "agent-stored",
                    "contextId": "ctx",
                    "parts": [{"kind": "text", "text": "hi"}],
                    "metadata": {"agent.id": "A"},
                }
            },
        },
    )
    r = client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "y",
            "method": "tasks/get",
            "params": {"id": "agent-stored"},
        },
    )
    body = r.json()
    assert body["result"]["id"] == "agent-stored"
