# Trace zoo

Checked-in fixture corpus of Phoenix-shaped spans. Each fixture is a JSON file
containing a list of spans in the canonical shape (`name`, `spanKind`,
`startTime`, `endTime`, `attributes` nested, `events` list).

Load with `from otel_a2a_relay_core.corpus import load_fixture, list_fixtures`.

The corpus exists to feed two consumers:

- `MemorySpanStore` round-trip tests and assertion-macro inputs (#71).
- Future-state diff visualizers and shape clusterers (#7 wall-of-ideas items
  13, 16, 21).

Each fixture targets one protocol shape so the corpus can answer
"is this shape exercised?" by name. Adding shapes is preferred to padding
existing fixtures with noise.

## Index

- `worked_example_completed.json` - protocol.md three-trace flow, terminal `completed`.
- `worked_example_failed.json` - same flow, B errors out, `o2r.relay.failure_class` set.
- `worked_example_canceled.json` - tasks/cancel mid-stream, terminal `canceled`.
- `single_send_sync.json` - degenerate sync case (one chunk, `final: true`).
- `streaming_long.json` - 8 stream_chunk events on the task span.
- `relay_reject_topology.json` - star-topology violation, `a2a.relay.reject` span, JSON-RPC -32010.
- `peer_404.json` - peer disconnect, `o2r.relay.failure_class = peer_404`.
- `multi_session.json` - two sessions in one fixture (used to test session isolation).
- `hub_topology.json` - one orchestrator dispatching to three workers.
- `chain_three_hops.json` - A -> B -> C handoff.
- `concurrent_workers.json` - one orchestrator, two workers running in parallel.
- `tool_call_flow.json` - LLM span with a `gen_ai.tool` child.
- `peer_timeout.json` - relay forward times out, `o2r.relay.failure_class = timeout`.
- `star_orchestrator_passthrough.json` - star mode pass: orchestrator sender, worker target.
- `user_id_propagation.json` - `user.id` attribute exercised on both ends.
