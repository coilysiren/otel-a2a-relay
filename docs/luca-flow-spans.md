# LUCA-flow orchestrator spans

Companion to [`examples/luca-flow/README.md`](../examples/luca-flow/README.md). The consumer-flow span shapes the orchestrator layers on top of the relay's wire-protocol spans (which keep the `a2a.*` prefix). These describe the orchestrator's coordination logic, not the A2A wire.

## Span shapes

- **`orchestrator.flow`** - long-lived root span, parent of every step.
- **`orchestrator.plan`** - first child of the flow span. `output.value` is the full step plan (assignee + intent per step). Enables planned-vs-actual diffs.
- **`orchestrator.step.<n>`** - one per step. Parent of dispatch + validate + decide for that step. Phoenix and Grafana both render this as one expandable subtree.
- **`orchestrator.acceptance`** - one child of each step span. Carries `o2r.step.acceptance.{decision,reason,criterion,score}` plus `o2r.step.actor` and `o2r.step.specialization`. `decision` is `accepted | needs-followup | crashed | rogue-rejected | unknown`.
- **`orchestrator.flow_complete`** - terminal child of the flow span. `o2r.flow.outcome_counts` is a JSON map of decision -> count.

## Worker attributes

Per-worker `agent.specialization` rides on every worker span (`designer`, `curator`, `science_writer`, `spec_writer`, `polish_writer`, `rogue`). `agent.role` stays at `worker` (the topology role, used by the relay's star-topology gate). `agent.specialization` is the granular dimension you slice by.

## How these compose with the relay attributes

These complement the relay's `o2r.relay.failure_class` attribute and the two annotation configs (`relay_failure_class`, `task_outcome_correct`). For Phoenix users, `make phoenix-bootstrap` provisions the configs and datasets. For Tempo users, the `luca-flow` Grafana dashboard at `http://localhost:3000/d/luca-flow/luca-flow` does the same job.
