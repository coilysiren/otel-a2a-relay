# Protocol conventions and tracing bootstrap

Companion to [protocol.md](protocol.md). The span-shape rules every relay-emitted span obeys, and the one-shot per-process bootstrap entrypoint.

## Conventions

- **Agent identity = span-level attributes.** Every span the relay emits on agent X's behalf carries `agent.id`, `agent.name`, `agent.role`, and the graph attributes redundantly. Phoenix does not surface `Resource` attributes, so they cannot live there. The relay's own `service.name` is fine on the Resource because it never needs to be queryable per-span.
- **`agent.role` is the broad role** in the agent topology (`relay`, `orchestrator`, `planner`, `validator`, `worker`, `deployer`). Consumers may add a parallel `agent.specialization` for narrower per-worker analysis (`designer`, `curator`, `science_writer`, ...). The relay never inspects either; consumers query against them.
- **Sessions ride on `using_session(context_id)`** plus a redundant `session.id` span attribute. The redundant attribute makes Phoenix's Sessions tab work without OpenInference instrumentation in the loop. The context manager propagates the session to anything OpenInference-instrumented that runs inside.
- **`user.id` rides on `using_user(sender_id)`** plus a redundant `user.id` attribute. Phoenix's per-user filters and the User column in the Sessions tab consume it.
- **Task = one root span**, lifetime = task lifetime, state in events. Not one trace per task. Multiple tasks in the same session share `session.id`.
- **Messages = mixed.** Content-bearing initial sends and final completions are spans (LLM kind). Streaming chunks and protocol-level state pings are span events. Rule of thumb: if it would render as a node in the trace tree, it is a span. If it would render as a tick on a timeline, it is an event.
- **Streaming and sync share span shape.** Sync is the degenerate case where the task span opens, fires one `stream_chunk` event with `final: true`, ends with a child completion span. The relay does not branch on sync vs stream at the span layer.
- **Topology = `graph.node.*` attributes**, not span links. Span links may be emitted alongside but are not load-bearing.
- **Failure classification = `o2r.relay.failure_class`** on any erroring relay span. Stable, machine-readable bucket. Pairs with the `relay_failure_class` annotation config in Phoenix.

## Tracing bootstrap

The relay is consumer-agnostic. Anything reading or writing o2r-shaped spans is a "consumer," and the relay never knows or hardcodes which one. To stand up an OTel tracer that emits into the right Phoenix project with the right resource attributes, a consumer calls `otel_a2a_relay.tracing.bootstrap(...)` once per process.

```python
from otel_a2a_relay.tracing import bootstrap

tracer = bootstrap(
    namespace="frob",          # required - logical system name (OTel service.namespace)
    deployment="acme",         # required - logical install identifier
    role="planner",            # required - this process's role (OTel service.name)
    deployment_env="prod",     # optional
    version="1.2.3",           # optional
    git_commit="deadbeef",     # optional
    extra_resource={...},      # optional - merged in last
)
```

Returns a configured `Tracer`. Side effects:

- Sets `PHOENIX_PROJECT_NAME` env var (if not already set) to the slugified `<deployment>`. Slug rule: lowercase, `[a-z0-9-]`, collapse separators.
- Resource attributes record `service.namespace=<namespace>`, `service.name=<role>`, `<namespace>.deployment=<deployment>`, plus optional fields and `extra_resource`.
- When `emit_readme_span=True`, emits one `tracing.session.start` span with a `readme` attribute. Off by default.

Out of scope: auto-detecting consumer identity, multi-tenant exporter routing, helpers for setting consumer-flow attributes. Those live in the consumer's namespace.
