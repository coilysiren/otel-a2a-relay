#!/usr/bin/env python3
"""Phoenix harness for otel-a2a-relay protocol v0.

Posts the worked-example spans (A streams a task to B, B completes, A acks)
via OTLP/HTTP to a local Phoenix and exits. Use this to confirm Phoenix's
Sessions, Agent Graph, and Trace Tree views render the protocol correctly
before writing any relay code.

Usage:
    python post_worked_example.py
    OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix.local:6006 python post_worked_example.py

Defaults to http://localhost:6006 (Phoenix's default OTLP HTTP host:port).
"""

import hashlib
import json
import os
import time

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Link, SpanKind, Status, StatusCode

OTLP_HOST = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://localhost:6006",
).rstrip("/")
TRACES_ENDPOINT = f"{OTLP_HOST}/v1/traces"

REPO = "coilysiren/coilyco-ai"
ISSUE = 24
SESSION_ID = hashlib.sha256(f"{REPO}#{ISSUE}".encode()).hexdigest()[:16]
TASK_ID = "task-validate-001"


def make_provider(agent_id: str, agent_name: str, agent_version: str) -> TracerProvider:
    """Each agent gets its own TracerProvider so Agent Card data scopes as a Resource."""
    resource = Resource.create(
        {
            "service.name": f"a2a-agent-{agent_id.lower()}",
            "agent.id": agent_id,
            "agent.name": agent_name,
            "agent.version": agent_version,
            "agent.capabilities": json.dumps(["streaming", "messages"]),
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=TRACES_ENDPOINT))
    )
    return provider


def common_attrs() -> dict:
    return {
        "session.id": SESSION_ID,
        "a2a.task.id": TASK_ID,
    }


def emit_trace_1_a_send(provider_a: TracerProvider):
    """Trace 1: A sends message/stream to B. CLIENT side."""
    tracer = provider_a.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.client.send",
        kind=SpanKind.CLIENT,
        attributes={
            **common_attrs(),
            "openinference.span.kind": "AGENT",
            "peer.agent.id": "B",
            "a2a.method": "message/stream",
            "rpc.system": "jsonrpc",
            "rpc.service": "a2a",
            "rpc.method": "message/stream",
        },
    ) as send_span:
        client_send_ctx = send_span.get_span_context()
        with tracer.start_as_current_span(
            "a2a.message.send",
            attributes={
                **common_attrs(),
                "openinference.span.kind": "LLM",
                "input.value": json.dumps(
                    {
                        "role": "user",
                        "parts": [
                            {"kind": "text", "text": "summarize the design doc"}
                        ],
                    }
                ),
                "input.mime_type": "application/json",
            },
        ):
            pass
    return client_send_ctx


def emit_trace_2_b_task(provider_b: TracerProvider, link_to_send_ctx):
    """Trace 2: B executes the task. AGENT side, the meat."""
    tracer = provider_b.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.task",
        kind=SpanKind.SERVER,
        attributes={
            **common_attrs(),
            "openinference.span.kind": "AGENT",
            "a2a.task.state": "working",
        },
        links=[Link(link_to_send_ctx)],
    ) as task_span:
        task_ctx = task_span.get_span_context()
        task_span.add_event(
            "a2a.task.state_change",
            attributes={"from": "submitted", "to": "working"},
        )
        chunks = [
            ("The design doc proposes ", False),
            ("an A2A relay backed by OTel spans, ", False),
            ("validated against Phoenix.", True),
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
            "a2a.task.state_change",
            attributes={"from": "working", "to": "completed"},
        )
        with tracer.start_as_current_span(
            "a2a.message.send",
            attributes={
                **common_attrs(),
                "openinference.span.kind": "LLM",
                "output.value": json.dumps(
                    {
                        "role": "agent",
                        "parts": [
                            {
                                "kind": "text",
                                "text": "".join(c[0] for c in chunks),
                            }
                        ],
                    }
                ),
                "output.mime_type": "application/json",
            },
        ):
            pass
        task_span.set_attribute("a2a.task.state", "completed")
        task_span.set_status(Status(StatusCode.OK))
    return task_ctx


def emit_trace_3_a_recv(provider_a: TracerProvider, link_to_task_ctx):
    """Trace 3: A reads the result. CLIENT side."""
    tracer = provider_a.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.client.recv",
        kind=SpanKind.CLIENT,
        attributes={
            **common_attrs(),
            "openinference.span.kind": "AGENT",
            "a2a.method": "tasks/get",
        },
        links=[Link(link_to_task_ctx)],
    ):
        pass


def main() -> None:
    print(f"Posting worked example to {TRACES_ENDPOINT}")
    print(f"  session.id = {SESSION_ID}")
    print(f"  task.id    = {TASK_ID}")

    provider_a = make_provider("A", "alpha-agent", "0.1.0")
    provider_b = make_provider("B", "beta-agent", "0.1.0")

    send_ctx = emit_trace_1_a_send(provider_a)
    task_ctx = emit_trace_2_b_task(provider_b, send_ctx)
    emit_trace_3_a_recv(provider_a, task_ctx)

    provider_a.shutdown()
    provider_b.shutdown()

    print("Done. Validate in Phoenix:")
    print(f"  - Sessions tab: row for session.id = {SESSION_ID}")
    print("  - Agent Graph: nodes A and B with edges A->B and B->A")
    print("  - Trace Tree on the a2a.task trace: state-change and stream-chunk events inline, child a2a.message.send LLM span at the end")


if __name__ == "__main__":
    main()
