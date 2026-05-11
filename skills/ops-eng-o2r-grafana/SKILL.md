---
name: "ops-eng-o2r-grafana"
description: "Use when working with the Tempo + Grafana backend for otel-a2a-relay (o2r). Names the specific Grafana surface for each question (overview vs LUCA-flow vs Tempo Explore vs service graph), with direct dashboard URLs, TraceQL snippets, and the dockerized stack lifecycle. Triggers - grafana, tempo, o2r grafana, o2r tempo, o2r-overview, luca-flow dashboard, traceql, service graph, tempo explore, span metrics, o2r-tempo-harness, tempo-up."
---

# Tempo + Grafana backend for o2r

Local stack runs at `http://localhost:3000` (Grafana). Tempo accepts OTLP/HTTP on `:4318` and serves the query API on `:3200`. Prometheus is on `:9090` for span-metrics and service-graph.

Repo: [otel-a2a-relay/tempo_grafana/](https://github.com/coilysiren/otel-a2a-relay/tree/main/tempo_grafana). Docker stack: `tempo_grafana/docker/docker-compose.yml`.

## Which Grafana surface answers which question

Default to the provisioned dashboards. Tempo Explore is for ad-hoc TraceQL.

- **"Show me overall health"** - **o2r-overview** dashboard (Grafana home). http://localhost:3000/d/o2r-overview/o2r-overview. Agent topology, span rate, p95 latency, error rate, recent error traces, TraceQL cheatsheet panel.
- **"Show me one session's flow"** - **LUCA-flow** dashboard. http://localhost:3000/d/luca-flow/luca-flow. `session_id` variable at the top, switch to repivot. Waterfall, per-step latency table, acceptance-decision tally, recent runs list.
- **"Show me the visual parent/child waterfall for one trace"** - Click any trace row from the dashboard (recent errors, recent luca-flow runs) or paste a trace ID in Tempo Explore. Grafana renders the timeline waterfall on the trace detail panel.
- **"Show me the agent topology"** - Service-graph node view. http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22,%22queries%22:%5B%7B%22queryType%22:%22serviceMap%22%7D%5D%7D. Nodes are services, edges from CLIENT/SERVER span pairing.
- **"Let me write TraceQL"** - **Tempo Explore**. http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22%7D. Cheatsheet in the o2r-overview dashboard.
- **"Let me write PromQL on span metrics"** - direct Prometheus UI. http://localhost:9090. Or Grafana Explore with Prometheus datasource.

## Operate

From `otel-a2a-relay/` workspace root:

```sh
make tempo-up                                              # docker compose stack
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make luca-demo
open http://localhost:3000                                 # lands on o2r-overview
make tempo-down                                            # stop, preserve volumes
make tempo-clean                                           # stop + wipe volumes
```

`make tempo-up` brings up Tempo 2.6.1, Prometheus 2.55.1, Grafana 11.3.1 with two provisioned datasources and two provisioned dashboards. Anonymous login is on for the dev stack.

## CLI

- `o2r-tempo-harness` - posts the worked-example trace, waits for Tempo to index it, prints the direct Grafana Explore deep-link. Use this to validate the stack came up clean.

## TraceQL cheatsheet

Paste into Tempo Explore.

```traceql
{ trace:duration > 2s }                                                  # slow traces
{ status = error }                                                       # error traces
{ resource.service.name = "luca-relay" && status = error }               # per-agent errors
{ span.session.id = "luca-aurora-XXXX" }                                 # one session
{ span.a2a.method = "message/send" }                                     # A2A method calls
{ span.agent.role = "worker" } >> { span.agent.role = "validator" }      # parent-child
{ name = "orchestrator.acceptance" && span.o2r.step.acceptance.decision = "crashed" }
{ resource.service.name = "luca-relay" } | avg(span:duration) > 50ms     # latency aggregate
{ } | rate() by (span.agent.role)                                        # TraceQL metrics
{ } | quantile_over_time(span:duration, .95) by (resource.service.name)
```

TraceQL metrics queries need `local-blocks` flush (on by default in this stack).

## What the dashboards show

### o2r-overview (default home)

- Agent topology node-graph from `traces_service_graph_request_total`.
- Span rate (5m), error rate (5m). luca-aurora deliberately produces ~12.5% errors.
- p95 span latency by name (histogram quantile). Click exemplar dots to drill into the offending trace.
- Span call rate by `agent.role`.
- Recent error traces (live TraceQL `{ status = error }`).
- TraceQL cheatsheet markdown panel.

### LUCA-flow

- `session_id` variable populated from `{ name = "orchestrator.flow" } | by(span.session.id)`.
- orchestrator.flow waterfall for the active session. Click bars to expand the trace tree (orchestrator.flow -> orchestrator.step.<n> -> dispatch + validate + accept).
- Per-step latency table.
- Per-step acceptance decisions (decision, criterion, actor, specialization).
- Stat panels: accepted (luca expects 5), crashed (1, worker-d), rogue-rejected (1, worker-g), needs-followup (1, worker-b).
- Recent luca-flow runs across all sessions.

## Endpoint map

* Grafana home - http://localhost:3000 - lands on o2r-overview
* o2r-overview - http://localhost:3000/d/o2r-overview/o2r-overview - health view
* LUCA-flow - http://localhost:3000/d/luca-flow/luca-flow - per-session detail
* Tempo Explore - http://localhost:3000/explore - TraceQL playground
* Service Graph - http://localhost:3000/explore (queryType=serviceMap) - agent topology
* Tempo OTLP/HTTP - http://localhost:4318 - relay sends here
* Tempo query API - http://localhost:3200 - Grafana's datasource talks to this
* Prometheus - http://localhost:9090 - direct PromQL

## Configuration knobs

- Block retention - 168h (7 days) in `tempo.yaml`. Bump for longer history; local volume storage.
- Service-graph wait window - 60s. Pairs CLIENT and SERVER spans. luca-flow runs ~15s. If demo length grows, bump this.
- `metrics_generator.processor.span_metrics.dimensions` - `agent.role`, `session.id`, `a2a.method`. Adding more increases cardinality.
- Anonymous Grafana login - on. UI changes do not persist across container restarts unless committed back to `grafana/dashboards/`.
- Default home dashboard - `o2r-overview`. Override via `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH`.

## Common traps

- **Wrong port.** Tempo is `:4318`, Phoenix is `:6006`. Same OTLP/HTTP protocol, different backend. If spans are not appearing, check `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Empty service graph.** Service-graph requires CLIENT/SERVER span kind pairs within the 60s wait window. If the demo run is too short or kinds are not set, the graph stays empty.
- **Dashboard edits gone after restart.** Anonymous Grafana session edits do not persist. Commit dashboard JSON back to `grafana/dashboards/` to keep changes.
- **No metrics in Prometheus.** Tempo's `metrics_generator` must be reachable from Prometheus via remote_write. If `:9090/api/v1/write` is not getting traffic, span-metrics panels stay flat.
- **Volumes wiped.** `make tempo-clean` removes the volume. Use `make tempo-down` to stop while preserving trace history.
