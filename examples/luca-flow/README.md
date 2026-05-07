# LUCA-flow demo: AURORA microsite

Star-topology multi-agent choreography that dogfoods the relay end-to-end.
Produces a real static HTML site (the AURORA microsite, a fictional
consumer desk lamp marketed as if it physically channels solar-wind charged
particles) from real public-domain NASA imagery committed to this repo.

## What runs

Eight long-running peers + transient workers, all routed through the relay
under enforced star topology:

- **🎯 orchestrator** (`luca/orchestrator.py`) - drives the script, spawns workers
- **📋 planner** (`luca/planner.py`) - holds the task queue, pure oracle
- **🔍 validator** (`luca/validator.py`) - real HTML / citation / nav checks
- **🛠️ workers a-h** (`luca/worker.py`) - transient subprocesses spawned by orchestrator
- **📦 deployer** (`luca/deployer.py`) - assembles `dist/` after the flow

## Choreography

`script.yaml` is the only place that contains directional guidance like "worker D crashes on receive." Steps:

1. 🎨 worker-a builds the design system + hero. Validates pass.
2. 🖼️ worker-b drafts a partial gallery. Returns `needs-followup`.
3. 🖼️ worker-c completes the gallery. Validates pass.
4. 🛰️ worker-d crashes immediately on dispatch (exit 1).
5. 🔭 worker-e picks up the same task with an alternate framing. Validates pass.
6. 🔧 worker-f writes the spec sheet. First submission missing `<h1>`. Validator rejects, retry passes.
7. 🦹 worker-g attempts to message the validator directly, bypassing the orchestrator. Relay returns `-32010` (star-topology violation). Worker exits 1.
8. ✨ worker-h writes the mission, about, and preorder pages. Validates pass.
9. 📦 deployer assembles `dist/`, writes `CHANGELOG.md` + `delivery-report.md`.

## Run

```sh
make phoenix-fg            # in another terminal (operator-owned)
make luca-demo             # foreground; ~15 seconds
open examples/luca-flow/dist/index.html
```

`make luca-demo-no-phoenix` skips the Phoenix healthz gate (useful for
quick iteration; spans are emitted but not collected).

## Files

- `spec.yaml` - the steady-state target the team builds against
- `script.yaml` - the step-by-step choreography (only place for behavior flags)
- `fixtures/` - per-worker canned content (real HTML)
- `assets/img/nasa/` - 12 NASA public-domain photographs and visualizations
- `assets/img/nasa/SOURCES.yaml` - per-image attribution
- `assets/fonts/` - three self-hosted webfonts (SIL OFL 1.1)
- `CITATIONS.md` - long-form citation document
- `dist/` - regenerated each run (gitignored)

## Validation rules

The validator runs against every submitted page:

- HTML5 parses cleanly
- Exactly one `<h1>`
- Every `<img>` has `alt` and a `data-nasa-id` that resolves in `SOURCES.yaml`
- Internal `<a href>` links resolve to known pages
- Min word count from `spec.yaml`
- Min image count from `spec.yaml`
- No external `<script>` or runtime CDN reference

These are real checks against real HTML, not scripted-pass theater. Worker-f's first submission deterministically violates the `<h1>` rule; worker-b's partial gallery violates the image-count rule (which is why it returns `needs-followup` rather than submitting).

## Locking the outputs

Every dist artifact is byte-snapshotted under `tests/luca_flow/snapshots/`:

- `CHANGELOG.md`, `delivery-report.{md,json}`, every `*.html` page - byte diff
- Per-page full-page screenshot via Playwright headless chromium - pixel diff with a small tolerance for font hinting

The `LUCA_FREEZE_TIME=2026-01-01T00:00:00Z` env var pins every timestamp and JSON-RPC id that lands in the dist (see `src/otel_a2a_relay/luca/_clock.py`), so two runs produce byte-identical output.

```sh
make luca-test                          # diff against snapshots
make luca-snapshots-update              # regenerate after an intentional change
uv run playwright install chromium      # one-time setup on a fresh checkout
```

The suite is gated behind the `luca_flow` pytest marker, so `make test` skips it.

## Phoenix-side spans the orchestrator emits

LUCA layers four consumer-flow span shapes on top of the relay's wire-protocol spans (which keep the `a2a.*` prefix). These describe the orchestrator's coordination logic, not the A2A wire:

- **`orchestrator.plan`** - one root span at session start. `output.value` is the full step plan (assignee + intent per step). Enables planned-vs-actual diffs in Phoenix and makes step reassignment after a worker failure queryable without joining across worker spans.
- **`orchestrator.acceptance`** - one child-of-session span per step's terminal decision. Carries `o2r.step.acceptance.{decision,reason,criterion,score}` plus `o2r.step.actor` and `o2r.step.specialization`. `decision` is `accepted | needs-followup | crashed | rogue-rejected | unknown`. `score=1.0` for accepted, else `0.0`, so Phoenix's per-role rollup is a numeric average.
- **`orchestrator.flow_complete`** - one terminal span per session. `o2r.flow.outcome_counts` is a JSON map of decision → count. The `task_outcome_correct` annotation config attaches here for the per-session binary score.
- **Per-worker `agent.specialization`** - rides on every worker span (`designer`, `curator`, `science_writer`, `spec_writer`, `polish_writer`, `rogue`). `agent.role` stays at `worker` (the topology role, used by the relay's star-topology gate); `agent.specialization` is the granular dimension you slice by in Phoenix.

These complement the relay's `o2r.relay.failure_class` attribute and the two annotation configs (`relay_failure_class`, `task_outcome_correct`) that `make phoenix-bootstrap` provisions. Together they give Phoenix:

- Per-role analysis (`agent.specialization`)
- Per-step accept/reject scores (`orchestrator.acceptance`)
- Per-session correctness annotation (`orchestrator.flow_complete` + `task_outcome_correct`)
- Per-erroring-span failure-class annotation (relay spans + `relay_failure_class`)
- Planned-vs-actual queries (`orchestrator.plan` + per-step `orchestrator.acceptance`)

## Phoenix-side bootstrap

```sh
make phoenix-bootstrap                  # idempotent
make phoenix-bootstrap-dry-run          # show plan, no writes
```

Provisions the two annotation configs and two named datasets (`relay-decisions-golden`, `relay-failures-regression`) Phoenix needs to render the relay's data legibility surface end to end. Re-runs are no-ops on already-existing names. Source: `scripts/phoenix_bootstrap.py`.
