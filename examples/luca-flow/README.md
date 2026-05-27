# LUCA-flow demo: AURORA microsite

Star-topology multi-agent choreography that dogfoods `otel-a2a-relay-core` end-to-end. Produces a real static HTML site (the AURORA microsite, a fictional consumer desk lamp marketed as if it physically channels solar-wind charged particles) from real public-domain NASA imagery committed to this repo.

**Backend-agnostic.** Point `OTEL_EXPORTER_OTLP_ENDPOINT` at any OTLP/HTTP collector (Phoenix `:6006`, Tempo `:4318` via `make tempo-up`, Honeycomb, Datadog).

## What runs

Eight long-running peers + transient workers, all routed through the relay under enforced star topology:

- **orchestrator** (`luca/orchestrator.py`) - drives the script, spawns workers
- **planner** (`luca/planner.py`) - holds the task queue, pure oracle
- **validator** (`luca/validator.py`) - real HTML / citation / nav checks
- **workers a-h** (`luca/worker.py`) - transient subprocesses spawned by orchestrator
- **deployer** (`luca/deployer.py`) - assembles `dist/` after the flow

## Choreography

`script.yaml` is the only place that contains directional guidance like "worker D crashes on receive." Steps:

1. worker-a builds the design system + hero. Validates pass.
2. worker-b drafts a partial gallery. Returns `needs-followup`.
3. worker-c completes the gallery. Validates pass.
4. worker-d crashes immediately on dispatch (exit 1).
5. worker-e picks up the same task with an alternate framing. Validates pass.
6. worker-f writes the spec sheet. First submission missing `<h1>`. Validator rejects, retry passes.
7. worker-g attempts to message the validator directly. Relay returns `-32010` (star-topology violation). Worker exits 1.
8. worker-h writes the mission, about, and preorder pages. Validates pass.
9. deployer assembles `dist/`, writes `CHANGELOG.md` + `delivery-report.md`.

## Run

```sh
# Pick one backend:
docker compose -f tempo_grafana/docker/docker-compose.yml up -d   # Tempo + Grafana
phoenix serve &                                                   # Phoenix

# Then run the demo:
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run luca-flow      # Tempo
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 uv run luca-flow      # Phoenix
python -m webbrowser examples/luca-flow/dist/index.html
```

## Files

- `spec.yaml` - the steady-state target the team builds against
- `script.yaml` - the step-by-step choreography (only place for behavior flags)
- `fixtures/` - per-worker canned content (real HTML)
- `assets/img/nasa/` - 12 NASA public-domain photographs (per-image attribution in `SOURCES.yaml`)
- `assets/fonts/` - three self-hosted webfonts (SIL OFL 1.1)
- `CITATIONS.md` - long-form citation document
- `dist/` - regenerated each run (gitignored)

## Validation rules

The validator runs against every submitted page: HTML5 parses cleanly; exactly one `<h1>`; every `<img>` has `alt` and a `data-nasa-id` resolving in `SOURCES.yaml`; internal links resolve; min word/image count from `spec.yaml`; no external `<script>` or CDN. Real checks, not scripted-pass theater.

## Locking the outputs

Every dist artifact is byte-snapshotted under `tests/snapshots/`. The `LUCA_FREEZE_TIME=2026-01-01T00:00:00Z` env var pins every timestamp and JSON-RPC id (see `src/luca/_clock.py`), so two runs produce byte-identical output. The suite is gated behind the `luca_flow` pytest marker, so default test runs skip it.

```sh
make luca-test                          # diff against snapshots
make luca-snapshots-update              # regenerate after an intentional change
```

## Orchestrator spans

See [`docs/luca-flow-spans.md`](../../docs/luca-flow-spans.md) for the `orchestrator.flow` / `orchestrator.plan` / `orchestrator.step.<n>` / `orchestrator.acceptance` / `orchestrator.flow_complete` span shapes and their attributes.
