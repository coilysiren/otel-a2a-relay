# Protocol attribute registry

Companion to [protocol.md](protocol.md). The canonical set of span attributes this protocol uses. This YAML block is parsed by `scripts/emit_protocol_artifacts.py`, which writes `docs/generated/o2r-attributes.schema.json` (JSON Schema) and `docs/generated/o2r-semconv.yaml` (OTel semantic-conventions shape). Doc is the source of truth. The generated files are committed for downstream tools that want a machine artifact.

```yaml
# o2r-attributes
attributes:
  - { id: agent.id, type: string, requirement: required, brief: Stable per-agent identifier. }
  - { id: agent.name, type: string, requirement: required, brief: Human-readable agent name. }
  - id: agent.role
    type: string
    requirement: required
    brief: Broad role in the topology.
    enum: [relay, orchestrator, planner, validator, worker, deployer]
  - { id: agent.specialization, type: string, requirement: optional, brief: Consumer-defined per-agent specialization. }
  - { id: session.id, type: string, requirement: required, brief: Deterministic session id (sha256(repo:issue)[:16] for GitHub-rooted). }
  - { id: user.id, type: string, requirement: recommended, brief: Sender identity via OpenInference using_user(). }
  - { id: graph.node.id, type: string, requirement: required, brief: Topology node id for cross-trace rendering. }
  - { id: graph.node.parent_id, type: string, requirement: recommended, brief: Parent node id in the topology graph. }
  - { id: o2r.task.id, type: string, requirement: required, brief: Task identifier within the session. }
  - { id: o2r.task.state, type: string, requirement: required, brief: Current task state. }
  - { id: o2r.task.state_change, type: string, requirement: optional, brief: State transition recorded as a span event attribute. }
  - { id: o2r.message.text, type: string, requirement: optional, brief: Content of the originating message. }
  - { id: o2r.message.reply_text, type: string, requirement: optional, brief: Content of the completion reply. }
  - { id: o2r.peer.target, type: string, requirement: required, brief: Target peer id for a relay forward. }
  - { id: o2r.peer.sender_role, type: string, requirement: required, brief: Registered role of the sending peer. }
  - { id: o2r.peer.target_role, type: string, requirement: required, brief: Registered role of the target peer. }
  - { id: o2r.relay.mode, type: string, requirement: optional, brief: Relay routing mode in effect for this span. }
  - { id: o2r.relay.reject_reason, type: string, requirement: optional, brief: Reason a relay rejected a message. }
  - id: o2r.relay.failure_class
    type: string
    requirement: required
    brief: Coarse failure class on any erroring relay span.
    enum: [topology_violation, peer_disconnect, peer_404, timeout, peer_jsonrpc_error, unknown]
  - { id: o2r.method, type: string, requirement: required, brief: A2A JSON-RPC method name driving this span. }
```
