"""TracerProvider setup. One per relay process.

Agent identity does NOT live on the Resource (Phoenix drops Resource attributes).
The Resource carries only relay-process identity; agent.* attributes are stamped
on each span by the caller. See docs/protocol.md.
"""

from __future__ import annotations

import os

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

DEFAULT_OTLP_HOST = "http://localhost:6006"


def traces_endpoint(host: str | None = None) -> str:
    base = (host or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_OTLP_HOST).rstrip("/")
    return f"{base}/v1/traces"


def make_provider(extra_processor: SpanProcessor | None = None) -> TracerProvider:
    resource = Resource.create({"service.name": "o2r"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint())))
    if extra_processor is not None:
        provider.add_span_processor(extra_processor)
    return provider
