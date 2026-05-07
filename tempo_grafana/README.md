# otel-a2a-relay-tempo-grafana

Tempo + Grafana backend extension for `otel-a2a-relay-core`. Adds:

- `o2r-tempo-harness` - posts the worked-example trace and waits for Tempo to index it, prints the direct Grafana Explore link.
- `otel_a2a_relay_tempo_grafana.bootstrap` - tiny helper around `tracing.bootstrap()` that defaults `OTEL_EXPORTER_OTLP_ENDPOINT` to the local Tempo port (4318).
- `docker/docker-compose.yml` - dockerized Tempo + Grafana stack, with a provisioned Tempo datasource and an auto-loaded LUCA-flow dashboard.

## Quick start

```sh
make tempo-up                                              # boot Tempo + Grafana (workspace root)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run --package otel-a2a-relay-tempo-grafana o2r-tempo-harness
open "http://localhost:3000/d/luca-flow/luca-flow"        # waterfall + per-step latency
make tempo-down                                            # stop (preserves data)
```

Sibling: `otel-a2a-relay-arize-phoenix` for Arize Phoenix.
