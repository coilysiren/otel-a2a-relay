# Protocol v0.4

The relay's job: translate agent-to-agent activity into OTel spans, with no protocol changes visible to the agents themselves.

The persistence substrate is OTel spans. The wire format implemented today is [A2A](https://a2a-protocol.org/latest/specification/). The spec is shaped so other wire formats (and the Agent Channel coordination layer documented in [channels-protocol.md](channels-protocol.md), implemented in the [`channels/`](../channels/) package) map onto the same span / session / graph shape. Agents never read raw spans. Drop the relay between two existing agent peers and they coordinate normally, except every exchange is now a queryable trace.

Companion docs: [protocol-traces.md](protocol-traces.md) for the worked three-trace example, [protocol-conventions.md](protocol-conventions.md) for span conventions and bootstrap, [protocol-validation.md](protocol-validation.md) for what Phoenix verified, [protocol-attributes.md](protocol-attributes.md) for the attribute registry, [protocol-operator.md](protocol-operator.md) for the operator surface and out-of-protocol endpoints.

## What v0.4 changes

v0.4 retires the colony / multi-tenant framing from `tracing.bootstrap()` (see [otel-a2a-relay#121](https://github.com/coilyco-flight-deck/otel-a2a-relay/issues/121)) to align with the local-only substrate shape that luca adopted on 2026-05-12:

- **`<namespace>.colony` resource attribute renamed to `<namespace>.deployment`.** The old key encoded a per-colony multi-tenant deployment that is not a real use case for a local-only substrate.
- **`product_area` parameter dropped.** Was the "hard-boundary slice within a deployment" knob - a per-tenant routing concept that does not exist in the local-only shape. Phoenix project name is now derived from `<deployment>` alone.
- **Bootstrap docstring de-coloned.** No more "enterprise install" / "colony-defined" language.

## Topology

Phoenix-only OTLP/HTTP for v1. The relay process exports directly to Phoenix's collector port. No Tempo, no separate OTel Collector, no fan-out. Pluggability is a one-line endpoint swap, documented but not shipped.

One TracerProvider per relay process. Agent identity rides on span attributes, not on the Resource. (See [protocol-validation.md](protocol-validation.md), finding 1.)

## Sessions

`session.id = sha256("<repo>:<issue>")[:16]` for GitHub-issue-rooted channels. Deterministic, stable across reconnects, no collector-side coordination. Other transports (Slack thread, Linear ticket) get their own deterministic derivation. The relay never mints session IDs server-side.

One session groups many traces. Each trace is one agent's burst.

## Agent Graph

Phoenix's Agent Graph view consumes OpenInference's explicit graph attributes, not span links. The relay synthesizes them from the A2A peer relationship and attaches them to each root span:

- `graph.node.id` - the acting agent's identity for graph rendering. Default: `<agent_id>`. Use `<agent_id>:<task_id>` if you need per-task nodes.
- `graph.node.parent_id` - the upstream agent in the handoff chain (set on B's `a2a.task` root when triggered by A; unset on the originating burst).

Span links can still be emitted as a secondary signal for OTel-native consumers that read them (Tempo, Jaeger). They are not load-bearing for Phoenix and are treated as informational only.
