"""otel-a2a-relay: A2A wire traffic as OTel spans.

The relay is consumer-agnostic. Frameworks consuming the protocol call
`tracing.bootstrap()` to stand up a tracer with their own identity.
"""

from otel_a2a_relay.tracing import bootstrap

__all__ = ["bootstrap"]
