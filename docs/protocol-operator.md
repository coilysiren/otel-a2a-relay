# Protocol operator surface

Companion to [protocol.md](protocol.md). The operator-facing CLI, the sequencing gate, and the operational endpoints that live outside the wire protocol.

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
- **Star-topology enforcement** - toggleable via `OTEL_A2A_RELAY_STAR_ENFORCE=1`. When on, `message/send` is rejected with JSON-RPC error `-32010` if neither sender nor target carries the `orchestrator` role. An `a2a.relay.reject` span is emitted instead of `a2a.task`. Peers without registered roles are not enforced (preserves legacy A/B dogfood behavior). The enforcement is a property of the deployment (which choreography is running), not of the A2A spec.

Both are exercised by the `examples/luca-flow/` demo. The wire format and span shape they produce are unchanged from v0.1.
