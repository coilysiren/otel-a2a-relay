# Protocol v0

The relay's job: translate A2A wire traffic between agents into OTel spans, with no protocol changes visible to the agents themselves.

A2A is the agent-facing format. OTel is the persistence substrate. Agents never read raw spans. Drop the relay between two existing A2A agents and they coordinate normally, except every exchange is now a queryable trace.

This document is the v0 protocol shape. Validate it against a real Phoenix instance before writing relay code.

## Topology

Phoenix-only OTLP/HTTP for v1. The relay process exports directly to Phoenix's collector port. No Tempo, no separate OTel Collector, no fan-out. Pluggability is a one-line endpoint swap, documented but not shipped.

## Sessions

`session.id = sha256("<repo>:<issue>")[:16]` for GitHub-issue-rooted channels. Deterministic, stable across reconnects, no collector-side coordination. Other transports (Slack thread, Linear ticket) get their own deterministic derivation. The relay never mints session IDs server-side.

One session groups many traces. Each trace is one agent's burst.

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
a2a.task.id:         T
a2a.task.state:      working   # updated to terminal state at span end
links:               [Trace 1's a2a.client.send span]
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

The terminal completion message is upgraded to a child span so it shows up as a node in the Agent Graph and Phoenix's message timeline:

```
name:                a2a.message.send
openinference.span.kind: LLM
parent:              a2a.task
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
a2a.method:          tasks/get   # or implicit on stream-close
a2a.task.id:         T
links:               [Trace 2's a2a.task span]
```

A's downstream processing of the result lives as children here. Out of scope for the relay.

## Conventions

- **Agent Cards live as resource attributes** on every span the relay emits on an agent's behalf. The relay caches each agent's card and attaches `agent.id` / `agent.name` / `agent.version` / `agent.capabilities` as resource-level attributes on the OTel `Resource` scoping that agent's spans. No separate registry. Card fetches at session start are recorded as a one-shot `a2a.agent.card.fetch` span on the relay's own service trace, not in the session trace.
- **Task = one root span**, lifetime = task lifetime, state in events. Not one trace per task. Multiple tasks in the same session share `session.id` and link to each other.
- **Messages = mixed.** Content-bearing initial sends and final completions are spans (LLM kind). Streaming chunks and protocol-level state pings are span events. Rule of thumb: if it would render as a node in the Agent Graph, it is a span. If it would render as a tick on a timeline, it is an event.
- **Streaming and sync share span shape.** Sync is the degenerate case where the task span opens, fires one `stream_chunk` event with `final: true`, ends with a child completion span. The relay does not branch on sync vs stream at the span layer.

## Phoenix UI sanity check

Mentally simulated against Phoenix's current views:

- Sessions tab: one row per `session.id`, three traces under it, agents A and B both visible.
- Agent Graph: nodes A and B, directed edge A -> B from the link on Trace 2 -> Trace 1, return edge B -> A from Trace 3 -> Trace 2. Edge labels = task IDs.
- Trace tree (Trace 2): `a2a.task` root, AGENT-kind. Inline events for state changes and stream chunks. Child `a2a.message.send` LLM span at the end with the final output.
- TraceQL-style filter "all spans where `session.id = <S> and agent.id = B`" returns exactly B's contributions. Cross-agent join falls out of `session.id` alone.

If any of the above does not render as expected against a real Phoenix instance, the v1 plan backs up. Build a one-page harness that posts these exact spans via OTLP/HTTP to a local Phoenix and screenshot the three views before writing the relay.

## Operator surface

`coily channel <verb>` lives in the `coily` repo and talks A2A to a relay. Verbs: `send`, `stream`, `tasks-get`, `tasks-cancel`, `view`. Inherits the audit + gate wrapper pattern. The relay itself ships only a `serve` mode.

## Sequencing

1. This repo exists with v0 protocol doc. (Done.)
2. Phoenix harness: one Python file, posts the worked-example spans via OTLP/HTTP to a local Phoenix, exits. Confirms the three UI views render as described.
3. Implement the relay around the verified shape.
4. `coily channel` ships after the relay has a `serve` mode reachable on the homelab.

Steps 1 and 2 are unblocked. Step 3 is blocked on step 2 passing. Step 4 is blocked on step 3.
