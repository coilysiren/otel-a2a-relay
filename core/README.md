# otel-a2a-relay-core

Backend-agnostic core of the otel-a2a-relay protocol. Ships:

- The relay HTTP server (`otel_a2a_relay_core.server`) - speaks JSON-RPC 2.0 A2A on the wire, emits OpenInference-compatible OTel spans.
- A consumer-agnostic tracing bootstrap (`otel_a2a_relay_core.tracing.bootstrap`) - hand it a namespace + deployment + role, get back a configured `Tracer` that exports OTLP/HTTP to whatever backend `OTEL_EXPORTER_OTLP_ENDPOINT` points at.
- A small echo A2A peer (`otel_a2a_relay_core.agent`) for two-process dogfood.
- An in-memory task store and OTLP exporter shim.

No Phoenix coupling, no Tempo coupling. The wire shape is documented in `docs/protocol.md` at the workspace root.

Backend-specific surfaces (harness probes, dataset/annotation provisioning, query helpers, dashboards) live in sibling packages: `otel-a2a-relay-arize-phoenix` and `otel-a2a-relay-tempo-grafana`.
