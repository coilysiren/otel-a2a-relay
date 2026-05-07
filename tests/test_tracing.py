"""Tests for `tracing.bootstrap()` - the caller-configurable OTel entrypoint."""

from __future__ import annotations

import os

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from otel_a2a_relay.tracing import bootstrap, project_name, slugify


def test_slugify_collapses_separators() -> None:
    assert slugify("Acme Corp") == "acme-corp"
    assert slugify("ACME__Corp  Checkout!") == "acme-corp-checkout"
    assert slugify("a/b\\c") == "a-b-c"


def test_project_name_with_and_without_product_area() -> None:
    assert project_name("acme", None) == "acme"
    assert project_name("Acme", "Checkout") == "acme.checkout"
    assert project_name("Acme Corp", "K8s Plane") == "acme-corp.k8s-plane"


def test_bootstrap_emits_session_start_and_sets_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    tracer = bootstrap(
        namespace="frob",
        deployment="acme",
        product_area="checkout",
        role="planner",
        version="1.2.3",
        deployment_env="prod",
        git_commit="deadbeef",
        extra_resource={"frob.colony.tier": "gold"},
        extra_processor=SimpleSpanProcessor(exporter),
    )

    # Phoenix project env var is set from slugified <deployment>.<product_area>.
    assert os.environ["PHOENIX_PROJECT_NAME"] == "acme.checkout"

    # Session-start span emitted.
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span: ReadableSpan = spans[0]
    assert span.name == "tracing.session.start"
    attrs = dict(span.attributes or {})
    assert attrs["namespace"] == "frob"
    assert attrs["deployment"] == "acme"
    assert attrs["product_area"] == "checkout"
    assert attrs["role"] == "planner"
    assert attrs["phoenix.project.name"] == "acme.checkout"
    assert attrs["version"] == "1.2.3"
    readme = str(attrs["readme"])
    assert "namespace=frob" in readme
    assert "deployment=acme" in readme
    assert "product_area=checkout" in readme
    assert "role=planner" in readme
    assert "version=1.2.3" in readme

    # Resource attributes carry caller identity.
    res = dict(span.resource.attributes)
    assert res["service.namespace"] == "frob"
    assert res["service.name"] == "planner"
    assert res["openinference.project.name"] == "acme.checkout"
    assert res["frob.colony"] == "acme"
    assert res["frob.product_area"] == "checkout"
    assert res["service.version"] == "1.2.3"
    assert res["deployment.environment.name"] == "prod"
    assert res["vcs.repository.ref.revision"] == "deadbeef"
    assert res["frob.colony.tier"] == "gold"

    # The returned tracer is functional.
    with tracer.start_as_current_span("downstream"):
        pass
    assert any(s.name == "downstream" for s in exporter.get_finished_spans())


def test_bootstrap_without_product_area_falls_back_to_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    exporter = InMemorySpanExporter()
    bootstrap(
        namespace="frob",
        deployment="acme",
        role="relay",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    assert os.environ["PHOENIX_PROJECT_NAME"] == "acme"
    span = exporter.get_finished_spans()[0]
    attrs = dict(span.attributes or {})
    assert "product_area" not in attrs
    assert attrs["phoenix.project.name"] == "acme"


def test_bootstrap_does_not_clobber_existing_phoenix_project_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "preset-project")
    exporter = InMemorySpanExporter()
    bootstrap(
        namespace="frob",
        deployment="acme",
        product_area="checkout",
        role="planner",
        extra_processor=SimpleSpanProcessor(exporter),
    )
    assert os.environ["PHOENIX_PROJECT_NAME"] == "preset-project"
