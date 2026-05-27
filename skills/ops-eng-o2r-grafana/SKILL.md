---
name: "ops-eng-o2r-grafana"
description: "Tempo + Grafana backend for otel-a2a-relay (o2r). Names the specific Grafana surface for each question. Triggers - grafana, tempo, o2r grafana, o2r-overview, luca-flow dashboard, traceql, service graph, tempo explore, span metrics, tempo-up."
---

# Tempo + Grafana backend for o2r

Local stack runs at `http://localhost:3000` (Grafana). Tempo accepts OTLP/HTTP on `:4318` and serves the query API on `:3200`. Prometheus is on `:9090` for span-metrics and service-graph.

Repo: [otel-a2a-relay/tempo_grafana/](https://github.com/coilysiren/otel-a2a-relay/tree/main/tempo_grafana). Docker stack: `tempo_grafana/docker/docker-compose.yml`.

Peer files in this skill folder: [dashboards.md](dashboards.md) (what each dashboard shows), [cheatsheet.md](cheatsheet.md) (TraceQL recipes + endpoint map + config knobs + common traps).

## Which Grafana surface answers which question

Default to the provisioned dashboards. Tempo Explore is for ad-hoc TraceQL.

- **"Show me overall health"** - **o2r-overview** dashboard (Grafana home). http://localhost:3000/d/o2r-overview/o2r-overview. Agent topology, span rate, p95 latency, error rate, recent error traces.
- **"Show me one session's flow"** - **LUCA-flow** dashboard. http://localhost:3000/d/luca-flow/luca-flow. `session_id` variable at the top, switch to repivot.
- **"Show me the visual parent/child waterfall for one trace"** - Click any trace row from a dashboard, or paste a trace ID in Tempo Explore. Grafana renders the timeline on the trace detail panel.
- **"Show me the agent topology"** - Service-graph node view in Tempo Explore (queryType=serviceMap). Nodes are services, edges from CLIENT/SERVER span pairing.
- **"Let me write TraceQL"** - **Tempo Explore**. http://localhost:3000/explore. See [cheatsheet.md](cheatsheet.md).
- **"Let me write PromQL on span metrics"** - direct Prometheus UI at http://localhost:9090.

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
