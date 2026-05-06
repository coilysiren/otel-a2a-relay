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

DEFAULT_RELAY_URL = "http://127.0.0.1:8080/"
DEFAULT_PHOENIX_URL = "http://127.0.0.1:6006"

EVENT_FIELDS = ("from", "to", "seq", "final")


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

    try:
        resp = httpx.post(url, json=envelope, timeout=10.0)
    except httpx.HTTPError as e:
        print(f"[{agent_id}] relay unreachable at {url}: {e}", file=sys.stderr)
        return 1

    body = resp.json()
    if "error" in body:
        print(f"[{agent_id}] error: {body['error']}", file=sys.stderr)
        return 1
    state = (body.get("result") or {}).get("status", {}).get("state", "?")
    arrow = f"-> {target} " if target else ""
    print(f"[{agent_id}] sent {arrow}task={task_id} state={state}")
    return 0


GRAPHQL = """
query SpansBySession($limit: Int!) {
  projects(first: 1) {
    edges {
      node {
        spans(first: $limit) {
          edges {
            node {
              name
              spanKind
              startTime
              attributes
              events {
                name
                attributes
              }
            }
          }
        }
      }
    }
  }
}
"""


def _fetch_spans(phoenix_url: str, limit: int = 200) -> list[dict[str, Any]]:
    r = httpx.post(
        f"{phoenix_url.rstrip('/')}/graphql",
        json={"query": GRAPHQL, "variables": {"limit": limit}},
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"graphql errors: {data['errors']}")
    edges = data["data"]["projects"]["edges"]
    if not edges:
        return []
    span_edges = edges[0]["node"]["spans"]["edges"]
    return [e["node"] for e in span_edges]


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    """Phoenix returns attributes as nested objects (dotted keys re-nested).
    Flatten back to dotted keys so callers can ask for `session.id` etc.
    """
    out: dict[str, Any] = {}
    if not isinstance(d, dict):
        return {prefix: d} if prefix else {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    raw = span.get("attributes")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return _flatten(raw or {})


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
        kind = a.get("openinference.span.kind", s.get("spanKind", ""))
        task = a.get("a2a.task.id", "?")
        print(f"[{agent}] {s.get('name')} task={task} kind={kind}")
        for ev in s.get("events") or []:
            ev_attrs = _attrs(ev)
            keep = {k: v for k, v in ev_attrs.items() if k in EVENT_FIELDS}
            if keep:
                pretty = " ".join(f"{k}={v}" for k, v in keep.items())
                print(f"  - {ev.get('name')}: {pretty}")
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
        "view": cmd_view,
        "get": cmd_get,
        "tasks": cmd_tasks,
        "cancel": cmd_cancel,
    }
    handler = handlers.get(verb)
    if not handler:
        print(f"unknown subcommand: {verb}", file=sys.stderr)
        return 2
    return handler()


if __name__ == "__main__":
    sys.exit(main())
