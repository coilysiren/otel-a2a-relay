"""Tests for `tracing.bootstrap()` - the caller-configurable OTel entrypoint."""

from __future__ import annotations

import os

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from otel_a2a_relay_core.tracing import bootstrap, project_name, slugify


def test_slugify_collapses_separators() -> None:
    assert slugify("Acme Corp") == "acme-corp"
    assert slugify("ACME__Corp  Checkout!") == "acme-corp-checkout"
    assert slugify("a/b\\c") == "a-b-c"


def test_project_name_slugifies_deployment() -> None:
    assert project_name("acme") == "acme"
    assert project_name("Acme Corp") == "acme-corp"
    assert project_name("Some__Deployment  Name!") == "some-deployment-name"


def test_bootstrap_emits_session_start_and_sets_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    tracer = bootstrap(
        namespace="frob",
        deployment="acme",
        role="planner",
        version="1.2.3",
        deployment_env="prod",
        git_commit="deadbeef",
        extra_resource={"frob.deployment.tier": "gold"},
        extra_processor=SimpleSpanProcessor(exporter),
        emit_readme_span=True,
    )

    # Phoenix project env var is set from slugified <deployment>.
    assert os.environ["PHOENIX_PROJECT_NAME"] == "acme"

    # Session-start span emitted.
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span: ReadableSpan = spans[0]
    assert span.name == "tracing.session.start"
    attrs = dict(span.attributes or {})
    assert attrs["namespace"] == "frob"
    assert attrs["deployment"] == "acme"
    assert attrs["role"] == "planner"
    assert attrs["phoenix.project.name"] == "acme"
    assert attrs["version"] == "1.2.3"
    readme = str(attrs["readme"])
    assert "namespace=frob" in readme
    assert "deployment=acme" in readme
    assert "role=planner" in readme
    assert "version=1.2.3" in readme

    # Resource attributes carry caller identity. v0.4 renamed `<namespace>.colony`
    # to `<namespace>.deployment` and dropped `<namespace>.product_area` entirely;
    # see otel-a2a-relay#121.
    res = dict(span.resource.attributes)
    assert res["service.namespace"] == "frob"
    assert res["service.name"] == "planner"
    assert res["openinference.project.name"] == "acme"
    assert res["frob.deployment"] == "acme"
    assert "frob.colony" not in res
    assert "frob.product_area" not in res
    assert res["service.version"] == "1.2.3"
    assert res["deployment.environment.name"] == "prod"
    assert res["vcs.repository.ref.revision"] == "deadbeef"
    assert res["frob.deployment.tier"] == "gold"

    # The returned tracer is functional.
    with tracer.start_as_current_span("downstream"):
        pass
    assert any(s.name == "downstream" for s in exporter.get_finished_spans())


def test_bootstrap_does_not_emit_readme_span_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The smoke `tracing.session.start` span is opt-in. Default flow keeps
    the project list clean: real work spans carry the session context, the
    readme span doesn't."""
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    bootstrap(
        namespace="frob",
        deployment="acme",
        role="relay",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    assert exporter.get_finished_spans() == ()


def test_bootstrap_does_not_clobber_existing_phoenix_project_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "preset-project")
    exporter = InMemorySpanExporter()
    bootstrap(
        namespace="frob",
        deployment="acme",
        role="planner",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    assert os.environ["PHOENIX_PROJECT_NAME"] == "preset-project"
