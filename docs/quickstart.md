# Quickstart

Pick a backend (or run both side by side - they coexist on different ports). All paths work identically through `core`'s `tracing.bootstrap()`.

## Phoenix backend

```sh
uv sync --all-packages
make phoenix-up                   # docker compose, always-on (or `make phoenix-fg` for foreground)
make phoenix-bootstrap            # one-time annotation configs + datasets
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 make luca-demo
python -m webbrowser http://localhost:6006   # Phoenix Sessions tab
```

## Tempo + Grafana backend

```sh
uv sync --all-packages
make tempo-up                     # docker compose Tempo + Grafana
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make luca-demo
python -m webbrowser http://localhost:3000/d/luca-flow/luca-flow
```

## Other backends

`tracing.bootstrap()` ships standard OTLP/HTTP - point it at Honeycomb, Datadog, or any OTel-native backend by setting `OTEL_EXPORTER_OTLP_ENDPOINT`. The protocol attributes (`session.id`, `agent.role`, `o2r.*`) work everywhere; backend-specific UX (annotation configs in Phoenix, dashboards in Grafana) is added by extension packages.

## Topology

![Relay topology, simplest case: one client, one relay, one peer, one trace](../assets/topology.png)

Simplest shape: one client, one relay, one peer, one trace. The [LUCA-flow demo](luca-flow-demo.md) runs eight workers, an orchestrator, a planner, a validator, and a deployer through this same relay, with star-topology enforcement, retries, a deliberate worker crash, and a rogue worker the relay gates.

The peer registry comes from `OTEL_A2A_RELAY_PEERS=A=http://...,B=http://...`. The Makefile sets this for you. If a target in `metadata.agent.target` has no peer registered, the relay synthesizes a completed Task and skips the forward.

Diagram source: [`scripts/render_topology.py`](../scripts/render_topology.py). Regenerate with `uv run --with matplotlib python scripts/render_topology.py`.

## Methods and span shape

Methods (`message/send`, `message/stream`, `tasks/get`, `tasks/cancel`) and the full attribute schema are specified in [protocol.md](protocol.md). The peer agent serves an AgentCard at `/.well-known/agent.json`; the relay's `GET /peers` aggregates them.

## See also

- [README.md](../README.md) - intro and the canonical pitch.
- [animated-topology.md](animated-topology.md) - the hero GIF and its renderer.
- [luca-flow-demo.md](luca-flow-demo.md) - the multi-agent dogfood.
