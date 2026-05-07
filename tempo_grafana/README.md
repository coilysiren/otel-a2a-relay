# otel-a2a-relay-tempo-grafana

Tempo + Grafana backend extension for `otel-a2a-relay-core`. Adds:

- `o2r-tempo-harness` - posts the worked-example trace and waits for Tempo to index it, prints the direct Grafana Explore link.
- `otel_a2a_relay_tempo_grafana.bootstrap` - thin wrapper around `tracing.bootstrap()` that defaults `OTEL_EXPORTER_OTLP_ENDPOINT` to the local Tempo port (4318).
- `docker/docker-compose.yml` - dockerized **Tempo + Prometheus + Grafana** stack. Tempo's `metrics_generator` ships span-metrics and service-graph metrics into Prometheus via remote_write; Grafana consumes both. Two dashboards auto-load:
  - **o2r-overview** (default home): live agent topology (service graph), span rate / p95 latency / error rate, recent error traces, TraceQL cheatsheet.
  - **LUCA-flow**: per-session waterfall, per-step latency table, per-acceptance-decision tally, drill-down by `session.id`.

## Quick start

```sh
make tempo-up                                              # workspace root
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make luca-demo
open http://localhost:3000                                 # auto-lands on o2r-overview
make tempo-down                                            # stop, preserve data
make tempo-clean                                           # stop + wipe volumes
```

## Lifecycle

The stack is three services:

- **Tempo** (2.6.1): traces backend. OTLP/HTTP on `4318`, query API on `3200`.
- **Prometheus** (2.55.1): receives Tempo's span-metrics + service-graph remote_write on `9090/api/v1/write`. Also scrapes Tempo's `/metrics` for self-observability.
- **Grafana** (11.3.1): UI on `3000`. Two provisioned datasources (Tempo + Prometheus), two provisioned dashboards.

| Endpoint | URL | Purpose |
| --- | --- | --- |
| Grafana home | http://localhost:3000 | lands on o2r-overview |
| LUCA-flow dashboard | http://localhost:3000/d/luca-flow/luca-flow | per-session detail |
| Tempo Explore | http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22%7D | TraceQL playground |
| Service Graph tab | http://localhost:3000/explore?left=%7B%22datasource%22:%22tempo%22,%22queries%22:%5B%7B%22queryType%22:%22serviceMap%22%7D%5D%7D | agent topology |
| Tempo OTLP/HTTP | http://localhost:4318 | where the relay sends |
| Tempo query API | http://localhost:3200 | Grafana's datasource talks to this |
| Prometheus | http://localhost:9090 | direct PromQL UI |

## What the dashboards show

### o2r-overview

- **Agent topology** (node-graph from `traces_service_graph_request_total`). Edges are relay forwards; node size scales with span count.
- **Span rate** (last 5m) and **error rate** (5m, fraction with `status=error`). luca-aurora deliberately produces ~12.5% errors (worker-d crash + worker-g topology violation), so green at low error count = real failure modes are getting caught.
- **p95 span latency by name** (Prometheus histogram quantile). Click an exemplar dot (orange diamonds) to drill into the trace that caused the spike.
- **Span call rate by agent role** (per-role span throughput; `relay` and `orchestrator` should always dominate).
- **Recent error traces** (live TraceQL `{ status = error }`, click any row for the waterfall).
- **TraceQL cheatsheet** (markdown panel; copy-paste into Tempo Explore).

### LUCA-flow

- **`session_id` variable** at the top, populated from `{ name = "orchestrator.flow" } | by(span.session.id)`. Switch sessions to repivot every panel.
- **orchestrator.flow waterfall** for the active session. Click any bar to expand the trace tree: `orchestrator.flow` -> `orchestrator.step.<n>` -> dispatch + validate + accept subtrees.
- **Per-step latency table** (one row per `orchestrator.step.<n>` span, sorted by duration).
- **Per-step acceptance decisions table** (decision + criterion + actor + specialization).
- **Stat panels**: steps accepted (luca expects 5), crashed (1, worker-d), rogue-rejected (1, worker-g), needs-followup (1, worker-b). Color thresholds line up with the expected luca-aurora flow shape.
- **Recent luca-flow runs** trace list across all sessions.

## TraceQL cheatsheet

Copy into Tempo Explore -> TraceQL editor.

```traceql
# Slow traces
{ trace:duration > 2s }

# Error traces
{ status = error }

# Per-agent errors
{ resource.service.name = "luca-relay" && status = error }

# One session
{ span.session.id = "luca-aurora-XXXX" }

# A2A method calls
{ span.a2a.method = "message/send" }

# Worker -> validator chains (parent-child)
{ span.agent.role = "worker" } >> { span.agent.role = "validator" }

# All crashes for a session
{ name = "orchestrator.acceptance" && span.o2r.step.acceptance.decision = "crashed" }

# Latency aggregate
{ resource.service.name = "luca-relay" } | avg(span:duration) > 50ms

# TraceQL metrics queries (need `local-blocks` flush, on by default in this stack)
{ resource.service.name = "luca-relay" } | rate() by (span.agent.role)
{ } | quantile_over_time(span:duration, .95) by (resource.service.name)
```

## Configuration knobs

- **Block retention**: 168h (7 days) in `tempo.yaml`. Bump if you need longer trace history; storage is local volume.
- **Service-graph wait window**: 60s. The processor pairs CLIENT and SERVER spans within this window. luca-flow runs ~15s, so 60s gives headroom; if you change the demo length, bump this too.
- **`metrics_generator.processor.span_metrics.dimensions`**: currently `agent.role`, `session.id`, `a2a.method`. Add more to slice differently in Prometheus; each adds cardinality, so think before piling on.
- **Anonymous Grafana login**: on for the dev stack. The dashboards are still editable; UI changes won't persist across container restarts unless you commit JSON updates back to `grafana/dashboards/`.
- **Default home dashboard**: `o2r-overview`. Override via `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH` env in `docker-compose.yml`.

## Why Prometheus is in the loop

Tempo's `metrics_generator` produces two metric streams from spans:

- **span-metrics**: `traces_spanmetrics_calls_total`, `traces_spanmetrics_latency_bucket` (per-span rate / latency / error histograms).
- **service-graph**: `traces_service_graph_request_total`, `traces_service_graph_request_failed_total`, `traces_service_graph_request_{client,server}_seconds_*` (edges between services with rate / error / duration).

These metrics are *not* served by Tempo itself; Tempo only does remote_write. Without a Prometheus-compatible store, the metrics are computed and dropped. The bundled Prometheus exists to receive them so Grafana panels can query span-metrics + the service graph.

If you swap in Mimir or a remote Prometheus, change `tempo.yaml`'s `storage.remote_write[0].url` and the Grafana `Prometheus` datasource URL together.

## Known quirks

- **Service graph appears empty for ~60s after a fresh `make tempo-up`**: the generator's pairing window is 60s and it flushes on close. Run a luca-demo, wait a minute, refresh.
- **Some service-graph edges show `connection_type=virtual_node`**: those are spans where Tempo could not pair a CLIENT side with the SERVER. Currently the orchestrator's HTTP calls into the relay don't emit an explicit CLIENT span (just `httpx.post()`), so the relay's `a2a.task` SERVER span has no peer; Tempo synthesizes a `virtual_node` for the user-side. Wiring an explicit CLIENT span around `_send_via_relay` would fix this; see [otel-a2a-relay#XX](https://github.com/coilysiren/otel-a2a-relay/issues) (TODO file when surfaced).
- **The relay shows up as `o2r` in the service graph, not `relay`**: the relay's `service.name` resource attribute is the protocol-canonical `o2r`. The per-span `agent.role` attribute is `relay`; that one's available for filtering and shows up on `spanBar`.

## Sibling

[`otel-a2a-relay-arize-phoenix`](../arize_phoenix/) is the other backend extension. Both implement the same protocol shape; the LUCA-flow demo runs against either.
