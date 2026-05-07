"""Tiny CLI client for the dogfood loop.

Two subcommands:

- `send`: build a JSON-RPC `message/send` envelope and POST it to a running
  relay. Reads `AS`, `CTX`, `MSG`, `OTEL_A2A_RELAY_URL` from env.
- `view`: query Phoenix for spans tagged with `session.id == $CTX`, sort by
  start time, and print one line per span plus indented event lines for the
  span events that carry routing fields. Reads `CTX`, `PHOENIX_URL`.

Both are intentionally thin so the dogfood loop is just `make send` /
`make view` from a shell.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

import httpx
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind, Status, StatusCode

from otel_a2a_relay.phoenix import DEFAULT_PHOENIX_URL
from otel_a2a_relay.phoenix import attrs as _attrs
from otel_a2a_relay.phoenix import fetch_spans as _fetch_spans
from otel_a2a_relay.phoenix import flatten as _flatten
from otel_a2a_relay.telemetry import make_provider

DEFAULT_RELAY_URL = "http://127.0.0.1:8080/"

EVENT_FIELDS = ("from", "to", "seq", "final")

__all__ = (
    "DEFAULT_PHOENIX_URL",
    "_attrs",
    "_fetch_spans",
    "_flatten",
)


def _env(name: str, required: bool = True, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        print(f"missing env: {name}", file=sys.stderr)
        sys.exit(2)
    return val or ""


def cmd_send() -> int:
    agent_id = _env("AS")
    context_id = _env("CTX")
    msg = _env("MSG")
    target = os.environ.get("TO") or ""
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL)

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    message_id = f"m-{uuid.uuid4().hex[:8]}"
    metadata: dict[str, Any] = {"agent.id": agent_id}
    if target:
        metadata["agent.target"] = target
    envelope = {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": message_id,
                "taskId": task_id,
                "contextId": context_id,
                "role": "user",
                "parts": [{"kind": "text", "text": msg}],
                "metadata": metadata,
            }
        },
    }

    provider = make_provider()
    tracer = provider.get_tracer(f"o2r.client.{agent_id}")
    body: dict[str, Any] = {}
    try:
        with tracer.start_as_current_span(
            "a2a.client.send",
            kind=SpanKind.CLIENT,
            attributes={
                "session.id": context_id,
                "o2r.task.id": task_id,
                "agent.id": agent_id,
                "agent.name": f"{agent_id}-client",
                "openinference.span.kind": "AGENT",
                "graph.node.id": agent_id,
                "peer.agent.id": target,
                "o2r.method": "message/send",
                "rpc.system": "jsonrpc",
                "rpc.service": "a2a",
                "rpc.method": "message/send",
                "input.value": json.dumps(
                    {"role": "user", "parts": [{"kind": "text", "text": msg}]}
                ),
                "input.mime_type": "application/json",
                "o2r.message.text": msg,
            },
        ) as span:
            headers: dict[str, str] = {}
            inject(headers)
            try:
                resp = httpx.post(url, json=envelope, headers=headers, timeout=10.0)
            except httpx.HTTPError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                print(f"[{agent_id}] relay unreachable at {url}: {e}", file=sys.stderr)
                return 1
            body = resp.json()
            span.set_attribute("http.status_code", resp.status_code)
            if "error" in body:
                span.set_status(Status(StatusCode.ERROR, str(body["error"])))
            else:
                span.set_status(Status(StatusCode.OK))
    finally:
        provider.shutdown()

    if "error" in body:
        print(f"[{agent_id}] error: {body['error']}", file=sys.stderr)
        return 1
    state = (body.get("result") or {}).get("status", {}).get("state", "?")
    arrow = f"-> {target} " if target else ""
    print(f"[{agent_id}] sent {arrow}task={task_id} state={state}")
    return 0


def cmd_view() -> int:
    context_id = _env("CTX")
    phoenix_url = os.environ.get("PHOENIX_URL", DEFAULT_PHOENIX_URL)

    spans: list[dict[str, Any]] = []
    for attempt in range(2):
        try:
            all_spans = _fetch_spans(phoenix_url)
        except (httpx.HTTPError, RuntimeError) as e:
            print(f"phoenix query failed at {phoenix_url}: {e}", file=sys.stderr)
            return 1
        spans = [s for s in all_spans if _attrs(s).get("session.id") == context_id]
        if spans or attempt == 1:
            break
        time.sleep(0.5)

    if not spans:
        print(f"no spans for session.id={context_id}")
        return 0

    spans.sort(key=lambda s: s.get("startTime") or "")

    for s in spans:
        a = _attrs(s)
        agent = a.get("agent.id", "?")
        parent = a.get("graph.node.parent_id", "")
        kind = a.get("openinference.span.kind", s.get("spanKind", ""))
        task = a.get("o2r.task.id", "?")
        state = a.get("o2r.task.state", "")
        chain = f"{parent}->{agent}" if parent else agent
        suffix = f" state={state}" if state else ""
        print(f"[{chain}] {s.get('name')} task={task} kind={kind}{suffix}")
        in_text = a.get("o2r.message.text")
        if in_text:
            print(f"  in: {in_text}")
        out_text = a.get("o2r.message.reply_text")
        if out_text:
            print(f"  out: {out_text}")
        for ev in s.get("events") or []:
            ev_attrs = _attrs(ev)
            keep = {k: v for k, v in ev_attrs.items() if k in EVENT_FIELDS}
            if keep:
                pretty = " ".join(f"{k}={v}" for k, v in keep.items())
                print(f"  - {ev.get('name')}: {pretty}")
    return 0


def cmd_stream() -> int:
    agent_id = _env("AS")
    context_id = _env("CTX")
    msg = _env("MSG")
    target = os.environ.get("TO") or ""
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL)

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    message_id = f"m-{uuid.uuid4().hex[:8]}"
    metadata: dict[str, Any] = {"agent.id": agent_id}
    if target:
        metadata["agent.target"] = target
    envelope = {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": "message/stream",
        "params": {
            "message": {
                "messageId": message_id,
                "taskId": task_id,
                "contextId": context_id,
                "role": "user",
                "parts": [{"kind": "text", "text": msg}],
                "metadata": metadata,
            }
        },
    }

    provider = make_provider()
    tracer = provider.get_tracer(f"o2r.client.{agent_id}")
    arrow = f"-> {target} " if target else ""
    print(f"[{agent_id}] streaming {arrow}task={task_id}")
    try:
        with tracer.start_as_current_span(
            "a2a.client.stream",
            kind=SpanKind.CLIENT,
            attributes={
                "session.id": context_id,
                "o2r.task.id": task_id,
                "agent.id": agent_id,
                "openinference.span.kind": "AGENT",
                "graph.node.id": agent_id,
                "peer.agent.id": target,
                "o2r.method": "message/stream",
                "rpc.system": "jsonrpc",
                "rpc.service": "a2a",
                "rpc.method": "message/stream",
                "o2r.message.text": msg,
            },
        ) as span:
            headers: dict[str, str] = {}
            inject(headers)
            try:
                with httpx.stream("POST", url, json=envelope, headers=headers, timeout=60.0) as r:
                    for line in r.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        try:
                            evt = json.loads(line[len("data: ") :])
                        except json.JSONDecodeError:
                            continue
                        res = evt.get("result") or {}
                        kind = res.get("kind", "?")
                        if kind == "artifact-update":
                            artifact = res.get("artifact") or {}
                            text = (artifact.get("parts") or [{}])[0].get("text", "")
                            sys.stdout.write(text)
                            sys.stdout.flush()
                        elif kind == "status-update":
                            state = (res.get("status") or {}).get("state", "")
                            final = res.get("final")
                            if final:
                                print(f"\n[{agent_id}] stream done state={state}")
            except httpx.HTTPError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                print(f"[{agent_id}] relay unreachable at {url}: {e}", file=sys.stderr)
                return 1
            span.set_status(Status(StatusCode.OK))
    finally:
        provider.shutdown()
    return 0


def cmd_gif() -> int:
    """Render a session's spans as an animated topology GIF.

    Reads `CTX` (session id) and optional `OUT` (output path), pulls the
    session from Phoenix, and writes a GIF that animates each hop in
    start-time order. The viz module is an optional dependency; we
    surface a clear install hint if Pillow is missing rather than a
    raw ImportError.
    """
    context_id = _env("CTX")
    phoenix_url = os.environ.get("PHOENIX_URL", DEFAULT_PHOENIX_URL)
    out_env = os.environ.get("OUT") or ""
    out_path = (
        os.path.abspath(out_env)
        if out_env
        else os.path.abspath(f"assets/sessions/{context_id}.gif")
    )

    try:
        from otel_a2a_relay.viz import render_session
    except ImportError as e:  # pragma: no cover - guarded by viz extra
        print(
            f"viz extra not installed: {e}\n  install with: uv sync --extra viz",
            file=sys.stderr,
        )
        return 2

    try:
        all_spans = _fetch_spans(phoenix_url)
    except (httpx.HTTPError, RuntimeError) as e:
        print(f"phoenix query failed at {phoenix_url}: {e}", file=sys.stderr)
        return 1
    spans = [s for s in all_spans if _attrs(s).get("session.id") == context_id]
    if not spans:
        print(f"no spans for session.id={context_id}", file=sys.stderr)
        return 1
    spans.sort(key=lambda s: (s.get("startTime") or "", s.get("name") or ""))

    from pathlib import Path as _Path

    try:
        session = render_session(spans, context_id, _Path(out_path))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(
        f"wrote {out_path}  hub={session.hub}  leaves={len(session.leaves)}  "
        f"hops={len(session.hops)}  spans={session.span_count}  "
        f"duration={session.duration_s:.2f}s"
    )
    return 0


def cmd_get() -> int:
    """tasks/get against the relay; prints the JSON Task back."""
    task_id = _env("TASK")
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL)
    envelope = {
        "jsonrpc": "2.0",
        "id": f"g-{uuid.uuid4().hex[:6]}",
        "method": "tasks/get",
        "params": {"id": task_id},
    }
    try:
        resp = httpx.post(url, json=envelope, timeout=10.0)
    except httpx.HTTPError as e:
        print(f"relay unreachable at {url}: {e}", file=sys.stderr)
        return 1
    body = resp.json()
    if "error" in body:
        print(f"error: {body['error']}", file=sys.stderr)
        return 1
    print(json.dumps(body.get("result"), indent=2))
    return 0


def cmd_tasks() -> int:
    """List tasks the relay has observed."""
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL).rstrip("/") + "/tasks"
    try:
        resp = httpx.get(url, timeout=10.0)
    except httpx.HTTPError as e:
        print(f"relay unreachable at {url}: {e}", file=sys.stderr)
        return 1
    tasks = resp.json().get("tasks") or []
    if not tasks:
        print("(no tasks)")
        return 0
    for t in tasks:
        state = t.get("status", {}).get("state", "?")
        print(f"{t.get('id')} ctx={t.get('contextId')} state={state}")
    return 0


def cmd_peers() -> int:
    """List peers the relay knows about, with their agent cards."""
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL).rstrip("/") + "/peers"
    try:
        resp = httpx.get(url, timeout=5.0)
    except httpx.HTTPError as e:
        print(f"relay unreachable at {url}: {e}", file=sys.stderr)
        return 1
    peers = resp.json().get("peers") or []
    if not peers:
        print("(no peers configured)")
        return 0
    for p in peers:
        card = p.get("card") or {}
        skills = ", ".join(s.get("id", "?") for s in card.get("skills") or [])
        proto = card.get("protocolVersion", "?")
        if "card_error" in p:
            print(f"{p['id']} {p['url']}  error={p['card_error']}")
        else:
            print(
                f"{p['id']} {p['url']}  proto={proto} "
                f"name={card.get('name', '?')} skills=[{skills}]"
            )
    return 0


def cmd_cancel() -> int:
    task_id = _env("TASK")
    url = os.environ.get("OTEL_A2A_RELAY_URL", DEFAULT_RELAY_URL)
    envelope = {
        "jsonrpc": "2.0",
        "id": f"c-{uuid.uuid4().hex[:6]}",
        "method": "tasks/cancel",
        "params": {"id": task_id},
    }
    try:
        resp = httpx.post(url, json=envelope, timeout=10.0)
    except httpx.HTTPError as e:
        print(f"relay unreachable at {url}: {e}", file=sys.stderr)
        return 1
    body = resp.json()
    if "error" in body:
        print(f"error: {body['error']}", file=sys.stderr)
        return 1
    state = (body.get("result") or {}).get("status", {}).get("state", "?")
    print(f"task={task_id} state={state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(
            "usage: python -m otel_a2a_relay.client {send|view|get|tasks|cancel}",
            file=sys.stderr,
        )
        return 2
    verb = argv[0]
    handlers = {
        "send": cmd_send,
        "stream": cmd_stream,
        "view": cmd_view,
        "gif": cmd_gif,
        "get": cmd_get,
        "tasks": cmd_tasks,
        "cancel": cmd_cancel,
        "peers": cmd_peers,
    }
    handler = handlers.get(verb)
    if not handler:
        print(f"unknown subcommand: {verb}", file=sys.stderr)
        return 2
    return handler()


if __name__ == "__main__":
    sys.exit(main())
