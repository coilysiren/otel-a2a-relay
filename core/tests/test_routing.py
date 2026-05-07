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
from otel_a2a_relay_core.server import create_app


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
    assert relay_attrs["o2r.relay.mode"] == "forward"
    assert relay_attrs["o2r.peer.target"] == "B"
    assert relay_attrs["o2r.message.text"] == "ping"

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
    assert relay_attrs["o2r.relay.mode"] == "synthesize"


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
    assert attrs["o2r.relay.mode"] == "synthesize-stream"


def test_forward_peer_returns_error_envelope() -> None:
    """Peer returns a JSON-RPC error body; relay surfaces it and marks task failed."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": "x", "error": {"code": -1, "message": "no"}}
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=http_client)
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-fwd-err",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    http_client.close()
    body = r.json()
    assert body["error"]["code"] == -1
    relay = _spans_by_name(exporter)["a2a.task"]
    attrs = relay.attributes or {}
    assert attrs["o2r.task.state"] == "failed"


def test_forward_peer_returns_non_json() -> None:
    """Peer returns 200 with a body that isn't valid JSON; relay returns -32011."""
    provider = TracerProvider()

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "text/plain"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=http_client)
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-nonjson",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    http_client.close()
    body = r.json()
    assert body["error"]["code"] == -32011
    assert "non-JSON" in body["error"]["message"]


def test_forward_peer_unreachable() -> None:
    """httpx raises before any response; relay returns -32011."""
    provider = TracerProvider()

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=http_client)
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-unreachable",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    http_client.close()
    body = r.json()
    assert body["error"]["code"] == -32011
    assert "forward to B failed" in body["error"]["message"]


def test_forward_uses_default_client_when_none_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """If create_app gets http_client=None, the relay constructs one and closes it."""
    provider = TracerProvider()
    closed: list[bool] = []

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "result": {
                    "id": "t-default-client",
                    "contextId": "ctx",
                    "kind": "task",
                    "status": {"state": "completed"},
                    "history": [],
                },
            },
        )

    real_client_cls = httpx.Client

    def fake_client_ctor(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        c = real_client_cls(*args, **kwargs)
        original_close = c.close

        def tracked_close() -> None:
            closed.append(True)
            original_close()

        c.close = tracked_close  # type: ignore[method-assign]
        return c

    monkeypatch.setattr(httpx, "Client", fake_client_ctor)
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=None)
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": "x",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m-1",
                        "taskId": "t-default-client",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        )
    assert r.json()["result"]["id"] == "t-default-client"
    assert closed, "default httpx client was not closed"


def test_message_stream_forwards_to_peer() -> None:
    """Streaming forward path: peer SSE chunks are passed through and recorded as span events."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    sse_body = (
        b'data: {"result":{"kind":"artifact-update",'
        b'"artifact":{"parts":[{"kind":"text","text":"hi "}]},"lastChunk":false}}\n\n'
        b'data: {"result":{"kind":"artifact-update",'
        b'"artifact":{"parts":[{"kind":"text","text":"there"}]},"lastChunk":true}}\n\n'
        b'data: {"result":{"kind":"status-update","status":{"state":"completed"},"final":true}}\n\n'
        b"\n"
        b"data: not-json\n\n"
    )

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=http_client)
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
                        "taskId": "t-fwd-stream",
                        "contextId": "ctx-fs",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        ) as r:
            data_lines = [
                line.decode() if isinstance(line, bytes) else line
                for line in r.iter_lines()
                if (line.decode() if isinstance(line, bytes) else line).startswith("data: ")
            ]
    http_client.close()
    assert any("artifact-update" in line for line in data_lines)

    spans = _spans_by_name(exporter)
    assert spans["a2a.task"].attributes["o2r.relay.mode"] == "forward-stream"  # type: ignore[index]
    relay_task = spans["a2a.task"]
    chunk_events = [e for e in relay_task.events if e.name == "a2a.message.stream_chunk"]
    assert len(chunk_events) == 2
    # Stored task entry should be persisted via the stream path.
    listing_app_resp = TestClient(app).get("/tasks").json()
    assert any(t["id"] == "t-fwd-stream" for t in listing_app_resp["tasks"])


def test_message_stream_forward_uses_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streaming forward with http_client=None constructs and closes its own client."""
    provider = TracerProvider()
    closed: list[bool] = []

    sse_body = (
        b'data: {"result":{"kind":"status-update","status":{"state":"completed"},"final":true}}\n\n'
    )

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    real_client_cls = httpx.Client

    def fake_client_ctor(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        c = real_client_cls(*args, **kwargs)
        original_close = c.close

        def tracked_close() -> None:
            closed.append(True)
            original_close()

        c.close = tracked_close  # type: ignore[method-assign]
        return c

    monkeypatch.setattr(httpx, "Client", fake_client_ctor)
    app = create_app(provider=provider, peers={"B": "http://stub/"}, http_client=None)
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
                        "taskId": "t-stream-default",
                        "contextId": "ctx",
                        "metadata": {"agent.id": "A", "agent.target": "B"},
                    }
                },
            },
        ) as r:
            list(r.iter_lines())
    assert closed, "default streaming client was not closed"


def test_tasks_get_missing_id_returns_error() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {}})
    assert r.json()["error"]["code"] == -32602


def test_tasks_cancel_missing_id_returns_error() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post(
            "/", json={"jsonrpc": "2.0", "id": 1, "method": "tasks/cancel", "params": {}}
        )
    assert r.json()["error"]["code"] == -32602


def test_tasks_cancel_unknown_id_returns_error() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/cancel",
                "params": {"id": "not-real"},
            },
        )
    assert r.json()["error"]["code"] == -32001


def test_jsonrpc_parse_error_on_invalid_body() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post("/", content=b"{not-json")
    body = r.json()
    assert body["error"]["code"] == -32700


def test_jsonrpc_invalid_request_missing_method() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post("/", json={"jsonrpc": "2.0", "id": 1})
    body = r.json()
    assert body["error"]["code"] == -32600


def test_list_peers_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /peers fetches each peer's agent card with httpx.get."""

    class FakeGetResponse:
        def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
            self.status_code = status_code
            self._payload = payload or {}

        def json(self) -> dict[str, Any]:
            return self._payload

    def fake_get(url: str, timeout: float = 0) -> FakeGetResponse:
        if "ok-peer" in url:
            return FakeGetResponse(200, {"name": "ok-card", "skills": []})
        if "bad-status" in url:
            return FakeGetResponse(503)
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "get", fake_get)
    app = create_app(
        provider=TracerProvider(),
        peers={
            "OK": "http://ok-peer/",
            "BAD": "http://bad-status/",
            "DOWN": "http://down/",
        },
        peer_roles={"OK": "worker"},
    )
    with TestClient(app) as client:
        r = client.get("/peers")
    by_id = {p["id"]: p for p in r.json()["peers"]}
    assert by_id["OK"]["card"] == {"name": "ok-card", "skills": []}
    assert by_id["OK"]["role"] == "worker"
    assert by_id["BAD"]["card_error"] == "http 503"
    assert "nope" in by_id["DOWN"]["card_error"]


def test_register_peer_invalid_json_returns_400() -> None:
    app = create_app(provider=TracerProvider(), peers={})
    with TestClient(app) as client:
        r = client.post("/peers", content=b"{not-json")
    assert r.status_code == 400


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
