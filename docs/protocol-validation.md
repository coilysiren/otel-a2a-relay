# Protocol validation history

Companion to [protocol.md](protocol.md). What the Phoenix harness verified, and what each minor version reshaped after seeing real data.

## Phoenix-validated

Run against Phoenix platform v15.4.0 via `phoenix serve` + the `harness/` posting the worked example. What the harness confirmed:

- `session.id` flows correctly. Sessions tab groups traces as expected.
- `openinference.span.kind` drives the rendered span kind (AGENT / LLM).
- Span events render under their parent span without polluting the trace tree.
- Three-traces-per-session topology works, multiple AGENT-kind roots under one session.
- Span event attributes (state changes, stream-chunk seq + final) all preserved.

## What v0.1 rewrote in v0

- **Resource attributes are not exposed by Phoenix.** Agent identity must live on spans, not on the Resource. v0 specified the opposite. v0.1 fixes it. (v0.2 still puts caller identity on the Resource via `bootstrap()` because non-Phoenix OTel consumers do read it. The relay's own span emission keeps the redundant span-level identity for Phoenix.)
- **Span links are not exposed by Phoenix.** v0 used links for cross-trace topology. v0.1 uses `graph.node.id` / `graph.node.parent_id` instead.

## What v0.2 changed

- **Wire-protocol attributes are now `o2r.*`, not `a2a.*`.** The renamed keys describe this protocol's mechanics, not the consumer's flow. Specifically: `o2r.task.id`, `o2r.task.state`, `o2r.task.state_change` (event), `o2r.message.text`, `o2r.message.reply_text`, `o2r.peer.target`, `o2r.relay.mode`, `o2r.relay.reject_reason`, `o2r.method`. Span names (`a2a.task`, `a2a.client.send`, `a2a.relay.forward`, ...) keep the `a2a.*` prefix because they label A2A wire events.
- **`tracing.bootstrap()` entrypoint** added. See [protocol-conventions.md](protocol-conventions.md).

## What v0.3 changed

Surfaced by real Phoenix sessions (see [otel-a2a-relay#93](https://github.com/coilysiren/otel-a2a-relay/issues/93)):

- **Sessions propagate via OpenInference's `using_session(...)` context manager**, not just hand-set `session.id` attributes. Every relay-emitted span sits inside `using_session(context_id)` so any nested OpenInference-instrumented call inherits the session ID.
- **Every span carries `agent.role`.** Workers, validators, planners, orchestrators are no longer anonymous in per-role analysis.
- **Every erroring relay span carries `o2r.relay.failure_class`.** Coarse, machine-readable bucket (`topology_violation`, `peer_disconnect`, `peer_404`, `timeout`, `peer_jsonrpc_error`, `unknown`). Mirrors the Phoenix `relay_failure_class` annotation config that `scripts/phoenix_bootstrap.py` provisions.
- **`tracing.bootstrap()` no longer auto-emits a `tracing.session.start` smoke span.** It is opt-in via `emit_readme_span=True`. Default flow keeps the project list clean.

If a future Phoenix release changes any of these, the spec backs up again.
