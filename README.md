# otel-a2a-relay

A2A coordination as OTel spans. Drop-in relay between A2A agents that turns wire traffic into traces any OTel-native observability tool can render.

## Pitch

Two A2A agents talk to each other through this relay. Every message becomes one or more OTel spans, exported via OTLP/HTTP to whatever you've pointed `OTEL_EXPORTER_OTLP_ENDPOINT` at. The trace IS the operations view, no derived state needed.

- Agent-facing format: A2A (JSON-RPC 2.0 over HTTP, AgentCards, `message/send`, `tasks/get`, `tasks/cancel`).
- Relay-persistence format: OTel spans, OpenInference attributes for Phoenix's Agent Graph and Sessions views.
- Trace propagation: W3C `traceparent` end-to-end. Client → relay → peer is one trace.
- Default visualizer: [Phoenix](https://github.com/Arize-ai/phoenix). Anything OTLP-native works.

## Quickstart (dogfood loop)

Phoenix is operator-owned, so start it once in its own terminal:

```sh
uv sync
make phoenix-fg
```

In another terminal, bring up the relay + two echo agents:

```sh
make up
```

`make up` starts agent A on `:9001`, agent B on `:9002`, the relay on `:8080`, waits for `/healthz` on each, and prints a status line. Logs land in `logs/<service>.log`.

End-to-end smoke:

```sh
make send AS=A TO=B CTX=demo MSG="hello B"
make send AS=B TO=A CTX=demo MSG="hi A"
make view CTX=demo
```

`view` reduces Phoenix spans for one session into a single readable transcript:

```
[A] a2a.client.send task=t-d2d508 kind=AGENT
  in: hello B
[A->relay] a2a.task task=t-d2d508 kind=AGENT state=completed
[relay] a2a.relay.forward task=t-d2d508 kind=AGENT
[A->B] a2a.task task=t-d2d508 kind=AGENT state=completed
  in: hello B
  out: echo from B: hello B
```

`make demo` restarts everything and runs both directions in one shot.

## Make targets

- `up` / `down` / `restart` / `status` / `wait` - lifecycle.
- `send AS=... TO=... CTX=... MSG="..."` - JSON-RPC `message/send` to the relay.
- `view CTX=...` - GraphQL-query Phoenix for spans tagged with `session.id == $CTX` and reduce.
- `get TASK=t-...` - `tasks/get`.
- `tasks` - list tasks the relay has indexed in memory.
- `cancel TASK=t-...` - `tasks/cancel` (emits an `a2a.task.cancel` span).
- `peers` - list the relay's configured peers + their AgentCards.
- `harness` - the original Phoenix protocol-validation harness.
- `phoenix-fg` / `clean-phoenix-db` - operator-side Phoenix lifecycle.
- `test` / `lint` / `tail-relay` / `tail-agent-a` / `tail-agent-b`.

## Topology

```
make send (client.py) ── HTTP/JSON-RPC ──▶  relay (:8080)
        │                                       │ peers={A:9001, B:9002}
        │ a2a.client.send (CLIENT span)         │ a2a.task (SERVER span)
        │ traceparent injected ────────────────▶│ a2a.relay.forward (CLIENT span)
                                                │ traceparent injected
                                                ▼
                                       agent A or B (:9001/:9002)
                                       a2a.task (SERVER span, kind=AGENT)
```

The relay's peer registry comes from `OTEL_A2A_RELAY_PEERS=A=http://...,B=http://...`. The Makefile sets this for you. If a target in `metadata.agent.target` has no peer registered, the relay synthesizes a completed Task and skips the forward.

## Methods

- `message/send` - send a message, get a Task back. The originator sets `metadata.agent.id` (sender) and optionally `metadata.agent.target` (recipient).
- `tasks/get` - retrieve a Task by id from the relay's in-memory store. Each peer agent indexes its own tasks too.
- `tasks/cancel` - mark a Task as canceled and emit an `a2a.task.cancel` span.

The peer agent serves an A2A AgentCard at `/.well-known/agent.json` (capabilities, skills, protocol version). The relay's `GET /peers` aggregates them for discovery.

## Span shape

Every `a2a.task` carries `session.id`, `a2a.task.id`, `agent.id`, `graph.node.id`, `graph.node.parent_id`, `openinference.span.kind=AGENT`, plus `input.value` / `output.value` (OpenInference) and `a2a.message.text` / `a2a.message.reply_text` shortcuts. State changes are span events (`a2a.task.state_change` with `from` / `to`). Stream chunks are span events (`a2a.message.stream_chunk` with `seq` / `final`).

The original v0.1 protocol document at [`docs/protocol.md`](docs/protocol.md) is the precedent and explains why agent identity rides on attributes (Phoenix drops Resource attributes), why the Agent Graph uses `graph.node.*` (Phoenix doesn't expose span links), and why state changes are events not spans (tree noise vs queryable timeline).

## Layout

- `src/otel_a2a_relay/server.py` - the relay (FastAPI, JSON-RPC, peer routing, span emission).
- `src/otel_a2a_relay/agent.py` - tiny echo peer agent.
- `src/otel_a2a_relay/client.py` - dogfood CLI (`send`, `view`, `get`, `tasks`, `cancel`, `peers`).
- `src/otel_a2a_relay/store.py` - thread-safe in-memory task store.
- `src/otel_a2a_relay/telemetry.py` - one TracerProvider per process, OTLP/HTTP exporter.
- `src/otel_a2a_relay/harness.py` - the original Phoenix-validation harness, kept as a fixture.
- `scripts/bg.sh` - pidfile-backed background process manager.
- `scripts/wait-healthy.sh` - poll `/healthz` until 2xx.
- `Makefile` - thin wrapper over the above.

## Related

Operator CLI: [`coily channel`](https://github.com/coilysiren/coily) once that side catches up. Origin discussion: [coilysiren/coilyco-ai#24](https://github.com/coilysiren/coilyco-ai/issues/24).

## License

MIT.
