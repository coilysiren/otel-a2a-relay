# Phoenix harness

Validates the v0.1 protocol shape against a running Phoenix instance before any relay code lands.

Posts the [`protocol.md`](protocol.md) worked example (A streams a task to B, B completes, A acks) as three traces under one session via OTLP/HTTP, then exits.

## Run

```sh
uv sync
uv run phoenix serve &              # if no Phoenix is already up
uv run otel-a2a-relay-harness
```

Or via tasks:

```sh
invoke phoenix &                    # starts Phoenix in foreground
invoke harness                      # posts the worked example
```

Phoenix elsewhere:

```sh
invoke harness --endpoint http://phoenix.local:6006
# or
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix.local:6006 uv run otel-a2a-relay-harness
```

## What to check in Phoenix

1. **Sessions tab.** One row, `session.id = <printed by harness>`, three traces grouped under it. Both agents A and B visible.
2. **Agent Graph.** Two nodes (A, B), directed edge A -> B from B's `a2a.task` (`graph.node.parent_id = A`), return edge B -> A from A's `a2a.client.recv` (`graph.node.parent_id = B`).
3. **Trace Tree on the `a2a.task` trace.** AGENT-kind root, `a2a.task.state_change` and `a2a.message.stream_chunk` events rendered inline on the timeline, single child `a2a.message.send` LLM span with the final output.

If any of those views does not render as described, the protocol doc backs up before relay implementation begins. Open an issue with screenshots.

## What this harness does NOT validate

- Real A2A wire format. Inputs and outputs are JSON-serialized stand-ins, not actual A2A `Message` shapes.
- Concurrency, contention, ordering across racing agents.
- Long-lived task spans. The harness posts everything in milliseconds.
- Agent Card fetch flow. Cards are stamped on every span directly.

Each of those gets its own harness once the basic shape is confirmed.

## Phoenix DB resets

`phoenix serve` keeps state in `~/.phoenix/phoenix.db`. Across version upgrades the migration can fail with `alembic.script.revision.ResolutionError: No such revision or branch '...'`. Fix is `rm ~/.phoenix/phoenix.db` and restart - the harness is single-shot, the DB is disposable.
