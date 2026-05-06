# LUCA-flow plan + progress

Living document. Update checkboxes as steps land. Resume here on interruption.

Scope: dogfood the LUCA multi-agent topology against this relay end-to-end. Star topology (all routing through orchestrator), dynamic worker spawn, real validation, deterministic offline run, Phoenix required, runnable via `make luca-demo` and in GitHub Actions.

Approved artifact: AURORA - "The desk lamp that mirrors the Northern Lights." Plausible-but-impossible consumer device. Static HTML site assembled from real (committed) NASA public-domain imagery. Quality bar: a stranger landing on `dist/index.html` would believe a real product team made this in a hurry.

## Architecture

### Processes started by `make luca-demo`

* relay :8080 - extended with dynamic peer mgmt + star-topology enforcement
* planner :9101 - long-running A2A peer; holds task queue, decides what runs next; pure oracle
* validator :9102 - long-running A2A peer; runs real HTML/CSS/citation checks; pure executor of validation
* orchestrator :9100 - long-running A2A peer; lifecycle + dispatch; subprocess-spawns workers; only role allowed to send to non-orchestrator peers (since orchestrator IS the orchestrator)
* workers :9201..9208 - transient processes spawned by orchestrator; register with relay on boot, deregister on exit
* deployer - subprocess invoked by orchestrator at end (not a long-running peer); produces dist/

### Per-worker dynamics

Orchestrator spawns each worker as `python -m otel_a2a_relay.luca.worker --id worker-X --port 92NN --task-id ... --script-step N`. Worker boots, POSTs `/peers` to register itself, awaits a `message/send` from orchestrator with the task payload, executes its scripted behavior (or crashes), responds, POSTs `DELETE /peers/{id}` and exits.

### Star topology enforcement

Relay tracks each peer's role (orchestrator|planner|validator|worker|deployer). On `message/send` it checks: if sender is not orchestrator, target MUST be orchestrator. Else 403 with reason. Orchestrator can target anyone.

### Strict ordering

Sequential, one worker active at a time. Orchestrator drives the script step-by-step.

## Worker → deliverable mapping

* worker-a 🎨 Designer - design system + `index.html` - submit-pass
* worker-b 🖼️ Curator-1 - `gallery.html` shell + 3 images - needs-followup
* worker-c 🖼️ Curator-2 - finish `gallery.html` (6+ images) - submit-pass
* worker-d 🛰️ Researcher-failed - `science.html` - crash exit 1 immediately
* worker-e 🔭 Researcher-recovery - `science.html` alternate framing - submit-pass
* worker-f 🔧 Engineer - `product.html` - fail (missing h1) → fix → pass
* worker-g 🦹 Rogue - tries to bypass orchestrator - relay 403, exit non-zero
* worker-h ✨ Polish - `mission.html` + `about.html` + `preorder.html` + `CITATIONS.md` - submit-pass

deployer 📦 Release Manager - assemble dist/, tidy/minify, write `CHANGELOG.md` + `delivery-report.md`

## Spec + script files (committed)

* `examples/luca-flow/spec.yaml` - what the team is building (pages, validation rules, design tokens)
* `examples/luca-flow/script.yaml` - the directional choreography (which worker, what behavior, what fixture)
* `examples/luca-flow/fixtures/` - per-worker canned content
* `examples/luca-flow/dist/` - output artifact (gitignored except `.gitkeep`)

## Phases & checklist

### Phase 0: Plan + scaffolding
- [x] Write this file
- [x] Commit plan
- [x] `examples/luca-flow/` skeleton dirs

### Phase 1: NASA imagery acquisition
- [x] Identify ~10-12 NASA public-domain aurora/magnetosphere images
- [x] Download to `examples/luca-flow/assets/img/nasa/`
- [x] `assets/img/nasa/SOURCES.yaml` per-file: url, title, credit, license, fetched_at
- [x] `CITATIONS.md` template (deployer fills the per-image rendering section, this file holds NASA media-policy text + master credit list)
- [x] Commit imagery

### Phase 2: Spec + script schema
- [x] `spec.yaml` (project, pages, design tokens, validation rules)
- [x] `script.yaml` (per-step actor, behavior, fixture, expected outcome)
- [x] `fixtures/` per-worker canned text/HTML
- [x] Commit spec+script+fixtures

### Phase 3: Relay extensions
- [x] `POST /peers` (register: id, url, role) + `DELETE /peers/{id}`
- [x] Star-topology enforcement on `message/send` (with role-based whitelist)
- [x] Tests for both
- [x] `docs/protocol.md` addendum: dynamic peer registration is relay-management (out of A2A→span protocol scope)
- [x] Commit per logical change

### Phase 4: LUCA processes
- [x] `src/otel_a2a_relay/luca/__init__.py`
- [x] `luca/messages.py` - humanized + machine-readable message envelope helpers
- [x] `luca/planner.py`
- [x] `luca/validator.py`
- [x] `luca/orchestrator.py`
- [x] `luca/worker.py`
- [x] `luca/deployer.py`
- [x] `luca/runner.py` - one-command driver (used by `make luca-demo`)
- [x] Tests per process
- [x] Commit per process

### Phase 5: Validator real checks
- [x] HTML5 parse (html5lib)
- [x] Exactly one `<h1>` per page
- [x] Every `<img>` has alt + a citation reference resolvable in CITATIONS.md
- [x] Every NASA image referenced exists in SOURCES.yaml
- [x] Internal nav links resolve
- [x] Min word count per page (from spec)
- [x] CSS file present + non-empty
- [x] No external `<script>` or runtime CDN reference
- [x] Tests
- [x] Commit

### Phase 6: Build pipeline / artifact assembly
- [x] HTML page templates (Jinja-ish via stdlib `string.Template` to avoid a new dep, or single Jinja2 dep - prefer stdlib)
- [x] CSS design system (real, not a stub)
- [x] Self-hosted fonts decision: ship Inter + Space Grotesk + JetBrains Mono in `assets/fonts/` (OFL/MIT)
- [x] Tidy/minify integration (htmltidy via subprocess if available, else pure-Python `htmlmin`)
- [x] Commit

### Phase 7: Deployer + reports
- [x] Assemble dist/ (copy assets, render pages, run minifier)
- [x] Customer changelog (humanized, one entry per accepted task in chronological order)
- [x] Delivery report (full system message log, humanized + machine-readable JSON sidecar)
- [x] Commit

### Phase 8: Phoenix integration verification
- [x] Local Phoenix run, verify spans present per session
- [x] `make view` reducer renders the LUCA flow readably
- [x] Commit any tweaks

### Phase 9: One-command run
- [x] `make luca-demo` Makefile target
- [x] Tears down prior state, brings up phoenix-check + relay + planner + validator + orchestrator, runs script, prints summary, exits clean
- [x] Acceptance assertions inline (artifact exists, expected files present, expected spans recorded)
- [x] Commit

### Phase 10: GitHub Actions
- [x] `.github/workflows/luca-demo.yml`
- [x] Phoenix in CI (run as background process)
- [x] Run `make luca-demo`
- [x] Upload `dist/` as workflow artifact
- [x] Iterate until green
- [x] Commit per iteration

## Dependencies to add

* `pyyaml` - read spec/script/fixtures
* `jinja2` - HTML templating (cleaner than string.Template for this scale)
* `html5lib` - HTML5 parser for validation
* `htmlmin` - HTML minifier (pure Python, deterministic)

## Out of scope (explicit)

* LLM-backed worker variant (deferred; backbone designed to admit it later)
* Auth on the relay
* Persistence beyond the run
* Parallel worker dispatch
* Human-in-the-loop / planner-as-human-contact
* Tempo / non-Phoenix backend

## Resume notes

When resuming, the latest commit on `main` shows the most recent complete phase. Re-read this file's checkboxes against actual on-disk state before deciding what to do next - on-disk wins if they disagree. The `examples/luca-flow/dist/` directory is regenerated each `make luca-demo` and shouldn't be inspected for progress.
