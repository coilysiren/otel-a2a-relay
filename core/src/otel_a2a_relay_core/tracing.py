"""Caller-configurable OTel tracing bootstrap for consumers of this protocol.

The relay is consumer-agnostic. Any framework that wants to participate in the
o2r protocol calls `bootstrap()` with its own identity values and gets back a
fully-configured `Tracer` plus a self-describing session-start span. Identity
fields are recorded as OTel resource attributes (relay's own emission path
keeps span-level redundancy because Phoenix drops Resource attrs in its UI -
resource attrs are still useful for non-Phoenix consumers and the
`PHOENIX_PROJECT_NAME` derivation below).

See docs/protocol.md "Tracing bootstrap" for the contract.
"""

from __future__ import annotations

import os
import re
from typing import Any

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import Tracer

DEFAULT_OTLP_HOST = "http://localhost:6006"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"-+")


def slugify(value: str) -> str:
    """Lowercase, collapse non-`[a-z0-9]` runs to a single `-`, strip edges."""
    out = _SLUG_STRIP.sub("-", value.lower())
    out = _SLUG_TRIM.sub("-", out).strip("-")
    return out


def traces_endpoint(host: str | None = None) -> str:
    base = (host or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_OTLP_HOST).rstrip("/")
    return f"{base}/v1/traces"


def project_name(deployment: str) -> str:
    """Phoenix project name = slugified `<deployment>`."""
    return slugify(deployment)


def bootstrap(
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
    """Configure OTel for a process consuming the o2r protocol.

    Required:
      namespace   - logical system name. OTel `service.namespace`. Also the root
                    prefix for caller-specific resource attributes
                    (`<namespace>.deployment`, ...).
      deployment  - logical install identifier. Slugified into the Phoenix
                    project name.
      role        - this process's role in the graph. OTel `service.name`.

    Optional:
      deployment_env, version, git_commit  - resource attributes for slicing.
      extra_resource  - dict of additional resource attributes, merged last.
      extra_processor - additional SpanProcessor for tests.
      endpoint        - override OTLP host (default reads env or localhost).
      emit_readme_span - emit a self-describing `tracing.session.start` smoke
                        span at bootstrap time. Off by default - the span has
                        zero IO and zero session context, so on real flows it
                        crowds the project list without informing anything.
                        Tests and one-off probes can opt in.

    Side effects:
      Sets `PHOENIX_PROJECT_NAME` env var if not already set, derived from the
      slugified `<deployment>`. Phoenix reads this on the exporter side, not us.

    Returns the configured `Tracer`. The caller owns its lifetime; nothing in
    the relay holds a reference.
    """
    proj = project_name(deployment)
    os.environ.setdefault("PHOENIX_PROJECT_NAME", proj)

    resource_attrs: dict[str, Any] = {
        "service.namespace": namespace,
        "service.name": role,
        # Phoenix routes spans by this attribute (env equivalent: PHOENIX_PROJECT_NAME).
        "openinference.project.name": proj,
        f"{namespace}.deployment": deployment,
    }
    if deployment_env:
        resource_attrs["deployment.environment.name"] = deployment_env
    if version:
        resource_attrs["service.version"] = version
    if git_commit:
        resource_attrs["vcs.repository.ref.revision"] = git_commit
    if extra_resource:
        resource_attrs.update(extra_resource)

    provider = TracerProvider(resource=Resource.create(resource_attrs))
    provider.add_span_processor(
        SimpleSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint(endpoint)))
    )
    if extra_processor is not None:
        provider.add_span_processor(extra_processor)

    tracer = provider.get_tracer(f"{namespace}.{role}")

    if emit_readme_span:
        readme_parts = [
            f"namespace={namespace}",
            f"deployment={deployment}",
            f"role={role}",
        ]
        if version:
            readme_parts.append(f"version={version}")
        readme = " ".join(readme_parts)

        session_attrs: dict[str, Any] = {
            "readme": readme,
            "namespace": namespace,
            "deployment": deployment,
            "role": role,
            "phoenix.project.name": proj,
        }
        if deployment_env:
            session_attrs["deployment_env"] = deployment_env
        if version:
            session_attrs["version"] = version
        if git_commit:
            session_attrs["git_commit"] = git_commit

        with tracer.start_as_current_span("tracing.session.start", attributes=session_attrs):
            pass

    return tracer
