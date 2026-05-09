# Features

Baseline inventory of what `otel-a2a-relay` ships today. Use this as the reference point for scope changes. When a feature is added, removed, or materially reshaped, update the relevant section so the diff against this file shows scope drift over time.

Last full sweep: 2026-05-08.

## Core relay

- **A2A JSON-RPC 2.0 server** over HTTP. Methods: `message/send`, `message/stream`, `tasks/get`, `tasks/cancel`. See [core/src/otel_a2a_relay_core/server.py](../core/src/otel_a2a_relay_core/server.py).
- **AgentCard discovery** at `/.well-known/agent.json`, plus `/peers` aggregation endpoint. See [core/src/otel_a2a_relay_core/agent.py](../core/src/otel_a2a_relay_core/agent.py).
- **Star-topology enforcement**. Only the orchestrator can target peers. Other peers can only target the orchestrator. Violations return JSON-RPC error `-32010`. See [core/src/otel_a2a_relay_core/server.py](../core/src/otel_a2a_relay_core/server.py).
- **Peer registry** sourced from `OTEL_A2A_RELAY_PEERS` env var.
- **In-memory task store** with thread-safe read/write/update and state machine (submitted, working, completed, failed, canceled). See [core/src/otel_a2a_relay_core/store.py](../core/src/otel_a2a_relay_core/store.py).
- **Synthetic task synthesis** when no peers are configured (single-node smoke path).
- **W3C `traceparent` propagation** end-to-end across hops.

## Telemetry emission

- **Backend-agnostic OTLP/HTTP exporter** driven by `OTEL_EXPORTER_OTLP_ENDPOINT`. Works with any OTLP/HTTP collector (Phoenix, Tempo, Honeycomb, Datadog). See [core/src/otel_a2a_relay_core/telemetry.py](../core/src/otel_a2a_relay_core/telemetry.py).
- **OpenInference-compatible span attributes** so Phoenix Agent Graph and Sessions views light up without bespoke config.
- **Per-span payloads** include task state, state-change events, stream chunks, input/output payloads.
- **Session propagation** via OpenInference `using_session()` context manager.
- **Span attribute conventions**:
  - `openinference.span.kind` (AGENT, LLM, TOOL)
  - `agent.role` (worker, validator, orchestrator, planner, deployer)
  - `agent.specialization` (designer, curator, science_writer, spec_writer, polish_writer, rogue)
  - `o2r.relay.failure_class` (topology_violation, peer_disconnect, peer_404, timeout, peer_jsonrpc_error, unknown)
  - `graph.node.id`, `graph.node.parent_id` for Agent Graph rendering
- **Reusable span assertions** library: `every_tool_call_is_observed()`, `no_pii_in_attributes()`, `agent_role_mandatory()`, `failure_class_on_errors()`, `session_id_on_every_span()`, `graph_parent_referential_integrity()`. See [core/src/otel_a2a_relay_core/assertions.py](../core/src/otel_a2a_relay_core/assertions.py).
- **In-memory span store** for test fixtures without standing up a backend. See [core/src/otel_a2a_relay_core/span_store.py](../core/src/otel_a2a_relay_core/span_store.py).

## Arize Phoenix integration

Package: [arize_phoenix/](../arize_phoenix/).

- **`o2r-harness`**: posts a worked-example trace and prints validation steps.
- **`o2r-phoenix-bootstrap`**: idempotent provisioning of annotation configs (`relay_failure_class`, `task_outcome_correct`) and datasets (`relay-decisions-golden`, `relay-failures-regression`) via Phoenix REST API.
- **`o2r-view`**: reduces Phoenix session spans to a readable per-hop log with agent tagging and event details.
- **GIF rendering** of session topologies from real Phoenix spans, with temporal animation. Same `session.id` produces byte-identical GIFs (deterministic). Pillow renderer with embedded JetBrains Mono font, optional `viz` extra.
- **REST + GraphQL query helpers** for Phoenix.

## Tempo + Grafana integration

Package: [tempo_grafana/](../tempo_grafana/).

- **Dockerized stack**: Tempo 2.6.1, Prometheus 2.55.1, Grafana 11.3.1 with provisioned datasources.
- **Provisioned dashboards**:
  - `o2r-overview`: live topology, span metrics, error analysis.
  - `LUCA-flow`: per-session waterfall, step latency, acceptance decisions.
- **`o2r-tempo-harness`**: posts a worked-example trace, waits for indexing, prints a Grafana Explore link.
- **`bootstrap_tempo()`** helper defaults `OTEL_EXPORTER_OTLP_ENDPOINT` to local Tempo (port 4318).
- **Span and service-graph metrics** via Tempo's `metrics_generator` to Prometheus.
- **TraceQL examples** for per-agent, per-role, per-session analysis.
- **Service-graph edges** keyed by `agent.role`, `session.id`, `a2a.method`.

## LUCA-flow demo

Package: [examples/luca-flow/](../examples/luca-flow/).

- **Multi-agent choreography**: orchestrator + planner + validator + deployer + eight transient workers. Builds an AURORA microsite from NASA imagery.
- **Real validation steps**: HTML5 parsing, `<h1>` count, image alt-text checks, internal link resolution, word and image counts.
- **Intentional failure modes**: worker-d crashes (exit 1), worker-g attempts a topology bypass and is rejected with `-32010`. Exercises the failure-class taxonomy.
- **Frozen timestamps** via `LUCA_FREEZE_TIME` for byte-snapshotted output.
- **Backend-agnostic**: runs against any OTLP/HTTP collector.
- **Span shape conventions**:
  - `orchestrator.flow` (long-lived root)
  - `orchestrator.step.<n>` (per-step subtrees)
  - `orchestrator.acceptance` (decision + reason + criterion + score)

## Tooling and developer experience

- **uv workspace** with four members: `core`, `arize_phoenix`, `tempo_grafana`, `examples/luca-flow`.
- **CLI entrypoints**:
  - `o2r-relay` (relay HTTP server)
  - `o2r-agent` (echo peer)
  - `o2r-harness` (Phoenix validation)
  - `o2r-phoenix-bootstrap`
  - `o2r-view`
  - `o2r-tempo-harness`
  - `luca-flow`
- **Pytest with 100% coverage enforcement** per package.
- **Lint stack**: ruff + mypy. Pre-commit config runs ruff format checks.
- **Make targets** for test, lint, format, and LUCA snapshot diffing. See [Makefile](../Makefile).
- **Process scripts**:
  - [scripts/bg.sh](../scripts/bg.sh): pidfile-backed start/stop/status for the relay.
  - [scripts/wait-healthy.sh](../scripts/wait-healthy.sh): poll loop for `/healthz`.

## Documentation

- **Protocol v0.3 spec**: wire shape, topology, sessions, agent graph, worked example. See [docs/protocol.md](protocol.md).
- **Harness reference**. See [docs/harness.md](harness.md).
- **Per-package READMEs** for core, arize_phoenix, tempo_grafana, luca-flow.
- **Makefile help target** documents workspace-wide and backend-specific targets.

## Planned, not yet shipped

Tracked in [PLAN.md](../PLAN.md). Listed here so scope-drift reviews can tell "added" from "promoted from plan."

- Peer forwarding inside the relay (next slice after dogfood).
- Authentication.
- Pluggable persistence beyond the in-memory task store and Phoenix's DB.
