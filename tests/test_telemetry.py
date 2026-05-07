"""Tests for the TracerProvider factory."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otel_a2a_relay.telemetry import DEFAULT_OTLP_HOST, make_provider, traces_endpoint


def test_traces_endpoint_uses_default_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert traces_endpoint() == f"{DEFAULT_OTLP_HOST}/v1/traces"


def test_traces_endpoint_honors_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/")
    assert traces_endpoint() == "http://collector:4318/v1/traces"


def test_traces_endpoint_explicit_host_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://env:4318")
    assert traces_endpoint("http://explicit:9999") == "http://explicit:9999/v1/traces"


def test_make_provider_returns_tracer_provider() -> None:
    provider = make_provider()
    assert isinstance(provider, TracerProvider)
    assert (provider.resource.attributes or {}).get("service.name") == "o2r"


def test_make_provider_attaches_extra_processor() -> None:
    exporter = InMemorySpanExporter()
    extra = SimpleSpanProcessor(exporter)
    provider = make_provider(extra_processor=extra)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("span"):
        pass
    provider.force_flush()
    assert [s.name for s in exporter.get_finished_spans()] == ["span"]
