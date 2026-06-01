# 🔁🔗🤖 otel-a2a-relay (o2r)

Agent activity as [OTel](https://opentelemetry.io/) spans. The persistence layer is the legible thing: every agent message, handoff, and task transition becomes a queryable trace any OTel-native observability tool can render. [A2A](https://a2a-protocol.org/latest/specification/) is the supported wire format today. The session derivation generalizes to any transport-keyed channel (GitHub issue, Slack thread, Linear ticket).

`otel-a2a-relay` is the canonical name. `o2r` is the dictation-friendly shortname used in CLI entrypoints (`o2r`, `o2r-harness`), span identifiers (`service.name=o2r`), and prose.

![Animated session topology: a hot-pink relay hub at the center, two agent leaves on either side, a particle traveling along the arc that connects them, faint trails of past hops fading behind it](assets/session-topology.gif)

A real session, animated. Magenta hub is the relay; particles are A2A hops from real Phoenix spans. Generate your own with `make demo && make gif CTX=demo`. Renderer details: [docs/animated-topology.md](docs/animated-topology.md).

## Pitch

Agent peers coordinate through this relay. Every message becomes one or more OTel spans, exported via [OTLP/HTTP](https://opentelemetry.io/docs/specs/otlp/) to whatever you've pointed `OTEL_EXPORTER_OTLP_ENDPOINT` at. The trace IS the operations view, no derived state needed.

Two coordination shapes share one span schema:

1. **A2A wire format** - JSON-RPC 2.0 over HTTP translated into traces, including a deterministic `sha256(<repo>:<issue>)` session id for any GitHub-issue-rooted coordination.
2. **Agent Channel** - Postgres-backed coordination with 4-character dictatable ids, an append-only event log, and self-describing onboarding. Spec: [`docs/channels-protocol.md`](docs/channels-protocol.md). Origin: pre-migration coilyco-ai design work, now folded into this repo.

Trace propagation is [W3C `traceparent`](https://www.w3.org/TR/trace-context/) end-to-end. Default visualizer: [Phoenix](https://github.com/Arize-ai/phoenix). Anything OTLP-native works.

## Workspace layout

This repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with a backend-agnostic core and per-backend extensions.

- `otel-a2a-relay-core` - relay HTTP server, `tracing.bootstrap()`, echo peer, in-memory task store.
- `otel-a2a-relay-channels` - Agent Channel coordination layer (FastAPI + Postgres).
- `otel-a2a-relay-arize-phoenix` - Phoenix harness, query helpers, GIF renderer.
- `otel-a2a-relay-tempo-grafana` - Tempo + Grafana stack with provisioned dashboards.
- `luca-flow` - the AURORA microsite multi-agent demo, backend-agnostic.

## Quickstart

```sh
uv sync --all-packages
make phoenix-up
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 make luca-demo
python -m webbrowser http://localhost:6006
```

Tempo + Grafana, other backends, the topology diagram, methods, and span shape: [docs/quickstart.md](docs/quickstart.md). The full demo writeup: [docs/luca-flow-demo.md](docs/luca-flow-demo.md).

## Related

Operator CLI: [`coily channel`](https://github.com/coilyco-bridge/coily) once that side catches up. Origin discussion: pre-migration coilyco-ai design work, now folded into this repo.

## See also

- [AGENTS.md](AGENTS.md) - agent-facing operating rules.
- [docs/FEATURES.md](docs/FEATURES.md) - inventory of what ships today.
- [.coily/coily.yaml](.coily/coily.yaml) - allowlisted commands. Agents route through coily, not bare `make` / `uv` / `python`.

Cross-reference convention from [coilysiren/agentic-os#59](https://github.com/coilyco-flight-deck/agentic-os/issues/59).

## License

MIT.
