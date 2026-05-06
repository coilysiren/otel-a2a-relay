"""A2A relay server.

Speaks JSON-RPC 2.0 over HTTP. Two modes per `message/send` request:

1. Synthesize. No peer registered for `metadata.agent.target`. The relay
   completes the task itself and returns a synthetic Task. Useful for
   smoke-testing the OTel emission path without a real peer.
2. Forward. A peer is registered. The relay POSTs the same JSON-RPC
   envelope to the peer's URL, with W3C traceparent headers injected so
   the peer's span attaches to the relay's forwarding span. The peer's
   Task result flows back to the original sender.

Either way, the relay emits an `a2a.task` SERVER span on its own side, so
even agents that aren't OTel-aware contribute one routed span per hop.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from otel_a2a_relay.store import TaskStore
from otel_a2a_relay.telemetry import make_provider

PROTOCOL_VERSION = "0.1"
RELAY_AGENT_ID = "relay"
RELAY_AGENT_NAME = "otel-a2a-relay"


def parse_peers(spec: str | None) -> dict[str, str]:
    """Parse `A=http://host:port,B=http://...` into a dict.

    Whitespace around entries is tolerated. Empty/None spec returns {}.
    """
    if not spec:
        return {}
    out: dict[str, str] = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        agent_id, url = entry.split("=", 1)
        agent_id, url = agent_id.strip(), url.strip()
        if agent_id and url:
            out[agent_id] = url
    return out


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jsonrpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


def _synthesize_task(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}",
        "contextId": message.get("contextId") or str(uuid.uuid4()),
        "kind": "task",
        "status": {"state": "completed", "timestamp": _now_iso()},
        "history": [message] if message else [],
    }


def handle_message_send(
    tracer: Tracer,
    payload: dict[str, Any],
    peers: dict[str, str],
    store: TaskStore,
    http_client: httpx.Client | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Emit the relay-side a2a.task span, optionally forward to a peer, return JSON-RPC result."""
    params = payload.get("params") or {}
    req_id = payload.get("id")
    message = params.get("message") or {}
    metadata = message.get("metadata") or {}
    context_id = message.get("contextId") or str(uuid.uuid4())
    task_id = message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}"
    sender_id = metadata.get("agent.id", "unknown")
    target_id = metadata.get("agent.target")
    peer_url = peers.get(target_id) if target_id else None

    parts = message.get("parts") or []
    input_text = next(
        (p.get("text", "") for p in parts if p.get("kind") == "text"),
        "",
    )

    incoming_ctx = extract(headers or {})

    with tracer.start_as_current_span(
        "a2a.task",
        context=incoming_ctx,
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
            "a2a.peer.target": target_id or "",
            "a2a.relay.mode": "forward" if peer_url else "synthesize",
            "input.value": json.dumps({"role": message.get("role", "user"), "parts": parts}),
            "input.mime_type": "application/json",
            "a2a.message.text": input_text,
        },
    ) as span:
        span.add_event(
            "a2a.task.state_change",
            attributes={"from": "submitted", "to": "working"},
        )

        result: dict[str, Any]
        if peer_url:
            forward_payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "message/send",
                "params": params,
            }
            outgoing_headers: dict[str, str] = {}
            inject(outgoing_headers)
            with tracer.start_as_current_span(
                "a2a.relay.forward",
                kind=SpanKind.CLIENT,
                attributes={
                    "session.id": context_id,
                    "a2a.task.id": task_id,
                    "agent.id": RELAY_AGENT_ID,
                    "graph.node.id": RELAY_AGENT_ID,
                    "peer.agent.id": target_id or "",
                    "peer.url": peer_url,
                    "openinference.span.kind": "AGENT",
                    "rpc.system": "jsonrpc",
                    "rpc.service": "a2a",
                    "rpc.method": "message/send",
                },
            ) as fwd:
                client = http_client or httpx.Client(timeout=30.0)
                close_after = http_client is None
                try:
                    resp = client.post(peer_url, json=forward_payload, headers=outgoing_headers)
                    fwd.set_attribute("http.status_code", resp.status_code)
                    body = resp.json()
                finally:
                    if close_after:
                        client.close()
            if "error" in body:
                span.set_attribute("a2a.task.state", "failed")
                span.set_status(Status(StatusCode.ERROR, str(body["error"])))
                span.add_event(
                    "a2a.task.state_change",
                    attributes={"from": "working", "to": "failed"},
                )
                return {"jsonrpc": "2.0", "id": req_id, "error": body["error"]}
            result = body.get("result") or _synthesize_task(message)
        else:
            result = _synthesize_task(message)

        span.add_event(
            "a2a.task.state_change",
            attributes={"from": "working", "to": "completed"},
        )
        span.set_attribute("a2a.task.state", "completed")
        span.set_status(Status(StatusCode.OK))
        store.put(result)

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_tasks_get(
    payload: dict[str, Any],
    store: TaskStore,
) -> dict[str, Any]:
    params = payload.get("params") or {}
    req_id = payload.get("id")
    task_id = params.get("id") or params.get("taskId")
    if not task_id:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Missing task id"},
        }
    task = store.get(task_id)
    if not task:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32001, "message": f"Unknown task: {task_id}"},
        }
    return {"jsonrpc": "2.0", "id": req_id, "result": task}


def handle_tasks_cancel(
    tracer: Tracer,
    payload: dict[str, Any],
    store: TaskStore,
) -> dict[str, Any]:
    params = payload.get("params") or {}
    req_id = payload.get("id")
    task_id = params.get("id") or params.get("taskId")
    if not task_id:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Missing task id"},
        }
    task = store.get(task_id)
    if not task:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32001, "message": f"Unknown task: {task_id}"},
        }
    prev_state = task.get("status", {}).get("state", "unknown")
    updated = store.update_state(task_id, "canceled") or task
    with tracer.start_as_current_span(
        "a2a.task.cancel",
        kind=SpanKind.SERVER,
        attributes={
            "session.id": task.get("contextId", ""),
            "a2a.task.id": task_id,
            "agent.id": RELAY_AGENT_ID,
            "graph.node.id": RELAY_AGENT_ID,
            "openinference.span.kind": "AGENT",
        },
    ) as span:
        span.add_event(
            "a2a.task.state_change",
            attributes={"from": prev_state, "to": "canceled"},
        )
    return {"jsonrpc": "2.0", "id": req_id, "result": updated}


def create_app(
    provider: TracerProvider | None = None,
    peers: dict[str, str] | None = None,
    http_client: httpx.Client | None = None,
    store: TaskStore | None = None,
) -> FastAPI:
    """Build the FastAPI app. Pass a custom TracerProvider for tests; defaults to OTLP.

    `peers` overrides the env-var registry. `http_client` lets tests stub the
    forwarding HTTP call. `store` is the in-memory task index; default per-app.
    """
    tracer = (provider or make_provider()).get_tracer("otel-a2a-relay")
    if peers is None:
        peers = parse_peers(os.environ.get("OTEL_A2A_RELAY_PEERS"))
    task_store = store or TaskStore()

    app = FastAPI(title="otel-a2a-relay", version=PROTOCOL_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION, "peers": sorted(peers.keys())}

    @app.get("/tasks")
    def list_tasks() -> dict[str, Any]:
        return {"tasks": task_store.all()}

    @app.get("/peers")
    def list_peers() -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for pid, purl in sorted(peers.items()):
            entry: dict[str, Any] = {"id": pid, "url": purl}
            try:
                resp = httpx.get(
                    purl.rstrip("/") + "/.well-known/agent.json",
                    timeout=2.0,
                )
                if resp.status_code == 200:
                    entry["card"] = resp.json()
                else:
                    entry["card_error"] = f"http {resp.status_code}"
            except httpx.HTTPError as e:
                entry["card_error"] = str(e)
            out.append(entry)
        return {"peers": out}

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

        if method == "message/send":
            return JSONResponse(
                handle_message_send(
                    tracer,
                    payload,
                    peers,
                    task_store,
                    http_client,
                    headers=dict(request.headers),
                )
            )
        if method == "tasks/get":
            return JSONResponse(handle_tasks_get(payload, task_store))
        if method == "tasks/cancel":
            return JSONResponse(handle_tasks_cancel(tracer, payload, task_store))

        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    return app
