"""Tempo-side harness: post the worked-example trace, wait for it to land.

Mirror of `otel_a2a_relay_arize_phoenix.harness` but pointed at Tempo. The
harness is a single-process probe that:

  1. Bootstraps a tracer pointed at Tempo's OTLP/HTTP endpoint.
  2. Emits the three-trace worked example (A streams to B, B works, A
     acks). Same shape as the Phoenix harness so visual diffs across
     backends are apples-to-apples.
  3. Polls Tempo's search API until the spans show up.
  4. Prints a Grafana Explore link the operator can click.

Usage::

    uv run --package otel-a2a-relay-tempo-grafana o2r-tempo-harness
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run o2r-tempo-harness
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from urllib.parse import quote

import httpx
from opentelemetry.trace import SpanKind, Status, StatusCode

from otel_a2a_relay_tempo_grafana.bootstrap import (
    DEFAULT_GRAFANA_URL,
    DEFAULT_TEMPO_OTLP_ENDPOINT,
    DEFAULT_TEMPO_QUERY_URL,
    bootstrap_tempo,
)

REPO = "coilysiren/otel-a2a-relay"
ISSUE = 1
SESSION_ID = hashlib.sha256(f"{REPO}#{ISSUE}".encode()).hexdigest()[:16]
TASK_ID = "task-validate-001"

AGENTS = {
    "A": {"agent.id": "A", "agent.name": "alpha-agent", "agent.version": "0.1.0"},
    "B": {"agent.id": "B", "agent.name": "beta-agent", "agent.version": "0.1.0"},
}


def _base_attrs(acting_agent: str) -> dict[str, str]:
    return {
        "session.id": SESSION_ID,
        "o2r.task.id": TASK_ID,
        **AGENTS[acting_agent],
    }


def _emit_worked_example() -> None:
    """Emit the same three-trace worked example as the Phoenix harness.

    Identical shape on both backends so cross-backend diffing is a drop-in.
    """
    tracer = bootstrap_tempo(
        namespace="o2r",
        deployment="harness",
        role="harness",
    )

    # Trace 1: A's outgoing burst.
    with tracer.start_as_current_span(
        "a2a.client.send",
        kind=SpanKind.CLIENT,
        attributes={
            **_base_attrs("A"),
            "agent.role": "harness",
            "openinference.span.kind": "AGENT",
            "graph.node.id": "A",
            "peer.agent.id": "B",
            "o2r.method": "message/stream",
            "rpc.system": "jsonrpc",
            "rpc.service": "a2a",
            "rpc.method": "message/stream",
        },
    ):
        with tracer.start_as_current_span(
            "a2a.message.send",
            attributes={
                **_base_attrs("A"),
                "agent.role": "harness",
                "openinference.span.kind": "LLM",
                "input.value": json.dumps(
                    {
                        "role": "user",
                        "parts": [{"kind": "text", "text": "summarize the design doc"}],
                    }
                ),
                "input.mime_type": "application/json",
            },
        ):
            pass

    # Trace 2: B's task execution.
    with tracer.start_as_current_span(
        "a2a.task",
        kind=SpanKind.SERVER,
        attributes={
            **_base_attrs("B"),
            "agent.role": "harness",
            "openinference.span.kind": "AGENT",
            "graph.node.id": "B",
            "graph.node.parent_id": "A",
            "o2r.task.state": "working",
        },
    ) as task_span:
        task_span.add_event(
            "o2r.task.state_change",
            attributes={"from": "submitted", "to": "working"},
        )
        chunks = [
            ("The design doc proposes ", False),
            ("an A2A relay backed by OTel spans, ", False),
            ("validated against Tempo + Grafana.", True),
        ]
        for seq, (text, final) in enumerate(chunks):
            task_span.add_event(
                "a2a.message.stream_chunk",
                attributes={
                    "seq": seq,
                    "message.role": "agent",
                    "parts": json.dumps([{"kind": "text", "text": text}]),
                    "final": final,
                },
            )
            time.sleep(0.01)
        task_span.add_event(
            "o2r.task.state_change",
            attributes={"from": "working", "to": "completed"},
        )
        with tracer.start_as_current_span(
            "a2a.message.send",
            attributes={
                **_base_attrs("B"),
                "agent.role": "harness",
                "openinference.span.kind": "LLM",
                "output.value": json.dumps(
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "".join(c[0] for c in chunks)}],
                    }
                ),
                "output.mime_type": "application/json",
            },
        ):
            pass
        task_span.set_attribute("o2r.task.state", "completed")
        task_span.set_status(Status(StatusCode.OK))

    # Trace 3: A's read.
    with tracer.start_as_current_span(
        "a2a.client.recv",
        kind=SpanKind.CLIENT,
        attributes={
            **_base_attrs("A"),
            "agent.role": "harness",
            "openinference.span.kind": "AGENT",
            "graph.node.id": "A",
            "graph.node.parent_id": "B",
            "o2r.method": "tasks/get",
        },
    ):
        pass


def _wait_for_tempo(query_url: str, *, timeout: float = 30.0) -> dict[str, object] | None:
    """Poll Tempo's search API until the harness session shows up."""
    deadline = time.time() + timeout
    encoded = quote(f'{{ resource.session.id="{SESSION_ID}" }}')
    search_url = f"{query_url.rstrip('/')}/api/search?q={encoded}&limit=10"
    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.get(search_url, timeout=2.0)
            if r.status_code == 200:
                body: dict[str, object] = r.json()
                if body.get("traces"):
                    return body
        except httpx.HTTPError as e:
            last_err = str(e)
        # Fallback: tag-style search (some Tempo versions key off span attrs not resource).
        try:
            tag_url = f"{query_url.rstrip('/')}/api/search?tags=session.id%3D{SESSION_ID}&limit=10"
            r2 = httpx.get(tag_url, timeout=2.0)
            if r2.status_code == 200:
                body2: dict[str, object] = r2.json()
                if body2.get("traces"):
                    return body2
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(0.5)
    if last_err:
        print(f"Tempo poll timed out (last err: {last_err})", file=sys.stderr)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--otlp-endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_TEMPO_OTLP_ENDPOINT),
        help="OTLP/HTTP receiver. Default: Tempo's bundled docker-compose port.",
    )
    p.add_argument("--query-url", default=DEFAULT_TEMPO_QUERY_URL)
    p.add_argument("--grafana-url", default=DEFAULT_GRAFANA_URL)
    p.add_argument("--no-wait", action="store_true", help="Don't poll Tempo after emitting.")
    args = p.parse_args()

    # Make sure the bootstrap helper sees the resolved endpoint.
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = args.otlp_endpoint

    print(f"📡 Tempo OTLP: {args.otlp_endpoint}")
    print(f"  session.id = {SESSION_ID}")
    print(f"  task.id    = {TASK_ID}")
    _emit_worked_example()
    print("Posted 3 traces.")

    if args.no_wait:
        return 0

    print(f"⏳ Polling {args.query_url}/api/search until Tempo indexes the session...")
    body = _wait_for_tempo(args.query_url)
    if not body:
        print("❌ Tempo did not index the spans within the timeout.", file=sys.stderr)
        return 2
    traces_obj = body.get("traces", [])
    traces: list[dict[str, object]] = traces_obj if isinstance(traces_obj, list) else []
    print(f"✅ Tempo indexed {len(traces)} traces for session.id={SESSION_ID}")
    if traces:
        first = traces[0]
        if isinstance(first, dict):
            tid = first.get("traceID", "")
            if tid:
                explore = (
                    f"{args.grafana_url.rstrip('/')}/explore?left=%7B%22datasource%22:%22tempo%22,"
                    f"%22queries%22:%5B%7B%22query%22:%22{tid}%22,%22queryType%22:%22traceql%22%7D%5D%7D"
                )
                print(f"🔭 Open in Grafana: {explore}")
    print(f"📊 LUCA-flow dashboard: {args.grafana_url.rstrip('/')}/d/luca-flow/luca-flow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
