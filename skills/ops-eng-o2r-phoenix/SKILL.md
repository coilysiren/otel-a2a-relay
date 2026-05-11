---
name: "ops-eng-o2r-phoenix"
description: "Use when working with the Arize Phoenix backend for otel-a2a-relay (o2r). Names the specific Phoenix UI surface for each question (waterfall vs JSON tree vs session list vs agent topology), with direct URLs and click paths. Triggers - phoenix, arize phoenix, o2r phoenix, phoenix sessions, phoenix trace, where is the waterfall, agent graph, openinference, o2r-harness, o2r-view, o2r-phoenix-bootstrap."
---

# Phoenix backend for o2r

Local Phoenix runs at `http://localhost:6006`. The relay points `OTEL_EXPORTER_OTLP_ENDPOINT` at the same host (Phoenix accepts OTLP/HTTP on 6006).

Repo: [otel-a2a-relay/arize_phoenix/](https://github.com/coilysiren/otel-a2a-relay/tree/main/arize_phoenix). Upstream: [Arize Phoenix](https://docs.arize.com/phoenix).

## Which UI surface answers which question

Default to *visual* views, not the JSON tree. The JSON tree on the trace detail page is a fallback - it is not the waterfall.

- **"Show me one session, all hops"** - **Sessions** tab. http://localhost:6006/projects/default/sessions. One row per `session.id`, click to expand to per-trace list. This is the entry point for any o2r demo run.
- **"Show me the visual parent/child waterfall for one trace"** - Click a trace from the Sessions row. The **Trace** detail page renders the timeline waterfall by default. If you are looking at JSON, you clicked the wrong tab. Honeycomb / Sentry / Datadog equivalent: same view, different vendor.
- **"Show me the agent topology"** - **Agent Graph** tab on the project. Nodes are agents (`agent.role` + `agent.specialization`), edges come from `graph.node.parent_id` on spans. For o2r this is A -> B for outbound, B -> A for return.
- **"Show me LLM calls inside a hop"** - LLM-kind spans nest under AGENT-kind roots in the Trace waterfall. OpenInference attributes (`openinference.span.kind = LLM`) drive the rendering.
- **"Show me datasets / annotations"** - **Datasets** and **Annotations** sections in the left nav. `o2r-phoenix-bootstrap` provisions `relay-decisions-golden`, `relay-failures-regression`, `relay_failure_class`, `task_outcome_correct`.

## Operate

From `otel-a2a-relay/` workspace root:

```sh
uv sync --all-packages
make phoenix-fg              # Phoenix in foreground (operator-owned, separate terminal)
make phoenix-bootstrap       # idempotent: annotation configs + datasets
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 make luca-demo
open http://localhost:6006   # lands on home, click Sessions
```

Phoenix elsewhere (remote host): `OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix.local:6006 uv run o2r-harness`.

## CLIs the relay ships

- `o2r-harness` - posts the worked-example trace, prints `session.id`, prints the validation checklist (Sessions / Agent Graph / Trace Tree) you should walk through.
- `o2r-view` - reduces a Phoenix session's spans to a readable per-hop log. Use when Kai wants the waterfall content in text form (mobile, dictation, no browser). Also drives `make gif CTX=<context>` for an animated topology GIF of one session.
- `o2r-phoenix-bootstrap` - idempotently provisions annotation configs + datasets via Phoenix REST.

## Harness validation checklist

After `o2r-harness`, confirm in Phoenix:

1. **Sessions tab** - one row with the printed `session.id`, three traces grouped under it, both agents A and B visible.
2. **Agent Graph** - two nodes (A, B), edge A -> B (B's `a2a.task`), edge B -> A (A's `a2a.client.recv`).
3. **Trace** detail on the `a2a.task` trace - AGENT-kind root, inline events for `a2a.task.state_change` and `a2a.message.stream_chunk`, single `a2a.message.send` LLM child.

If any of those fails to render, do not start relay implementation. Open an issue with screenshots.

## Common traps

- **JSON tree is not the waterfall.** The trace detail page has a JSON view and a timeline view. The timeline is the waterfall. If Kai asks "where is the visual view," answer Trace detail -> timeline tab, not the default JSON dump.
- **DB stuck on alembic error.** `~/.phoenix/phoenix.db` migration fails across version bumps with `ResolutionError`. Fix: `rm ~/.phoenix/phoenix.db` and restart. The harness reseeds in seconds.
- **No spans showing.** Check `OTEL_EXPORTER_OTLP_ENDPOINT` actually points at `:6006` (Phoenix), not `:4318` (Tempo's port). Same protocol, different backend.
- **OpenInference attributes missing.** Agent Graph stays empty without `openinference.span.kind` and `graph.node.parent_id`. The relay sets these; bespoke instrumentation must too.
