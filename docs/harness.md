# Phoenix harness

Validates the v0 protocol shape against a running Phoenix instance before any relay code lands.

Posts the [`docs/protocol.md`](../docs/protocol.md) worked example (A streams a task to B, B completes, A acks) as three traces under one session via OTLP/HTTP, then exits.

## Run

Phoenix on the same host:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python post_worked_example.py
```

Phoenix elsewhere:

```sh
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix.local:6006 python post_worked_example.py
```

## What to check in Phoenix

1. **Sessions tab.** One row, `session.id = <printed by harness>`, three traces grouped under it. Both agents A and B visible.
2. **Agent Graph.** Two nodes (A, B), directed edge A -> B from Trace 2's link, return edge B -> A from Trace 3's link. Edge labels carry the task ID.
3. **Trace Tree on the `a2a.task` trace.** AGENT-kind root, `a2a.task.state_change` and `a2a.message.stream_chunk` events rendered inline on the timeline, single child `a2a.message.send` LLM span with the final output.

If any of those views does not render as described, the protocol doc backs up before relay implementation begins. Open an issue with screenshots.

## What this harness does NOT validate

- Real A2A wire format. Inputs and outputs are JSON-serialized stand-ins, not actual A2A `Message` shapes.
- Concurrency, contention, ordering across racing agents.
- Long-lived task spans. The harness posts everything in milliseconds.
- Agent Card fetch flow. Cards are seeded as Resource attributes directly.

Each of those gets its own harness once the basic shape is confirmed.
