# Features

Baseline inventory of what `otel-a2a-relay` ships today. Use this as the reference point for scope changes. When a feature is added, removed, or materially reshaped, update the relevant section so the diff against this file shows scope drift over time.

Last full sweep: 2026-05-08.

## Core relay

Exercise: `coily exec test-core`.

- **A2A JSON-RPC 2.0 server** over HTTP. Methods: `message/send`, `message/stream`, `tasks/get`, `tasks/cancel`.
- **AgentCard discovery** at `/.well-known/agent.json`, plus `/peers` aggregation endpoint.
- **Star-topology enforcement**. Only the orchestrator can target peers. Other peers can only target the orchestrator. Violations return JSON-RPC error `-32010`.
- **Peer registry** sourced from `OTEL_A2A_RELAY_PEERS` env var.
- **In-memory task store** with thread-safe read/write/update and state machine (submitted, working, completed, failed, canceled).
- **Synthetic task synthesis** when no peers are configured (single-node smoke path).
- **W3C `traceparent` propagation** end-to-end across hops.

## Telemetry emission

- **Backend-agnostic OTLP/HTTP exporter** driven by `OTEL_EXPORTER_OTLP_ENDPOINT`. Works with any OTLP/HTTP collector (Phoenix, Tempo, Honeycomb, Datadog).
- **OpenInference-compatible span attributes** so Phoenix Agent Graph and Sessions views light up without bespoke config.
- **Per-span payloads** include task state, state-change events, stream chunks, input/output payloads.
- **Session propagation** via OpenInference `using_session()` context manager.
- **Span attribute conventions**:
  - `openinference.span.kind` (AGENT, LLM, TOOL)
  - `agent.role` (worker, validator, orchestrator, planner, deployer)
  - `agent.specialization` (designer, curator, science_writer, spec_writer, polish_writer, rogue)
  - `o2r.relay.failure_class` (topology_violation, peer_disconnect, peer_404, timeout, peer_jsonrpc_error, unknown)
  - `graph.node.id`, `graph.node.parent_id` for Agent Graph rendering
- **Reusable span assertions** library: `every_tool_call_is_observed()`, `no_pii_in_attributes()`, `agent_role_mandatory()`, `failure_class_on_errors()`, `session_id_on_every_span()`, `graph_parent_referential_integrity()`.
- **In-memory span store** for test fixtures without standing up a backend.

## Arize Phoenix integration

Exercise: `coily exec test-arize-phoenix`.

- **`o2r-harness`**: posts a worked-example trace and prints validation steps.
- **`o2r-phoenix-bootstrap`**: idempotent provisioning of annotation configs (`relay_failure_class`, `task_outcome_correct`) and datasets (`relay-decisions-golden`, `relay-failures-regression`) via Phoenix REST API.
- **`o2r-view`**: reduces Phoenix session spans to a readable per-hop log with agent tagging and event details.
- **GIF rendering** of session topologies from real Phoenix spans, with temporal animation. Same `session.id` produces byte-identical GIFs (deterministic). Pillow renderer with embedded JetBrains Mono font, optional `viz` extra.
- **REST + GraphQL query helpers** for Phoenix.

## Agent Channel coordination layer

Exercise: `coily exec test-channels`.

- **`otel-a2a-relay-channels` package** ships a FastAPI router + Postgres schema + Pydantic models for the cross-host coordination protocol in [`docs/channels-protocol.md`](channels-protocol.md).
- **8 routes** under `/agent-channel`: create, list, self-describing onboarding (json / yaml / markdown), latest spec, latest state, event log, append event, close.
- **4-character dictatable IDs** drawn from the alphabet in `agentic-os docs/dictatable-id-alphabet.md` (28^4 channels, dropped collisions: I, L, O, 1, 0, N, 2, 3).
- **Self-describing onboarding** at `GET /agent-channel/{id}`: prose, charter, current state, recent events, and the participate cheat sheet.
- **Append-only event log** with kinds `spec`, `state`, `status`, `comms`, `log` (free-string, so the protocol can add kinds without a schema change).
- **OTel span per event**: every `POST /agent-channel/{id}/event` opens one span `agent-channel.event.{kind}` with `session.id=<channel-id>`, `agent.id=<author>`, `openinference.span.kind=AGENT`, `o2r.channel.*`, `input.value=<payload>` so the event lights up in Phoenix / Tempo alongside A2A traces.
- **Backend-agnostic**: `make_router(...)` accepts a `pool_provider`, optional `auth_dependency`, and `base_url` so any FastAPI app can mount the router.

## Tempo + Grafana integration

Exercise: `coily exec test-tempo-grafana`.

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

- **Multi-agent choreography**: orchestrator + planner + validator + deployer + eight transient workers. Builds an AURORA microsite from NASA imagery.
- **Real validation steps**: HTML5 parsing, `<h1>` count, image alt-text checks, internal link resolution, word and image counts.
- **Intentional failure modes**: worker-d crashes (exit 1), worker-g attempts a topology bypass and is rejected with `-32010`. Exercises the failure-class taxonomy.
- **Frozen timestamps** via `LUCA_FREEZE_TIME` for byte-snapshotted output.
- **Backend-agnostic**: runs against any OTLP/HTTP collector.
- **Span shape conventions**:
  - `orchestrator.flow` (long-lived root)
  - `orchestrator.step.<n>` (per-step subtrees)
  - `orchestrator.acceptance` (decision + reason + criterion + score)

## See also

- [README.md](../README.md) - human-facing intro and quickstart.
- [AGENTS.md](../AGENTS.md) - agent-facing operating rules.
- [.coily/coily.yaml](../.coily/coily.yaml) - allowlisted commands. Agents route through coily, not bare `make` / `uv` / `python`.

Cross-reference convention from [coilysiren/coilyco-ai#313](https://github.com/coilysiren/coilyco-ai/issues/313). This repo is the worked example.
