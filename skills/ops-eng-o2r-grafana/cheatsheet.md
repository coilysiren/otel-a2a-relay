# TraceQL, endpoints, config knobs, common traps

Companion to [SKILL.md](SKILL.md). Tactical reference content moved here so the skill core stays under cap.

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
