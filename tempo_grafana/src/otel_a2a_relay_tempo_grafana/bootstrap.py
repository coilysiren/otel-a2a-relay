"""Tempo-flavored wrapper around `otel_a2a_relay_core.tracing.bootstrap`.

Tempo's default OTLP/HTTP port is 4318 (the OpenTelemetry HTTP default).
Phoenix uses 6006. Without a wrapper, callers of `bootstrap()` have to
remember to set `OTEL_EXPORTER_OTLP_ENDPOINT` to the right value for the
backend they're targeting; this module fixes the default to Tempo so the
sibling `arize_phoenix` and `tempo_grafana` packages mirror each other.

The relay's protocol attributes are unchanged - Tempo and Phoenix both
consume the same `o2r.*` / `agent.role` / `session.id` shape.
"""

from __future__ import annotations

import os
from typing import Any

from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import Tracer
from otel_a2a_relay_core.tracing import bootstrap as _core_bootstrap

DEFAULT_TEMPO_OTLP_ENDPOINT = "http://localhost:4318"
"""Where Tempo's OTLP HTTP receiver binds in the bundled docker-compose."""

DEFAULT_TEMPO_QUERY_URL = "http://localhost:3200"
"""Tempo HTTP query API. Grafana's datasource talks to this."""

DEFAULT_GRAFANA_URL = "http://localhost:3000"
"""Bundled Grafana UI."""


def bootstrap_tempo(
    *,
    namespace: str,
    deployment: str,
    role: str,
    deployment_env: str | None = None,
    version: str | None = None,
    git_commit: str | None = None,
    extra_resource: dict[str, Any] | None = None,
    extra_processor: SpanProcessor | None = None,
    endpoint: str | None = None,
    emit_readme_span: bool = False,
) -> Tracer:
    """Bootstrap a tracer that exports to Tempo (default localhost:4318).

    Thin wrapper around `otel_a2a_relay_core.tracing.bootstrap` - the only
    difference is the default OTLP endpoint. Identity and span-shape
    semantics are identical, so the same protocol surface lights up under
    Tempo's TraceQL/Grafana view that lights up under Phoenix's Sessions
    tab. If `OTEL_EXPORTER_OTLP_ENDPOINT` is already set in the env (or
    `endpoint` is passed explicitly), the caller wins - this just removes
    the per-process boilerplate of remembering the Tempo port.
    """
    resolved = (
        endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_TEMPO_OTLP_ENDPOINT
    )
    tracer: Tracer = _core_bootstrap(
        namespace=namespace,
        deployment=deployment,
        role=role,
        deployment_env=deployment_env,
        version=version,
        git_commit=git_commit,
        extra_resource=extra_resource,
        extra_processor=extra_processor,
        endpoint=resolved,
        emit_readme_span=emit_readme_span,
    )
    return tracer
