"""otel-a2a-relay: A2A wire traffic as OTel spans.

The relay is consumer-agnostic. Frameworks consuming the protocol call
`tracing.bootstrap()` to stand up a tracer with their own identity.
"""

from otel_a2a_relay_core.file_emit import (
    DEFAULT_SPANS_DIR,
    build_span_dict,
    default_spans_dir,
    emit_span,
)
from otel_a2a_relay_core.tracing import bootstrap

__all__ = [
    "DEFAULT_SPANS_DIR",
    "bootstrap",
    "build_span_dict",
    "default_spans_dir",
    "emit_span",
]
