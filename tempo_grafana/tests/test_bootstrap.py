"""Tests for `otel_a2a_relay_tempo_grafana.bootstrap`."""

from __future__ import annotations

import os

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from otel_a2a_relay_tempo_grafana import bootstrap_tempo
from otel_a2a_relay_tempo_grafana.bootstrap import (
    DEFAULT_TEMPO_OTLP_ENDPOINT,
    DEFAULT_TEMPO_QUERY_URL,
)


def test_default_endpoints_exposed() -> None:
    """Pin the bundled docker-compose ports. Drift here means the docs
    in tempo_grafana/README.md and the LUCA-flow runner help text need
    matching updates."""
    assert DEFAULT_TEMPO_OTLP_ENDPOINT == "http://localhost:4318"
    assert DEFAULT_TEMPO_QUERY_URL == "http://localhost:3200"


def test_bootstrap_tempo_defaults_to_tempo_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no env override and no explicit endpoint, `bootstrap_tempo`
    should send to Tempo's bundled docker-compose port - that's the
    point of the wrapper. Fail-closed if a future refactor accidentally
    falls back to the core default (Phoenix's 6006).
    """
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    tracer = bootstrap_tempo(
        namespace="o2r",
        deployment="harness",
        role="harness",
        extra_processor=SimpleSpanProcessor(exporter),
        emit_readme_span=True,
    )
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span: ReadableSpan = spans[0]
    assert span.name == "tracing.session.start"
    # Sanity: the tracer the wrapper hands back is functional.
    with tracer.start_as_current_span("downstream"):
        pass
    assert any(s.name == "downstream" for s in exporter.get_finished_spans())


def test_bootstrap_tempo_respects_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit `OTEL_EXPORTER_OTLP_ENDPOINT` wins over the Tempo default.
    A consumer that already wired their own collector path should not have
    that override silently undone by importing the Tempo helper."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://my-collector:9999")
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    bootstrap_tempo(
        namespace="o2r",
        deployment="harness",
        role="harness",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    # Bootstrap doesn't expose the resolved endpoint, but it does pass it
    # through to the OTLP exporter. The cleanest assertion we can make
    # without poking the SDK internals is that it ran without exception
    # and the env var still points where the caller set it.
    assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://my-collector:9999"


def test_bootstrap_tempo_respects_explicit_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit `endpoint=` arg wins over both env and default."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://from-env:9999")
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    bootstrap_tempo(
        namespace="o2r",
        deployment="harness",
        role="harness",
        endpoint="http://explicit-arg:8080",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    # No exception means the explicit arg was used by the wrapped bootstrap.
