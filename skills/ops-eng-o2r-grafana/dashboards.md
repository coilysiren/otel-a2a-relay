# Provisioned Grafana dashboards

Companion to [SKILL.md](SKILL.md). What each provisioned dashboard surfaces.

## o2r-overview (default home)

- Agent topology node-graph from `traces_service_graph_request_total`.
- Span rate (5m), error rate (5m). luca-aurora deliberately produces ~12.5% errors.
- p95 span latency by name (histogram quantile). Click exemplar dots to drill into the offending trace.
- Span call rate by `agent.role`.
- Recent error traces (live TraceQL `{ status = error }`).
- TraceQL cheatsheet markdown panel.

## LUCA-flow

- `session_id` variable populated from `{ name = "orchestrator.flow" } | by(span.session.id)`.
- orchestrator.flow waterfall for the active session. Click bars to expand the trace tree (orchestrator.flow -> orchestrator.step.<n> -> dispatch + validate + accept).
- Per-step latency table.
- Per-step acceptance decisions (decision, criterion, actor, specialization).
- Stat panels: accepted (luca expects 5), crashed (1, worker-d), rogue-rejected (1, worker-g), needs-followup (1, worker-b).
- Recent luca-flow runs across all sessions.
