# Protocol v0.1

The relay's job: translate A2A wire traffic between agents into OTel spans, with no protocol changes visible to the agents themselves.

A2A is the agent-facing format. OTel is the persistence substrate. Agents never read raw spans. Drop the relay between two existing A2A agents and they coordinate normally, except every exchange is now a queryable trace.

This document is the v0.1 protocol shape. v0 was rewritten after a real Phoenix harness run surfaced two findings: Phoenix drops OTel `Resource` attributes, and Phoenix does not expose span links via its API. See ["Phoenix-validated"](#phoenix-validated) below for which v0 claims survived and which were rewritten.

## Topology

Phoenix-only OTLP/HTTP for v1. The relay process exports directly to Phoenix's collector port. No Tempo, no separate OTel Collector, no fan-out. Pluggability is a one-line endpoint swap, documented but not shipped.

One TracerProvider per relay process. Agent identity rides on span attributes, not on the Resource. (See finding 1.)

## Sessions

`session.id = sha256("<repo>:<issue>")[:16]` for GitHub-issue-rooted channels. Deterministic, stable across reconnects, no collector-side coordination. Other transports (Slack thread, Linear ticket) get their own deterministic derivation. The relay never mints session IDs server-side.

One session groups many traces. Each trace is one agent's burst.

## Agent Graph

Phoenix's Agent Graph view consumes OpenInference's explicit graph attributes, not span links. The relay synthesizes them from the A2A peer relationship and attaches them to each root span:

- `graph.node.id` - the acting agent's identity for graph rendering. Default: `<agent_id>`. Use `<agent_id>:<task_id>` if you need per-task nodes.
- `graph.node.parent_id` - the upstream agent in the handoff chain (set on B's `a2a.task` root when triggered by A; unset on the originating burst).

Span links can still be emitted as a secondary signal for OTel-native consumers that read them (Tempo, Jaeger). They are not load-bearing for Phoenix and are treated as informational only.

## Worked example: A streams a task to B, B completes, A acks

Three traces, one session. Task ID `T` is A2A-native, minted by the relay when `message/stream` is called.

### Trace 1: A's outgoing burst (CLIENT side)

Root span `a2a.client.send`:

```
name:                a2a.client.send
openinference.span.kind: AGENT
session.id:          <S>
agent.id:            A
agent.name:          <from A's Agent Card>
graph.node.id:       A
peer.agent.id:       B
a2a.method:          message/stream
a2a.task.id:         T
rpc.system:          jsonrpc
rpc.service:         a2a
rpc.method:          message/stream
```

Child span `a2a.message.send` for the actual outgoing payload:

```
name:                a2a.message.send
openinference.span.kind: LLM   # if the message is model output
                               # else AGENT
agent.id:            A
input.value:         <message.parts as JSON>
input.mime_type:     application/json
```

Trace ends when the JSON-RPC call returns the task handle. Streaming continues in Trace 2.

### Trace 2: B's task execution (AGENT side, the meat)

Root span `a2a.task`. Lifetime = task lifetime.

```
name:                a2a.task
openinference.span.kind: AGENT
session.id:          <S>
agent.id:            B
agent.name:          <from B's Agent Card>
graph.node.id:       B
graph.node.parent_id: A
a2a.task.id:         T
a2a.task.state:      working   # updated to terminal state at span end
```

State changes are span events, not separate spans:

```
event: a2a.task.state_change   { from: submitted, to: working,   ts: ... }
event: a2a.task.state_change   { from: working,   to: completed, ts: ... }
```

Streaming chunks. Each SSE frame from B back to A is a span event on the task span:

```
event: a2a.message.stream_chunk
       { seq: 0, message.role: agent, parts: [...], final: false }
event: a2a.message.stream_chunk
       { seq: 1, ..., final: false }
event: a2a.message.stream_chunk
       { seq: 2, ..., final: true }
```

Rationale for events-not-spans on chunks: a 200-token streaming response is 200 spans of structural noise that obscure the Agent Graph. Events keep the chunk timeline queryable without polluting the trace tree. Phoenix renders span events inline.

The terminal completion message is upgraded to a child span so it shows up as a node in the trace tree and Phoenix's message timeline:

```
name:                a2a.message.send
openinference.span.kind: LLM
parent:              a2a.task
agent.id:            B
output.value:        <final message.parts as JSON>
output.mime_type:    application/json
```

Span ends. `a2a.task.state` is set to terminal at end. Status code OK on `completed`, ERROR on `failed` or `canceled`.

### Trace 3: A's read / ack burst

Root span `a2a.client.recv`:

```
name:                a2a.client.recv
openinference.span.kind: AGENT
session.id:          <S>
agent.id:            A
graph.node.id:       A
graph.node.parent_id: B
a2a.method:          tasks/get   # or implicit on stream-close
a2a.task.id:         T
```

A's downstream processing of the result lives as children here. Out of scope for the relay.

## Conventions

- **Agent identity = span-level attributes.** Every span the relay emits on agent X's behalf carries `agent.id`, `agent.name`, and the graph attributes redundantly. Phoenix does not surface `Resource` attributes, so they cannot live there. The relay's own `service.name` is fine on the Resource because it never needs to be queryable per-span.
- **Task = one root span**, lifetime = task lifetime, state in events. Not one trace per task. Multiple tasks in the same session share `session.id`.
- **Messages = mixed.** Content-bearing initial sends and final completions are spans (LLM kind). Streaming chunks and protocol-level state pings are span events. Rule of thumb: if it would render as a node in the trace tree, it is a span. If it would render as a tick on a timeline, it is an event.
- **Streaming and sync share span shape.** Sync is the degenerate case where the task span opens, fires one `stream_chunk` event with `final: true`, ends with a child completion span. The relay does not branch on sync vs stream at the span layer.
- **Topology = `graph.node.*` attributes**, not span links. Span links may be emitted alongside but are not load-bearing.

## Phoenix-validated

Run against Phoenix platform v15.4.0 via `phoenix serve` + the `harness/` posting the worked example. What the harness confirmed:

- `session.id` flows correctly. Sessions tab groups traces as expected.
- `openinference.span.kind` drives the rendered span kind (AGENT / LLM).
- Span events render under their parent span without polluting the trace tree.
- Three-traces-per-session topology works, multiple AGENT-kind roots under one session.
- Span event attributes (state changes, stream-chunk seq + final) all preserved.

What the harness rewrote in v0:

- **Resource attributes are not exposed by Phoenix.** Agent identity must live on spans, not on the Resource. v0 specified the opposite. v0.1 fixes it.
- **Span links are not exposed by Phoenix.** v0 used links for cross-trace topology. v0.1 uses `graph.node.id` / `graph.node.parent_id` instead.

If a future Phoenix release changes either of these, the spec backs up again.

## Operator surface

`coily channel <verb>` lives in the `coily` repo and talks A2A to a relay. Verbs: `send`, `stream`, `tasks-get`, `tasks-cancel`, `view`. Inherits the audit + gate wrapper pattern. The relay itself ships only a `serve` mode.

## Sequencing

1. v0.1 protocol doc + harness updated and re-validated against Phoenix. (This commit.)
2. Implement the relay around the verified shape.
3. `coily channel` ships after the relay has a `serve` mode reachable on the homelab.
