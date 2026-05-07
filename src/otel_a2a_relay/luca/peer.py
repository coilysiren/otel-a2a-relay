"""Shared A2A peer scaffold for LUCA processes.

Each LUCA role (orchestrator, planner, validator, worker) is an A2A peer
that registers with the relay, accepts `message/send`, emits an `a2a.task`
SERVER span on each receive, and dispatches to a role-specific handler.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openinference.instrumentation import using_session, using_user
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from otel_a2a_relay.luca import _clock
from otel_a2a_relay.luca.messages import LucaEnvelope, parse_envelope
from otel_a2a_relay.tracing import bootstrap

LUCA_NAMESPACE = "luca"
LUCA_DEFAULT_DEPLOYMENT = "demo"

Handler = Callable[[LucaEnvelope, dict[str, Any]], LucaEnvelope]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_agent_card(agent_id: str, role: str, base_url: str) -> dict[str, Any]:
    return {
        "name": f"luca-{agent_id}",
        "description": f"LUCA-flow {role} ({agent_id}). Star-topology peer.",
        "url": base_url,
        "version": "0.1.0",
        "protocolVersion": "0.2.5",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": role,
                "name": role,
                "description": f"LUCA-flow {role} role.",
                "tags": ["luca"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
    }


def create_peer_app(
    *,
    agent_id: str,
    role: str,
    base_url: str,
    handler: Handler,
    tracer: Tracer | None = None,
    specialization: str | None = None,
) -> FastAPI:
    """Build a FastAPI app for one LUCA peer.

    The handler is called with (incoming_envelope, raw_message) and must
    return a LucaEnvelope to send back as the response.

    LUCA is the demo consumer of the o2r protocol. When `tracer` is not
    supplied, this calls `tracing.bootstrap()` with namespace="luca" and
    deployment from `LUCA_DEPLOYMENT` (default "demo"). Tests pass their
    own tracer to keep emission in-process.

    `specialization` is the worker's narrow role (`designer`, `curator`,
    `researcher`, ...). It rides on every span this peer emits as
    `agent.specialization`, alongside the broader `agent.role` (the
    star-topology role: `orchestrator`/`planner`/`validator`/`worker`/...).
    Per-role analysis in Phoenix uses `agent.specialization` for granular
    slicing. Defaults to `role` when not provided.
    """
    if tracer is None:
        tracer = bootstrap(
            namespace=LUCA_NAMESPACE,
            deployment=os.environ.get("LUCA_DEPLOYMENT", LUCA_DEFAULT_DEPLOYMENT),
            product_area=os.environ.get("LUCA_PRODUCT_AREA") or None,
            role=role,
        )
    spec = specialization or role
    app = FastAPI(title=f"luca-{agent_id}")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "agent.id": agent_id, "role": role}

    @app.get("/.well-known/agent.json")
    def card() -> dict[str, Any]:
        return build_agent_card(agent_id, role, base_url)

    @app.post("/", response_model=None)
    async def jsonrpc(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            )
        if payload.get("method") != "message/send":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {payload.get('method')}",
                    },
                }
            )
        params = payload.get("params") or {}
        message = params.get("message") or {}
        ctx = extract(dict(request.headers))
        env = parse_envelope(message)
        context_id = message.get("contextId", "")

        span_attrs = {
            "session.id": context_id,
            "user.id": env.sender or agent_id,
            "o2r.task.id": message.get("taskId", ""),
            "agent.id": agent_id,
            "agent.name": f"luca-{agent_id}",
            "agent.role": role,
            "agent.specialization": spec,
            "openinference.span.kind": "AGENT",
            "graph.node.id": agent_id,
            "graph.node.parent_id": env.sender,
            "o2r.task.state": "working",
            "o2r.method": "message/send",
            "luca.role": role,
            "luca.kind.in": env.kind,
            "luca.step": env.step,
            "luca.task_id": env.task_id,
            "input.value": json.dumps({"role": "user", "human": env.human}),
            "input.mime_type": "application/json",
            "o2r.message.text": env.human,
        }
        with (
            using_session(context_id),
            using_user(env.sender or agent_id),
            tracer.start_as_current_span(
                "a2a.task",
                context=ctx,
                kind=SpanKind.SERVER,
                attributes=span_attrs,
            ) as span,
        ):
            try:
                reply = handler(env, message)
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            span.set_attribute("luca.kind.out", reply.kind)
            span.set_attribute("o2r.message.reply_text", reply.human)
            span.set_attribute(
                "output.value",
                json.dumps({"role": "agent", "human": reply.human}),
            )
            span.set_attribute("output.mime_type", "application/json")
            span.set_attribute("o2r.task.state", "completed")
            span.set_status(Status(StatusCode.OK))

        reply_message = reply.to_message(
            context_id=message.get("contextId", ""),
            a2a_task_id=message.get("taskId"),
            role="agent",
        )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "result": {
                    "id": message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}",
                    "contextId": message.get("contextId", ""),
                    "kind": "task",
                    "status": {"state": "completed", "timestamp": _now_iso()},
                    "history": [message, reply_message],
                },
            }
        )

    return app


def register_with_relay(
    relay_url: str, agent_id: str, role: str, peer_url: str, retries: int = 20
) -> None:
    """POST /peers to the relay. Retries briefly on connection refused."""
    last_err: Exception | None = None
    for _ in range(retries):
        try:
            r = httpx.post(
                relay_url.rstrip("/") + "/peers",
                json={"id": agent_id, "url": peer_url, "role": role},
                timeout=5.0,
            )
            if r.status_code == 200:
                return
            raise RuntimeError(f"register {agent_id}: HTTP {r.status_code} {r.text}")
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            last_err = e
            time.sleep(0.25)
    raise RuntimeError(f"register {agent_id}: relay unreachable at {relay_url} ({last_err})")


def deregister_from_relay(relay_url: str, agent_id: str) -> None:
    try:
        httpx.delete(
            relay_url.rstrip("/") + f"/peers/{agent_id}",
            timeout=2.0,
        )
    except httpx.HTTPError:
        pass  # best-effort on shutdown


def send_via_relay(
    relay_url: str,
    envelope: LucaEnvelope,
    *,
    context_id: str,
    a2a_task_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST a `message/send` JSON-RPC call to the relay. Returns the parsed body.

    The caller passes in a fully-built LucaEnvelope; this helper just wraps it.
    Traceparent is injected so the relay's span attaches to the caller's.
    """
    msg = envelope.to_message(context_id=context_id, a2a_task_id=a2a_task_id)
    payload = {
        "jsonrpc": "2.0",
        "id": f"r-{_clock.hex8()}",
        "method": "message/send",
        "params": {"message": msg},
    }
    headers: dict[str, str] = {}
    inject(headers)
    try:
        r = httpx.post(relay_url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as e:
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "error": {"code": -32012, "message": f"transport error: {e}"},
        }
    try:
        body: dict[str, Any] = r.json()
    except Exception:
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "error": {
                "code": -32013,
                "message": f"non-JSON relay response: HTTP {r.status_code}",
            },
        }
    return body


def serve_in_thread(app: FastAPI, *, host: str, port: int) -> threading.Thread:
    """Run uvicorn in a daemon thread. Used by the runner for in-process peers."""

    def _run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)

    t = threading.Thread(target=_run, daemon=True, name=f"luca-peer-{port}")
    t.start()
    return t
