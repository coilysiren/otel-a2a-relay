# otel-a2a-relay

A2A coordination as OTel spans. Drop-in relay between A2A agents that turns wire traffic into traces any OTel-native observability tool can render.

## Status

v0 design. No code yet. The protocol shape is captured in [`docs/protocol.md`](docs/protocol.md). Next step is a Phoenix harness that validates the worked example renders correctly before any relay code lands.

## Pitch

`otel-a2a-relay` translates A2A coordination into OTel spans. Any OTel-native agent observability tool (Phoenix, Langfuse, OpenLIT, SigNoz) becomes your live operations UI for free, because the trace IS the state, not a derived view.

- Agent-facing format: A2A (JSON-RPC 2.0 over HTTPS, Agent Cards, streaming via SSE).
- Relay-persistence format: OTel spans, exported via OTLP/HTTP.
- Agents never read raw spans. The relay translates A2A reads/writes into span emissions.
- A2A clients do not need to know they are being recorded. Drop the relay between two existing A2A agents without changing them.

Default visualizer: [Phoenix](https://github.com/Arize-ai/phoenix). OSS, self-hostable, OTLP-native, auto-instruments most agent SDKs.

## Repo layout (planned)

- `docs/protocol.md` - v0 protocol spec (current)
- `harness/` - Phoenix validation harness (next)
- `relay/` - relay server (after harness passes)

## Related

- Operator CLI lives in [`coily`](https://github.com/coilysiren/coily) under `coily channel`.
- Origin discussion: [coilysiren/coilyco-ai#24](https://github.com/coilysiren/coilyco-ai/issues/24).

## License

MIT.
