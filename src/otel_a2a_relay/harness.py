"""Phoenix harness for otel-a2a-relay protocol v0.1.

Posts the worked-example spans (A streams a task to B, B completes, A acks)
via OTLP/HTTP to a local Phoenix and exits. Use this to confirm Phoenix's
Sessions, Agent Graph, and Trace Tree views render the protocol correctly
before writing any relay code.

Usage:
    uv run otel-a2a-relay-harness
    OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix.local:6006 uv run otel-a2a-relay-harness

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
from opentelemetry.trace import SpanKind, Status, StatusCode

OTLP_HOST = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "http://localhost:6006",
).rstrip("/")
TRACES_ENDPOINT = f"{OTLP_HOST}/v1/traces"

REPO = "coilysiren/otel-a2a-relay"
ISSUE = 1
SESSION_ID = hashlib.sha256(f"{REPO}#{ISSUE}".encode()).hexdigest()[:16]
TASK_ID = "task-validate-001"

# Agent Cards. Phoenix drops Resource attributes, so these are stamped on
# every span the relay emits on the agent's behalf. See docs/protocol.md.
AGENTS = {
    "A": {"agent.id": "A", "agent.name": "alpha-agent", "agent.version": "0.1.0"},
    "B": {"agent.id": "B", "agent.name": "beta-agent", "agent.version": "0.1.0"},
}


def make_provider() -> TracerProvider:
    """One TracerProvider for the whole relay process. Agent identity rides on span attrs."""
    resource = Resource.create({"service.name": "otel-a2a-relay"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=TRACES_ENDPOINT)))
    return provider


def base_attrs(acting_agent: str) -> dict[str, str]:
    """Attributes every emitted span carries. Agent Card fields included redundantly."""
    return {
        "session.id": SESSION_ID,
        "a2a.task.id": TASK_ID,
        **AGENTS[acting_agent],
    }


def emit_trace_1_a_send(provider: TracerProvider) -> None:
    """Trace 1: A sends message/stream to B. CLIENT side."""
    tracer = provider.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.client.send",
        kind=SpanKind.CLIENT,
        attributes={
            **base_attrs("A"),
            "openinference.span.kind": "AGENT",
            "graph.node.id": "A",
            "peer.agent.id": "B",
            "a2a.method": "message/stream",
            "rpc.system": "jsonrpc",
            "rpc.service": "a2a",
            "rpc.method": "message/stream",
        },
    ):
        with tracer.start_as_current_span(
            "a2a.message.send",
            attributes={
                **base_attrs("A"),
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


def emit_trace_2_b_task(provider: TracerProvider) -> None:
    """Trace 2: B executes the task. AGENT side, the meat."""
    tracer = provider.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.task",
        kind=SpanKind.SERVER,
        attributes={
            **base_attrs("B"),
            "openinference.span.kind": "AGENT",
            "graph.node.id": "B",
            "graph.node.parent_id": "A",
            "a2a.task.state": "working",
        },
    ) as task_span:
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
                **base_attrs("B"),
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


def emit_trace_3_a_recv(provider: TracerProvider) -> None:
    """Trace 3: A reads the result. CLIENT side."""
    tracer = provider.get_tracer("otel-a2a-relay-harness")
    with tracer.start_as_current_span(
        "a2a.client.recv",
        kind=SpanKind.CLIENT,
        attributes={
            **base_attrs("A"),
            "openinference.span.kind": "AGENT",
            "graph.node.id": "A",
            "graph.node.parent_id": "B",
            "a2a.method": "tasks/get",
        },
    ):
        pass


def main() -> None:
    print(f"Posting worked example to {TRACES_ENDPOINT}")
    print(f"  session.id = {SESSION_ID}")
    print(f"  task.id    = {TASK_ID}")

    provider = make_provider()
    emit_trace_1_a_send(provider)
    emit_trace_2_b_task(provider)
    emit_trace_3_a_recv(provider)
    provider.shutdown()

    print("Done. Validate in Phoenix:")
    print(f"  - Sessions tab: row for session.id = {SESSION_ID}")
    print("  - Agent Graph: nodes A and B, edge A->B (from B's task), edge B->A (from A's recv)")
    print(
        "  - Trace Tree on the a2a.task trace: events inline, "
        "child a2a.message.send LLM span at the end"
    )


if __name__ == "__main__":
    main()
