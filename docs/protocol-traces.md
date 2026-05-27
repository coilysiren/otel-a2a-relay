# Protocol worked example: A streams a task to B

Companion to [protocol.md](protocol.md). Three traces, one session. Task ID `T` is A2A-native, minted by the relay when `message/stream` is called.

## Trace 1: A's outgoing burst (CLIENT side)

Root span `a2a.client.send` with `openinference.span.kind=AGENT`, `session.id=<S>`, `agent.id=A`, `agent.name=<from Agent Card>`, `graph.node.id=A`, `peer.agent.id=B`, `o2r.method=message/stream`, `o2r.task.id=T`, plus standard `rpc.{system,service,method}` for jsonrpc/a2a/message/stream.

Child span `a2a.message.send` for the outgoing payload: `openinference.span.kind=LLM` (if model output, else AGENT), `agent.id=A`, `input.value=<message.parts JSON>`, `input.mime_type=application/json`.

Trace ends when the JSON-RPC call returns the task handle. Streaming continues in Trace 2.

## Trace 2: B's task execution (AGENT side, the meat)

Root span `a2a.task`. Lifetime = task lifetime. Attributes: `openinference.span.kind=AGENT`, `session.id=<S>`, `agent.id=B`, `agent.name=<from Agent Card>`, `graph.node.id=B`, `graph.node.parent_id=A`, `o2r.task.id=T`, `o2r.task.state=working` (updated to terminal state at span end).

State changes are span events, not separate spans:

```
event: o2r.task.state_change   { from: submitted, to: working,   ts: ... }
event: o2r.task.state_change   { from: working,   to: completed, ts: ... }
```

Streaming chunks. Each SSE frame from B back to A is a span event on the task span:

```
event: a2a.message.stream_chunk  { seq: 0, message.role: agent, parts: [...], final: false }
event: a2a.message.stream_chunk  { seq: 1, ..., final: false }
event: a2a.message.stream_chunk  { seq: 2, ..., final: true }
```

Rationale for events-not-spans on chunks: a 200-token streaming response is 200 spans of structural noise that obscure the Agent Graph. Events keep the chunk timeline queryable without polluting the trace tree. Phoenix renders span events inline.

The terminal completion message is upgraded to a child span (`a2a.message.send` with `openinference.span.kind=LLM`, parent `a2a.task`, `agent.id=B`, `output.value=<final message.parts JSON>`, `output.mime_type=application/json`) so it shows up as a node in the trace tree.

Span ends. `o2r.task.state` is set to terminal at end. Status code OK on `completed`, ERROR on `failed` or `canceled`.

## Trace 3: A's read / ack burst

Root span `a2a.client.recv` with `openinference.span.kind=AGENT`, `session.id=<S>`, `agent.id=A`, `graph.node.id=A`, `graph.node.parent_id=B`, `o2r.method=tasks/get` (or implicit on stream-close), `o2r.task.id=T`.

A's downstream processing of the result lives as children here. Out of scope for the relay.
