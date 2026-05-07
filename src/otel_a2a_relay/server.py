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
from collections.abc import Iterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openinference.instrumentation import using_session, using_user
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from otel_a2a_relay.store import TaskStore
from otel_a2a_relay.telemetry import make_provider

RELAY_ROLE = "relay"

PROTOCOL_VERSION = "0.3"
RELAY_AGENT_ID = "relay"
RELAY_AGENT_NAME = "o2r"

# Star-topology roles. The orchestrator is the only role that may target
# peers other than itself; everyone else may only target the orchestrator.
ORCHESTRATOR_ROLE = "orchestrator"
KNOWN_ROLES = frozenset({"orchestrator", "planner", "validator", "worker", "deployer"})


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


def _classify_relay_reject(reason: str) -> str:
    """Coarse `o2r.relay.failure_class` for any relay rejection.

    Phoenix's `relay_failure_class` annotation config (see
    `scripts/phoenix-bootstrap.py`) consumes this so erroring spans show up
    grouped by class without a human having to read each reason string.
    Values - kept stable, machine-readable: `topology_violation`,
    `peer_disconnect`, `peer_404`, `timeout`, `peer_jsonrpc_error`, `unknown`.
    """
    r = reason.lower()
    if "star-topology" in r:
        return "topology_violation"
    if "404" in r:
        return "peer_404"
    if "timeout" in r:
        return "timeout"
    if "connect" in r or "remoteprotocol" in r or "readerror" in r or "non-json" in r:
        return "peer_disconnect"
    return "unknown"


def _check_star_topology(
    sender_id: str,
    target_id: str | None,
    peer_roles: dict[str, str],
) -> str | None:
    """Return None if the route is allowed under star topology, else a reason string.

    Rule: if either sender or target carries the orchestrator role, the route
    is allowed. Otherwise it's rejected. Peers without a registered role are
    treated as unconstrained (legacy / dogfood mode).
    """
    sender_role = peer_roles.get(sender_id)
    target_role = peer_roles.get(target_id) if target_id else None
    # Both unknown: not enforced (legacy callers).
    if sender_role is None and target_role is None:
        return None
    # Orchestrator on either end: allowed.
    if sender_role == ORCHESTRATOR_ROLE or target_role == ORCHESTRATOR_ROLE:
        return None
    return (
        f"star-topology violation: {sender_id} (role={sender_role!r}) "
        f"may not target {target_id} (role={target_role!r}); "
        f"all routes must traverse the orchestrator"
    )


def handle_message_send(
    tracer: Tracer,
    payload: dict[str, Any],
    peers: dict[str, str],
    store: TaskStore,
    http_client: httpx.Client | None = None,
    headers: dict[str, str] | None = None,
    peer_roles: dict[str, str] | None = None,
    star_enforce: bool = False,
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
    peer_roles = peer_roles or {}

    if star_enforce:
        violation = _check_star_topology(sender_id, target_id, peer_roles)
        if violation is not None:
            with (
                using_session(context_id),
                using_user(sender_id),
                tracer.start_as_current_span(
                    "a2a.relay.reject",
                    kind=SpanKind.SERVER,
                    attributes={
                        "session.id": context_id,
                        "user.id": sender_id,
                        "o2r.task.id": task_id,
                        "agent.id": RELAY_AGENT_ID,
                        "agent.role": RELAY_ROLE,
                        "openinference.span.kind": "AGENT",
                        "o2r.relay.mode": "reject",
                        "o2r.relay.reject_reason": violation,
                        "o2r.relay.failure_class": _classify_relay_reject(violation),
                        "o2r.peer.target": target_id or "",
                        "o2r.peer.target_role": peer_roles.get(target_id or "") or "",
                        "o2r.peer.sender_role": peer_roles.get(sender_id) or "",
                        "graph.node.id": RELAY_AGENT_ID,
                        "graph.node.parent_id": sender_id,
                    },
                ) as span,
            ):
                span.set_status(Status(StatusCode.ERROR, violation))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32010, "message": violation},
            }

    parts = message.get("parts") or []
    input_text = next(
        (p.get("text", "") for p in parts if p.get("kind") == "text"),
        "",
    )

    incoming_ctx = extract(headers or {})

    with (
        using_session(context_id),
        using_user(sender_id),
        tracer.start_as_current_span(
            "a2a.task",
            context=incoming_ctx,
            kind=SpanKind.SERVER,
            attributes={
                "session.id": context_id,
                "user.id": sender_id,
                "o2r.task.id": task_id,
                "agent.id": RELAY_AGENT_ID,
                "agent.name": RELAY_AGENT_NAME,
                "agent.role": RELAY_ROLE,
                "openinference.span.kind": "AGENT",
                "graph.node.id": RELAY_AGENT_ID,
                "graph.node.parent_id": sender_id,
                "o2r.task.state": "working",
                "o2r.peer.target": target_id or "",
                "o2r.peer.target_role": peer_roles.get(target_id or "") or "",
                "o2r.peer.sender_role": peer_roles.get(sender_id) or "",
                "o2r.relay.mode": "forward" if peer_url else "synthesize",
                "input.value": json.dumps({"role": message.get("role", "user"), "parts": parts}),
                "input.mime_type": "application/json",
                "o2r.message.text": input_text,
            },
        ) as span,
    ):
        span.add_event(
            "o2r.task.state_change",
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
                    "user.id": sender_id,
                    "o2r.task.id": task_id,
                    "agent.id": RELAY_AGENT_ID,
                    "agent.role": RELAY_ROLE,
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
                forward_error: str | None = None
                body = {}
                try:
                    try:
                        resp = client.post(peer_url, json=forward_payload, headers=outgoing_headers)
                        fwd.set_attribute("http.status_code", resp.status_code)
                        try:
                            body = resp.json()
                        except json.JSONDecodeError:
                            forward_error = (
                                f"peer returned non-JSON body ({resp.status_code}, "
                                f"{len(resp.content)} bytes)"
                            )
                    except httpx.HTTPError as e:
                        forward_error = f"forward to {target_id or '?'} failed: {e}"
                        fwd.set_status(Status(StatusCode.ERROR, forward_error))
                finally:
                    if close_after:
                        client.close()
            if forward_error is not None:
                # Peer crashed mid-handle or unreachable. Surface as JSON-RPC error
                # so the originating caller can record an outcome instead of 500ing.
                span.set_attribute("o2r.task.state", "failed")
                span.set_attribute("o2r.relay.failure_class", _classify_relay_reject(forward_error))
                span.set_status(Status(StatusCode.ERROR, forward_error))
                span.add_event(
                    "o2r.task.state_change",
                    attributes={"from": "working", "to": "failed"},
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32011, "message": forward_error},
                }
            if "error" in body:
                span.set_attribute("o2r.task.state", "failed")
                span.set_attribute("o2r.relay.failure_class", "peer_jsonrpc_error")
                span.set_status(Status(StatusCode.ERROR, str(body["error"])))
                span.add_event(
                    "o2r.task.state_change",
                    attributes={"from": "working", "to": "failed"},
                )
                return {"jsonrpc": "2.0", "id": req_id, "error": body["error"]}
            result = body.get("result") or _synthesize_task(message)
        else:
            result = _synthesize_task(message)

        span.add_event(
            "o2r.task.state_change",
            attributes={"from": "working", "to": "completed"},
        )
        span.set_attribute("o2r.task.state", "completed")
        span.set_status(Status(StatusCode.OK))
        store.put(result)

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def handle_message_stream(
    tracer: Tracer,
    payload: dict[str, Any],
    peers: dict[str, str],
    store: TaskStore,
    http_client: httpx.Client | None,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Forward `message/stream` to a peer as SSE; pass-through chunks to caller.

    If no peer is configured for the target, synthesize a minimal one-event
    completed stream so the dogfood works without a peer.
    """
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
    input_text = next((p.get("text", "") for p in parts if p.get("kind") == "text"), "")
    incoming_ctx = extract(headers or {})

    def _emit_synthetic() -> Iterator[bytes]:
        evt = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "kind": "status-update",
                "taskId": task_id,
                "contextId": context_id,
                "status": {"state": "completed", "timestamp": _now_iso()},
                "final": True,
            },
        }
        yield f"data: {json.dumps(evt)}\n\n".encode()

    def gen() -> Iterator[bytes]:
        with (
            using_session(context_id),
            using_user(sender_id),
            tracer.start_as_current_span(
                "a2a.task",
                context=incoming_ctx,
                kind=SpanKind.SERVER,
                attributes={
                    "session.id": context_id,
                    "user.id": sender_id,
                    "o2r.task.id": task_id,
                    "agent.id": RELAY_AGENT_ID,
                    "agent.name": RELAY_AGENT_NAME,
                    "agent.role": RELAY_ROLE,
                    "openinference.span.kind": "AGENT",
                    "graph.node.id": RELAY_AGENT_ID,
                    "graph.node.parent_id": sender_id,
                    "o2r.task.state": "working",
                    "o2r.peer.target": target_id or "",
                    "o2r.relay.mode": "forward-stream" if peer_url else "synthesize-stream",
                    "o2r.method": "message/stream",
                    "input.value": json.dumps(
                        {"role": message.get("role", "user"), "parts": parts}
                    ),
                    "input.mime_type": "application/json",
                    "o2r.message.text": input_text,
                },
            ) as span,
        ):
            span.add_event(
                "o2r.task.state_change",
                attributes={"from": "submitted", "to": "working"},
            )

            if not peer_url:
                yield from _emit_synthetic()
                span.add_event(
                    "o2r.task.state_change",
                    attributes={"from": "working", "to": "completed"},
                )
                span.set_attribute("o2r.task.state", "completed")
                span.set_status(Status(StatusCode.OK))
                return

            outgoing_headers: dict[str, str] = {}
            inject(outgoing_headers)
            with tracer.start_as_current_span(
                "a2a.relay.forward",
                kind=SpanKind.CLIENT,
                attributes={
                    "session.id": context_id,
                    "user.id": sender_id,
                    "o2r.task.id": task_id,
                    "agent.id": RELAY_AGENT_ID,
                    "agent.role": RELAY_ROLE,
                    "graph.node.id": RELAY_AGENT_ID,
                    "peer.agent.id": target_id or "",
                    "peer.url": peer_url,
                    "openinference.span.kind": "AGENT",
                    "rpc.system": "jsonrpc",
                    "rpc.service": "a2a",
                    "rpc.method": "message/stream",
                },
            ):
                client = http_client or httpx.Client(timeout=60.0)
                close_after = http_client is None
                seq = 0
                try:
                    with client.stream(
                        "POST",
                        peer_url,
                        json={
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "message/stream",
                            "params": params,
                        },
                        headers=outgoing_headers,
                    ) as r:
                        for line in r.iter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            try:
                                evt = json.loads(line[len("data: ") :])
                            except json.JSONDecodeError:
                                continue
                            result = evt.get("result") or {}
                            kind = result.get("kind", "")
                            if kind == "artifact-update":
                                artifact = result.get("artifact") or {}
                                first_part = (artifact.get("parts") or [{}])[0]
                                span.add_event(
                                    "a2a.message.stream_chunk",
                                    attributes={
                                        "seq": seq,
                                        "message.role": "agent",
                                        "final": bool(result.get("lastChunk")),
                                        "parts": json.dumps(artifact.get("parts") or []),
                                        "text": first_part.get("text", ""),
                                    },
                                )
                                seq += 1
                            yield (line + "\n\n").encode()
                finally:
                    if close_after:
                        client.close()

            span.add_event(
                "o2r.task.state_change",
                attributes={"from": "working", "to": "completed"},
            )
            span.set_attribute("o2r.task.state", "completed")
            span.set_status(Status(StatusCode.OK))

            # The relay didn't observe a full Task object on the streaming path,
            # so we record a minimal entry so /tasks lists it.
            store.put(
                {
                    "id": task_id,
                    "contextId": context_id,
                    "kind": "task",
                    "status": {"state": "completed", "timestamp": _now_iso()},
                    "history": [message] if message else [],
                    "via": "stream",
                }
            )

    return StreamingResponse(gen(), media_type="text/event-stream")


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
    ctx_id = task.get("contextId", "")
    with (
        using_session(ctx_id),
        tracer.start_as_current_span(
            "a2a.task.cancel",
            kind=SpanKind.SERVER,
            attributes={
                "session.id": ctx_id,
                "o2r.task.id": task_id,
                "agent.id": RELAY_AGENT_ID,
                "agent.role": RELAY_ROLE,
                "graph.node.id": RELAY_AGENT_ID,
                "openinference.span.kind": "AGENT",
            },
        ) as span,
    ):
        span.add_event(
            "o2r.task.state_change",
            attributes={"from": prev_state, "to": "canceled"},
        )
    return {"jsonrpc": "2.0", "id": req_id, "result": updated}


def create_app(
    provider: TracerProvider | None = None,
    peers: dict[str, str] | None = None,
    http_client: httpx.Client | None = None,
    store: TaskStore | None = None,
    peer_roles: dict[str, str] | None = None,
    star_enforce: bool | None = None,
) -> FastAPI:
    """Build the FastAPI app. Pass a custom TracerProvider for tests; defaults to OTLP.

    `peers` overrides the env-var registry. `http_client` lets tests stub the
    forwarding HTTP call. `store` is the in-memory task index; default per-app.
    `peer_roles` is the parallel id->role map used by star-topology enforcement.
    `star_enforce` toggles the enforcement; defaults to OTEL_A2A_RELAY_STAR_ENFORCE
    env var, off if unset (legacy dogfood behavior).
    """
    tracer = (provider or make_provider()).get_tracer("o2r")
    if peers is None:
        peers = parse_peers(os.environ.get("OTEL_A2A_RELAY_PEERS"))
    if peer_roles is None:
        peer_roles = {}
    if star_enforce is None:
        star_enforce = os.environ.get("OTEL_A2A_RELAY_STAR_ENFORCE", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    task_store = store or TaskStore()

    app = FastAPI(title="otel-a2a-relay", version=PROTOCOL_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "protocol": PROTOCOL_VERSION,
            "peers": sorted(peers.keys()),
            "star_enforce": star_enforce,
            "roles": dict(peer_roles),
        }

    @app.get("/tasks")
    def list_tasks() -> dict[str, Any]:
        return {"tasks": task_store.all()}

    @app.get("/peers")
    def list_peers() -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for pid, purl in sorted(peers.items()):
            entry: dict[str, Any] = {"id": pid, "url": purl, "role": peer_roles.get(pid)}
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

    @app.post("/peers")
    async def register_peer(request: Request) -> JSONResponse:
        """Register a peer dynamically. Body: {id, url, role}. role must be in KNOWN_ROLES.

        This is relay-management surface, not part of the A2A→OTel protocol.
        See docs/protocol.md.
        """
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)
        pid = body.get("id")
        purl = body.get("url")
        role = body.get("role")
        if not pid or not purl or not role:
            return JSONResponse({"error": "id, url, and role are required"}, status_code=400)
        if role not in KNOWN_ROLES:
            return JSONResponse(
                {"error": f"role must be one of {sorted(KNOWN_ROLES)}", "got": role},
                status_code=400,
            )
        peers[pid] = purl
        peer_roles[pid] = role
        return JSONResponse({"ok": True, "id": pid, "url": purl, "role": role})

    @app.delete("/peers/{peer_id}")
    def deregister_peer(peer_id: str) -> JSONResponse:
        peers.pop(peer_id, None)
        peer_roles.pop(peer_id, None)
        return JSONResponse({"ok": True, "id": peer_id})

    @app.post("/", response_model=None)
    async def jsonrpc(request: Request) -> JSONResponse | StreamingResponse:
        try:
            payload = await request.json()
        except Exception:
            return _jsonrpc_error(None, -32700, "Parse error")

        if payload.get("jsonrpc") != "2.0" or "method" not in payload:
            return _jsonrpc_error(payload.get("id"), -32600, "Invalid Request")

        method = payload["method"]
        req_id = payload.get("id")
        in_headers = dict(request.headers)

        if method == "message/send":
            return JSONResponse(
                handle_message_send(
                    tracer,
                    payload,
                    peers,
                    task_store,
                    http_client,
                    headers=in_headers,
                    peer_roles=peer_roles,
                    star_enforce=star_enforce,
                )
            )
        if method == "message/stream":
            return handle_message_stream(
                tracer,
                payload,
                peers,
                task_store,
                http_client,
                headers=in_headers,
            )
        if method == "tasks/get":
            return JSONResponse(handle_tasks_get(payload, task_store))
        if method == "tasks/cancel":
            return JSONResponse(handle_tasks_cancel(tracer, payload, task_store))

        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    return app
