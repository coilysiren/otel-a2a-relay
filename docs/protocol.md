# Protocol v0.4

The relay's job: translate agent-to-agent activity into OTel spans, with no protocol changes visible to the agents themselves.

The persistence substrate is OTel spans. The wire format implemented today is [A2A](https://a2a-protocol.org/latest/specification/). The spec is shaped so other wire formats (and the GitHub-issue-rooted agent-channel pattern from [coilysiren/coilyco-ai#24](https://github.com/coilysiren/coilyco-ai/issues/24)) can map onto the same span / session / graph shape. Agents never read raw spans. Drop the relay between two existing agent peers and they coordinate normally, except every exchange is now a queryable trace.

This document is the v0.4 protocol shape. v0.4 retires the colony / multi-tenant framing from `tracing.bootstrap()` (see [otel-a2a-relay#121](https://github.com/coilysiren/otel-a2a-relay/issues/121)) to align with the local-only substrate shape that luca adopted on 2026-05-12:

- **`<namespace>.colony` resource attribute renamed to `<namespace>.deployment`.** The old key encoded a per-colony multi-tenant deployment that is not a real use case for a local-only substrate.
- **`product_area` parameter dropped.** Was the "hard-boundary slice within a deployment" knob - a per-tenant routing concept that does not exist in the local-only shape. Phoenix project name is now derived from `<deployment>` alone.
- **Bootstrap docstring de-coloned.** No more "enterprise install" / "colony-defined" language.

v0.2 renamed wire-protocol attributes from `a2a.*` to `o2r.*` and added the `tracing.bootstrap()` entrypoint. v0.3 layered on data-legibility additions surfaced by real Phoenix sessions (see [otel-a2a-relay#93](https://github.com/coilysiren/otel-a2a-relay/issues/93)):

- **Sessions propagate via OpenInference's `using_session(...)` context manager**, not just hand-set `session.id` attributes. Every relay-emitted span sits inside `using_session(context_id)` so any nested OpenInference-instrumented call inherits the session ID.
- **Every span carries `agent.role`.** Workers, validators, planners, orchestrators are no longer anonymous in per-role analysis.
- **Every erroring relay span carries `o2r.relay.failure_class`.** Coarse, machine-readable bucket (`topology_violation`, `peer_disconnect`, `peer_404`, `timeout`, `peer_jsonrpc_error`, `unknown`). Mirrors the Phoenix `relay_failure_class` annotation config that `scripts/phoenix_bootstrap.py` provisions.
- **`tracing.bootstrap()` no longer auto-emits a `tracing.session.start` smoke span.** It is opt-in via `emit_readme_span=True`. Default flow keeps the project list clean.

See ["Phoenix-validated"](#phoenix-validated) below for which v0 claims survived and which were rewritten.

## Topology

Phoenix-only OTLP/HTTP for v1. The relay process exports directly to Phoenix's collector port. No Tempo, no separate OTel Collector, no fan-out. Pluggability is a one-line endpoint swap, documented but not shipped.

One TracerProvider per relay process. Agent identity rides on span attributes, not on the Resource. (See finding 1.)

## Sessions

`session.id = sha256("<repo>:<issue>")[:16]` for GitHub-issue-rooted channels. Deterministic, stable across reconnects, no collector-side coordination. Other transports (Slack thread, Linear ticket) get their own deterministic derivation. The relay never mints session IDs server-side.

One session groups many traces. Each trace is one agent's burst.

## Agent Graph

Phoenix's Agent Graph view consumes OpenInference's explicit graph attributes, not span links. The relay synthesizes them from the A2A peer relationship and attaches them to each root span:

- `graph.node.id` - the acting agent's identity for graph rendering. Default: `<agent_id>`. Use `<agent_id>:<task_id>` if you need per-task nodes.
- `graph.node.parent_id` - the upstream agent in the handoff chain (set on B's `a2a.task` root when triggered by A; unset on the originating burst).

Span links can still be emitted as a secondary signal for OTel-native consumers that read them (Tempo, Jaeger). They are not load-bearing for Phoenix and are treated as informational only.

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
graph.node.id:       A
peer.agent.id:       B
o2r.method:          message/stream
o2r.task.id:         T
rpc.system:          jsonrpc
rpc.service:         a2a
rpc.method:          message/stream
```

Child span `a2a.message.send` for the actual outgoing payload:

```
name:                a2a.message.send
openinference.span.kind: LLM   # if the message is model output
                               # else AGENT
agent.id:            A
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
graph.node.id:       B
graph.node.parent_id: A
o2r.task.id:         T
o2r.task.state:      working   # updated to terminal state at span end
```

State changes are span events, not separate spans:

```
event: o2r.task.state_change   { from: submitted, to: working,   ts: ... }
event: o2r.task.state_change   { from: working,   to: completed, ts: ... }
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

The terminal completion message is upgraded to a child span so it shows up as a node in the trace tree and Phoenix's message timeline:

```
name:                a2a.message.send
openinference.span.kind: LLM
parent:              a2a.task
agent.id:            B
output.value:        <final message.parts as JSON>
output.mime_type:    application/json
```

Span ends. `o2r.task.state` is set to terminal at end. Status code OK on `completed`, ERROR on `failed` or `canceled`.

### Trace 3: A's read / ack burst

Root span `a2a.client.recv`:

```
name:                a2a.client.recv
openinference.span.kind: AGENT
session.id:          <S>
agent.id:            A
graph.node.id:       A
graph.node.parent_id: B
o2r.method:          tasks/get   # or implicit on stream-close
o2r.task.id:         T
```

A's downstream processing of the result lives as children here. Out of scope for the relay.

## Conventions

- **Agent identity = span-level attributes.** Every span the relay emits on agent X's behalf carries `agent.id`, `agent.name`, `agent.role`, and the graph attributes redundantly. Phoenix does not surface `Resource` attributes, so they cannot live there. The relay's own `service.name` is fine on the Resource because it never needs to be queryable per-span.
- **`agent.role` is the broad role** in the agent topology (`relay`, `orchestrator`, `planner`, `validator`, `worker`, `deployer`). Consumers may add a parallel `agent.specialization` for narrower per-worker analysis (`designer`, `curator`, `science_writer`, ...). The relay never inspects either; consumers query against them.
- **Sessions ride on `using_session(context_id)`** plus a redundant `session.id` span attribute. The redundant attribute makes Phoenix's Sessions tab work without OpenInference instrumentation in the loop; the context manager propagates the session to anything OpenInference-instrumented that runs inside.
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

- Sets `PHOENIX_PROJECT_NAME` env var (if not already set) to the slugified `<deployment>`. The slug rule is: lowercase, `[a-z0-9-]`, collapse separators. Phoenix's exporter reads the env var.
- Resource attributes record `service.namespace=<namespace>`, `service.name=<role>`, `<namespace>.deployment=<deployment>`, plus any optional fields and `extra_resource`. The relay never inspects or special-cases the namespace.
- When the caller passes `emit_readme_span=True`, emits one `tracing.session.start` span with a `readme` attribute (`namespace=<x> deployment=<y> role=<r> version=<v>`). Off by default. The smoke span has zero IO and zero session context, so a real flow's project list stays free of it. Tests and one-off probes opt in.

What's out of scope:

- Auto-detecting consumer identity from env / git / process name. The bootstrap requires explicit args so the consumer is the source of truth.
- Multi-tenant exporter routing. One process, one Phoenix project.
- Helpers for setting consumer-flow attributes (`step`, `task_id`, `kind.in`, `kind.out`, `role`, `graph.node.*`). Those live in the consumer's namespace and the consumer sets them on its own spans.

## Phoenix-validated

Run against Phoenix platform v15.4.0 via `phoenix serve` + the `harness/` posting the worked example. What the harness confirmed:

- `session.id` flows correctly. Sessions tab groups traces as expected.
- `openinference.span.kind` drives the rendered span kind (AGENT / LLM).
- Span events render under their parent span without polluting the trace tree.
- Three-traces-per-session topology works, multiple AGENT-kind roots under one session.
- Span event attributes (state changes, stream-chunk seq + final) all preserved.

What the harness rewrote in v0:

- **Resource attributes are not exposed by Phoenix.** Agent identity must live on spans, not on the Resource. v0 specified the opposite. v0.1 fixes it. (v0.2 still puts caller identity on the Resource via `bootstrap()` because non-Phoenix OTel consumers do read it; the relay's own span emission keeps the redundant span-level identity for Phoenix.)
- **Span links are not exposed by Phoenix.** v0 used links for cross-trace topology. v0.1 uses `graph.node.id` / `graph.node.parent_id` instead.

What v0.2 changed:

- **Wire-protocol attributes are now `o2r.*`, not `a2a.*`.** The renamed keys describe this protocol's mechanics, not the consumer's flow. Specifically: `o2r.task.id`, `o2r.task.state`, `o2r.task.state_change` (event), `o2r.message.text`, `o2r.message.reply_text`, `o2r.peer.target`, `o2r.relay.mode`, `o2r.relay.reject_reason`, `o2r.method`. Span names (`a2a.task`, `a2a.client.send`, `a2a.relay.forward`, ...) keep the `a2a.*` prefix because they label A2A wire events.
- **`tracing.bootstrap()` entrypoint** added. See ["Tracing bootstrap"](#tracing-bootstrap) above.

What v0.3 changed:

- **`agent.role` is mandatory on every relay-emitted span.** `relay`, plus the registered role of the sender on `o2r.peer.sender_role` and the target on `o2r.peer.target_role`.
- **`o2r.relay.failure_class`** rides on every erroring relay span. Stable label set: `topology_violation`, `peer_disconnect`, `peer_404`, `timeout`, `peer_jsonrpc_error`, `unknown`.
- **Sessions and users propagate via OpenInference's context managers.** Every relay-emitted span sits inside `using_session(context_id)` and `using_user(sender_id)` so OpenInference auto-instrumentation picks them up without each handler restating them. The redundant `session.id` and `user.id` span attributes remain so Phoenix queries against them work without OpenInference in the loop.
- **`tracing.session.start` smoke span is opt-in.** Default behavior of `bootstrap()` no longer emits it.

If a future Phoenix release changes any of these, the spec backs up again.

## Attribute registry

The canonical set of span attributes this protocol uses. This YAML block is parsed by `scripts/emit_protocol_artifacts.py`, which writes `docs/generated/o2r-attributes.schema.json` (JSON Schema) and `docs/generated/o2r-semconv.yaml` (OTel semantic-conventions shape). Doc is the source of truth; the generated files are committed for downstream tools that want a machine artifact.

```yaml
# o2r-attributes
attributes:
  - id: agent.id
    type: string
    requirement: required
    brief: Stable per-agent identifier inside the deployment.
  - id: agent.name
    type: string
    requirement: required
    brief: Human-readable agent name.
  - id: agent.role
    type: string
    requirement: required
    brief: Broad role in the topology.
    enum: [relay, orchestrator, planner, validator, worker, deployer]
  - id: agent.specialization
    type: string
    requirement: optional
    brief: Narrower per-agent specialization. Consumer-defined.
  - id: session.id
    type: string
    requirement: required
    brief: Deterministic session identifier. sha256(repo:issue)[:16] for GitHub-rooted channels.
  - id: user.id
    type: string
    requirement: recommended
    brief: Sender identity. Propagated via OpenInference using_user().
  - id: graph.node.id
    type: string
    requirement: required
    brief: Topology node identifier for cross-trace graph rendering.
  - id: graph.node.parent_id
    type: string
    requirement: recommended
    brief: Parent node id in the topology graph.
  - id: o2r.task.id
    type: string
    requirement: required
    brief: Task identifier within the session.
  - id: o2r.task.state
    type: string
    requirement: required
    brief: Current task state.
  - id: o2r.task.state_change
    type: string
    requirement: optional
    brief: State transition recorded as a span event attribute.
  - id: o2r.message.text
    type: string
    requirement: optional
    brief: Content of the originating message.
  - id: o2r.message.reply_text
    type: string
    requirement: optional
    brief: Content of the completion reply.
  - id: o2r.peer.target
    type: string
    requirement: required
    brief: Target peer id for a relay forward.
  - id: o2r.peer.sender_role
    type: string
    requirement: required
    brief: Registered role of the sending peer.
  - id: o2r.peer.target_role
    type: string
    requirement: required
    brief: Registered role of the target peer.
  - id: o2r.relay.mode
    type: string
    requirement: optional
    brief: Relay routing mode in effect for this span.
  - id: o2r.relay.reject_reason
    type: string
    requirement: optional
    brief: Reason a relay rejected a message.
  - id: o2r.relay.failure_class
    type: string
    requirement: required
    brief: Coarse failure class on any erroring relay span.
    enum: [topology_violation, peer_disconnect, peer_404, timeout, peer_jsonrpc_error, unknown]
  - id: o2r.method
    type: string
    requirement: required
    brief: A2A JSON-RPC method name driving this span.
```

## Operator surface

`coily channel <verb>` lives in the `coily` repo and talks A2A to a relay. Verbs: `send`, `stream`, `tasks-get`, `tasks-cancel`, `view`. Inherits the audit + gate wrapper pattern. The relay itself ships only a `serve` mode.

## Sequencing

1. v0.1 protocol doc + harness updated and re-validated against Phoenix. (This commit.)
2. Implement the relay around the verified shape.
3. `coily channel` ships after the relay has a `serve` mode reachable on the homelab.

## Relay-management surface (out of protocol)

Some endpoints on the relay are operational, not protocol. They affect routing decisions but do not change the wire shape between agents, and they do not change span shape. They live outside this doc and below the sequencing gate. Adding or changing them does not require a harness re-run.

Currently in this category:

- **`POST /peers`** - register a peer dynamically with `{id, url, role}`. Role is one of `orchestrator | planner | validator | worker | deployer`. Used by transient processes (a worker that boots, registers, takes one task, exits, deregisters) so the relay does not need a static env-var registry for choreographies that spin agents up and down.
- **`DELETE /peers/{id}`** - deregister.
- **Star-topology enforcement** - toggleable via `OTEL_A2A_RELAY_STAR_ENFORCE=1`. When on, `message/send` is rejected with JSON-RPC error `-32010` if neither sender nor target carries the `orchestrator` role; an `a2a.relay.reject` span is emitted instead of `a2a.task`. Peers without registered roles are not enforced (preserves legacy A/B dogfood behavior). The enforcement is a property of the deployment (which choreography is running), not of the A2A spec.

Both are exercised by the `examples/luca-flow/` demo. The wire format and span shape they produce are unchanged from v0.1.
