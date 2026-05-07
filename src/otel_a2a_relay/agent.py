"""Tiny A2A peer agent.

Stands up a FastAPI server that speaks just enough of A2A to participate
in a two-agent dogfood. Receives `message/send`, emits its own `a2a.task`
span (kind=SERVER, agent.id from CLI), and replies with a Task that
includes an echo response in its history.

W3C traceparent headers are honored on incoming requests so the agent's
span becomes a child of the relay's forwarding span.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openinference.instrumentation import using_session, using_user
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

from otel_a2a_relay.store import TaskStore
from otel_a2a_relay.telemetry import make_provider

DEFAULT_AGENT_ROLE = "echo"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _jsonrpc_error(req_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    )


def _sse(obj: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


def build_agent_card(agent_id: str, name: str, base_url: str) -> dict[str, Any]:
    """A2A AgentCard for this echo agent. Loosely follows the public A2A spec.

    Only fields meaningful for the dogfood are populated. Anything we don't
    actually support (push notifications, auth) is omitted rather than lied
    about.
    """
    return {
        "name": name,
        "description": (
            f"Echo agent {agent_id}. Replies to text messages with 'echo from {agent_id}: <input>'."
        ),
        "url": base_url,
        "version": "0.1.0",
        "protocolVersion": "0.2.5",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "echo",
                "name": "echo",
                "description": "Echoes back any text message with the agent id prefix.",
                "tags": ["dogfood"],
                "examples": ["hello", "ping"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
    }


def create_app(
    agent_id: str,
    agent_name: str | None = None,
    provider: TracerProvider | None = None,
    store: TaskStore | None = None,
    base_url: str | None = None,
) -> FastAPI:
    tracer = (provider or make_provider()).get_tracer(f"o2r.agent.{agent_id}")
    name = agent_name or f"{agent_id}-echo-agent"
    task_store = store or TaskStore()
    self_url = base_url or "http://127.0.0.1/"
    app = FastAPI(title=f"a2a-agent-{agent_id}")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "agent.id": agent_id}

    @app.get("/.well-known/agent.json")
    def agent_card() -> dict[str, Any]:
        return build_agent_card(agent_id, name, self_url)

    @app.get("/tasks")
    def list_tasks() -> dict[str, Any]:
        return {"tasks": task_store.all()}

    def _handle_tasks_get(payload: dict[str, Any]) -> JSONResponse:
        params = payload.get("params") or {}
        req_id = payload.get("id")
        task_id = params.get("id") or params.get("taskId")
        if not task_id:
            return _jsonrpc_error(req_id, -32602, "Missing task id")
        task = task_store.get(task_id)
        if not task:
            return _jsonrpc_error(req_id, -32001, f"Unknown task: {task_id}")
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": task})

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

        if method == "tasks/get":
            return _handle_tasks_get(payload)
        if method == "message/send":
            return _do_send(request, payload)
        if method == "message/stream":
            return _do_stream(request, payload)
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    def _extract_text(message: dict[str, Any]) -> str:
        for part in message.get("parts") or []:
            if part.get("kind") == "text":
                return part.get("text", "") or ""
        return ""

    def _reply_message(text: str, task_id: str, context_id: str) -> tuple[str, dict[str, Any]]:
        reply_text = f"echo from {agent_id}: {text}" if text else f"ack from {agent_id}"
        return reply_text, {
            "messageId": f"m-{uuid.uuid4().hex[:8]}",
            "taskId": task_id,
            "contextId": context_id,
            "role": "agent",
            "parts": [{"kind": "text", "text": reply_text}],
            "metadata": {"agent.id": agent_id},
        }

    def _do_send(request: Request, payload: dict[str, Any]) -> JSONResponse:
        params = payload.get("params") or {}
        req_id = payload.get("id")
        ctx = extract(dict(request.headers))
        message = params.get("message") or {}
        context_id = message.get("contextId") or str(uuid.uuid4())
        task_id = message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}"
        sender_id = (message.get("metadata") or {}).get("agent.id", "unknown")
        text = _extract_text(message)

        with (
            using_session(context_id),
            using_user(sender_id),
            tracer.start_as_current_span(
                "a2a.task",
                context=ctx,
                kind=SpanKind.SERVER,
                attributes={
                    "session.id": context_id,
                    "user.id": sender_id,
                    "o2r.task.id": task_id,
                    "agent.id": agent_id,
                    "agent.name": name,
                    "agent.role": DEFAULT_AGENT_ROLE,
                    "openinference.span.kind": "AGENT",
                    "graph.node.id": agent_id,
                    "graph.node.parent_id": sender_id,
                    "o2r.task.state": "working",
                    "o2r.method": "message/send",
                    "input.value": json.dumps(
                        {"role": message.get("role", "user"), "parts": message.get("parts") or []}
                    ),
                    "input.mime_type": "application/json",
                    "o2r.message.text": text,
                },
            ) as span,
        ):
            span.add_event(
                "o2r.task.state_change",
                attributes={"from": "submitted", "to": "working"},
            )
            reply_text, reply_message = _reply_message(text, task_id, context_id)
            span.add_event(
                "a2a.message.stream_chunk",
                attributes={"seq": 0, "message.role": "agent", "final": True},
            )
            span.add_event(
                "o2r.task.state_change",
                attributes={"from": "working", "to": "completed"},
            )
            span.set_attribute("o2r.task.state", "completed")
            span.set_attribute(
                "output.value",
                json.dumps({"role": "agent", "parts": reply_message["parts"]}),
            )
            span.set_attribute("output.mime_type", "application/json")
            span.set_attribute("o2r.message.reply_text", reply_text)
            span.set_status(Status(StatusCode.OK))

        result = {
            "id": task_id,
            "contextId": context_id,
            "kind": "task",
            "status": {"state": "completed", "timestamp": _now_iso()},
            "history": [message, reply_message] if message else [reply_message],
        }
        task_store.put(result)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _do_stream(request: Request, payload: dict[str, Any]) -> StreamingResponse:
        params = payload.get("params") or {}
        req_id = payload.get("id")
        headers_in = dict(request.headers)
        message = params.get("message") or {}
        context_id = message.get("contextId") or str(uuid.uuid4())
        task_id = message.get("taskId") or f"task-{uuid.uuid4().hex[:8]}"
        sender_id = (message.get("metadata") or {}).get("agent.id", "unknown")
        text = _extract_text(message)

        def gen() -> Iterator[bytes]:
            ctx = extract(headers_in)
            with (
                using_session(context_id),
                using_user(sender_id),
                tracer.start_as_current_span(
                    "a2a.task",
                    context=ctx,
                    kind=SpanKind.SERVER,
                    attributes={
                        "session.id": context_id,
                        "user.id": sender_id,
                        "o2r.task.id": task_id,
                        "agent.id": agent_id,
                        "agent.name": name,
                        "agent.role": DEFAULT_AGENT_ROLE,
                        "openinference.span.kind": "AGENT",
                        "graph.node.id": agent_id,
                        "graph.node.parent_id": sender_id,
                        "o2r.task.state": "working",
                        "o2r.method": "message/stream",
                        "input.value": json.dumps(
                            {
                                "role": message.get("role", "user"),
                                "parts": message.get("parts") or [],
                            }
                        ),
                        "input.mime_type": "application/json",
                        "o2r.message.text": text,
                    },
                ) as span,
            ):
                span.add_event(
                    "o2r.task.state_change",
                    attributes={"from": "submitted", "to": "working"},
                )
                # Status event: working.
                yield _sse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "kind": "status-update",
                            "taskId": task_id,
                            "contextId": context_id,
                            "status": {
                                "state": "working",
                                "timestamp": _now_iso(),
                            },
                            "final": False,
                        },
                    }
                )

                reply_text, _reply = _reply_message(text, task_id, context_id)
                tokens = reply_text.split(" ")
                for seq, token in enumerate(tokens):
                    is_final = seq == len(tokens) - 1
                    chunk_part = token + ("" if is_final else " ")
                    span.add_event(
                        "a2a.message.stream_chunk",
                        attributes={
                            "seq": seq,
                            "message.role": "agent",
                            "final": is_final,
                            "parts": json.dumps([{"kind": "text", "text": chunk_part}]),
                        },
                    )
                    yield _sse(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "kind": "artifact-update",
                                "taskId": task_id,
                                "contextId": context_id,
                                "artifact": {
                                    "artifactId": f"a-{seq}",
                                    "parts": [{"kind": "text", "text": chunk_part}],
                                },
                                "lastChunk": is_final,
                            },
                        }
                    )
                    time.sleep(0.05)

                span.add_event(
                    "o2r.task.state_change",
                    attributes={"from": "working", "to": "completed"},
                )
                span.set_attribute("o2r.task.state", "completed")
                span.set_attribute(
                    "output.value",
                    json.dumps({"role": "agent", "parts": [{"kind": "text", "text": reply_text}]}),
                )
                span.set_attribute("output.mime_type", "application/json")
                span.set_attribute("o2r.message.reply_text", reply_text)
                span.set_status(Status(StatusCode.OK))

                # Final status event.
                yield _sse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "kind": "status-update",
                            "taskId": task_id,
                            "contextId": context_id,
                            "status": {
                                "state": "completed",
                                "timestamp": _now_iso(),
                            },
                            "final": True,
                        },
                    }
                )

                result = {
                    "id": task_id,
                    "contextId": context_id,
                    "kind": "task",
                    "status": {"state": "completed", "timestamp": _now_iso()},
                    "history": [message],
                }
                task_store.put(result)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="A2A peer agent (echo).")
    parser.add_argument("--id", required=True, help="agent.id (e.g. A, B)")
    parser.add_argument("--name", default=None, help="agent.name (default <id>-echo-agent)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    app = create_app(args.id, args.name, base_url=base_url)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
