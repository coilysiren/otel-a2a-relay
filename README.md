# otel-a2a-relay

A2A coordination as OTel spans. Drop-in relay between A2A agents that turns wire traffic into traces any OTel-native observability tool can render.

## Status

Protocol v0.1, validated against Phoenix. No relay code yet. The protocol shape is captured in [`docs/protocol.md`](docs/protocol.md), the harness that posts the worked example is in [`src/otel_a2a_relay/harness.py`](src/otel_a2a_relay/harness.py).

## Pitch

`otel-a2a-relay` translates A2A coordination into OTel spans. Any OTel-native agent observability tool (Phoenix, Langfuse, OpenLIT, SigNoz) becomes your live operations UI for free, because the trace IS the state, not a derived view.

- Agent-facing format: A2A (JSON-RPC 2.0 over HTTPS, Agent Cards, streaming via SSE).
- Relay-persistence format: OTel spans, exported via OTLP/HTTP.
- Agents never read raw spans. The relay translates A2A reads/writes into span emissions.
- A2A clients do not need to know they are being recorded. Drop the relay between two existing A2A agents without changing them.

Default visualizer: [Phoenix](https://github.com/Arize-ai/phoenix). OSS, self-hostable, OTLP-native, auto-instruments most agent SDKs.

## Quickstart

```sh
uv sync
uv run phoenix serve &
uv run otel-a2a-relay-harness
```

Open Phoenix at `http://localhost:6006`. See [`docs/harness.md`](docs/harness.md) for what to check.

## Repo layout

- `docs/protocol.md` - protocol spec (current: v0.1)
- `docs/harness.md` - harness run instructions and validation checklist
- `src/otel_a2a_relay/harness.py` - posts the worked-example spans
- `tasks.py` - pyinvoke entry points (`sync`, `harness`, `phoenix`, `test`, `ruff`, `mypy`)

## Related

- Operator CLI lives in [`coily`](https://github.com/coilysiren/coily) under `coily channel`.
- Origin discussion: [coilysiren/coilyco-ai#24](https://github.com/coilysiren/coilyco-ai/issues/24).

## License

MIT.
