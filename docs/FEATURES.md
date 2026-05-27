# Features

Baseline inventory of what `otel-a2a-relay` ships today. Last full sweep: 2026-05-08.

## Core relay

Exercise: `coily exec test-core`.

- **A2A JSON-RPC 2.0 server** over HTTP. Methods: `message/send`, `message/stream`, `tasks/get`, `tasks/cancel`.
- **AgentCard discovery** at `/.well-known/agent.json`, plus `/peers` aggregation.
- **Star-topology enforcement**. Only the orchestrator can target peers. Violations return `-32010`.
- **Peer registry** sourced from `OTEL_A2A_RELAY_PEERS`.
- **In-memory task store** with thread-safe state machine (submitted / working / completed / failed / canceled).
- **Synthetic task synthesis** when no peers are configured.
- **W3C `traceparent` propagation** end-to-end.

## Telemetry emission

- **Backend-agnostic OTLP/HTTP exporter** via `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **OpenInference-compatible span attributes** for Phoenix Agent Graph / Sessions.
- **Per-span payloads** include task state, state-change events, stream chunks, input/output.
- **Session propagation** via OpenInference `using_session()`.
- **Span attributes** documented in [protocol-attributes.md](protocol-attributes.md).
- **Reusable span assertions** library.
- **In-memory span store** for test fixtures.

## Arize Phoenix integration

Exercise: `coily exec test-arize-phoenix`.

- **`o2r-harness`** - posts a worked-example trace and prints validation steps.
- **`o2r-phoenix-bootstrap`** - idempotent provisioning of annotation configs + datasets via Phoenix REST.
- **`o2r-view`** - reduces Phoenix session spans to a readable per-hop log.
- **GIF rendering** of session topologies from real Phoenix spans. Deterministic. Pillow renderer with embedded JetBrains Mono font, optional `viz` extra.
- **REST + GraphQL query helpers** for Phoenix.

## Agent Channel coordination layer

Exercise: `coily exec test-channels`. Protocol: [channels-protocol.md](channels-protocol.md).

- **`otel-a2a-relay-channels` package** - FastAPI router + Postgres schema + Pydantic models.
- **8 routes** under `/agent-channel`: create, list, onboarding (json/yaml/markdown), spec, state, events, append, close.
- **4-char dictatable IDs** (2 letters + 2 digits).
- **Append-only event log** with kinds `spec`, `state`, `status`, `comms`, `log`.
- **OTel span per event** so channel activity lights up alongside A2A traces.
- **Backend-agnostic**: `make_router(...)` accepts `pool_provider`, optional `auth_dependency`, `base_url`.

## Tempo + Grafana integration

Exercise: `coily exec test-tempo-grafana`.

- **Dockerized stack** - Tempo 2.6.1, Prometheus 2.55.1, Grafana 11.3.1 with provisioned datasources.
- **Provisioned dashboards** - `o2r-overview` (live topology, span metrics, error analysis), `LUCA-flow` (per-session waterfall, step latency, acceptance decisions).
- **`o2r-tempo-harness`** - posts a worked-example trace, waits for indexing, prints a Grafana Explore link.
- **`bootstrap_tempo()`** helper defaults `OTEL_EXPORTER_OTLP_ENDPOINT` to local Tempo (port 4318).
- **Span and service-graph metrics** via Tempo's `metrics_generator` to Prometheus.
- **Service-graph edges** keyed by `agent.role`, `session.id`, `a2a.method`.

## LUCA-flow demo

- **Multi-agent choreography** - orchestrator + planner + validator + deployer + eight transient workers. Builds an AURORA microsite from NASA imagery.
- **Real validation steps** - HTML5 parsing, `<h1>` count, alt-text checks, internal link resolution, word and image counts.
- **Intentional failure modes** - worker-d crashes, worker-g topology bypass rejected with `-32010`.
- **Frozen timestamps** via `LUCA_FREEZE_TIME` for byte-snapshotted output.
- **Backend-agnostic** - runs against any OTLP/HTTP collector.
- **Orchestrator spans** - see [luca-flow-spans.md](luca-flow-spans.md).

## See also

- [README.md](../README.md), [AGENTS.md](../AGENTS.md), [.coily/coily.yaml](../.coily/coily.yaml).

Cross-reference convention from [coilysiren/agentic-os#59](https://github.com/coilysiren/agentic-os/issues/59).
