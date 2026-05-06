"""Minimum viable A2A relay server.

Accepts JSON-RPC 2.0 `message/send` over HTTP, emits the v0.1 `a2a.task` span
shape on the receiving side, and returns a synthetic completed Task. No peer
forwarding, no streaming, no persistence. The point of this slice is to prove
the relay can speak A2A and emit the right spans.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from otel_a2a_relay.telemetry import make_provider

PROTOCOL_VERSION = "0.1"
RELAY_AGENT_ID = "relay"
RELAY_AGENT_NAME = "otel-a2a-relay"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jsonrpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


def handle_message_send(tracer: Tracer, params: dict[str, Any]) -> dict[str, Any]:
    """Emit the v0.1 a2a.task span for an incoming message/send and return a Task."""
    message = params.get("message") or {}
    context_id = message.get("contextId") or str(uuid.uuid4())
    task_id = message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}"
    sender_id = (message.get("metadata") or {}).get("agent.id", "unknown")

    with tracer.start_as_current_span(
        "a2a.task",
        kind=SpanKind.SERVER,
        attributes={
            "session.id": context_id,
            "a2a.task.id": task_id,
            "agent.id": RELAY_AGENT_ID,
            "agent.name": RELAY_AGENT_NAME,
            "openinference.span.kind": "AGENT",
            "graph.node.id": RELAY_AGENT_ID,
            "graph.node.parent_id": sender_id,
            "a2a.task.state": "working",
        },
    ) as span:
        span.add_event(
            "a2a.task.state_change",
            attributes={"from": "submitted", "to": "working"},
        )
        # No peer forwarding yet, so no work happens. Mark complete.
        span.add_event(
            "a2a.task.state_change",
            attributes={"from": "working", "to": "completed"},
        )
        span.set_attribute("a2a.task.state", "completed")
        span.set_status(Status(StatusCode.OK))

    return {
        "id": task_id,
        "contextId": context_id,
        "kind": "task",
        "status": {"state": "completed", "timestamp": _now_iso()},
        "history": [message] if message else [],
    }


def create_app(provider: TracerProvider | None = None) -> FastAPI:
    """Build the FastAPI app. Pass a custom TracerProvider for tests; defaults to OTLP."""
    tracer = (provider or make_provider()).get_tracer("otel-a2a-relay")
    app = FastAPI(title="otel-a2a-relay", version=PROTOCOL_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION}

    @app.post("/")
    async def jsonrpc(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _jsonrpc_error(None, -32700, "Parse error")

        if payload.get("jsonrpc") != "2.0" or "method" not in payload:
            return _jsonrpc_error(payload.get("id"), -32600, "Invalid Request")

        method = payload["method"]
        req_id = payload.get("id")
        params = payload.get("params") or {}

        if method == "message/send":
            result = handle_message_send(tracer, params)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    return app
