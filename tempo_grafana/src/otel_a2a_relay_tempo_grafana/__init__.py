"""Tempo + Grafana backend extension for `otel-a2a-relay-core`.

Bootstraps an OTel tracer that defaults to Tempo's local OTLP/HTTP
receiver (port 4318) and exposes a harness probe that posts a
worked-example trace and waits for Tempo to index it.

See package `README.md` for usage. The relay's protocol shape is
documented in `docs/protocol.md` at the workspace root.
"""

from __future__ import annotations

from otel_a2a_relay_tempo_grafana.bootstrap import (
    DEFAULT_TEMPO_OTLP_ENDPOINT,
    DEFAULT_TEMPO_QUERY_URL,
    bootstrap_tempo,
)

__all__ = [
    "DEFAULT_TEMPO_OTLP_ENDPOINT",
    "DEFAULT_TEMPO_QUERY_URL",
    "bootstrap_tempo",
]
