.PHONY: help \
  sync test test-core test-arize-phoenix test-tempo-grafana test-luca \
  lint ruff mypy fmt \
  tempo-up tempo-down tempo-logs tempo-status tempo-harness tempo-clean \
  phoenix-fg phoenix-bootstrap phoenix-bootstrap-dry-run phoenix-harness \
  luca-demo luca-test luca-snapshots-update \
  gif-fixture-update gif-fixture-update-ci-replay \
  protocol-decisions protocol-decisions-check \
  status

# ----------------------------------------------------------------------
# Sync
# ----------------------------------------------------------------------
sync: ## uv sync --all-packages.
	uv sync --all-packages

# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
test: test-core test-arize-phoenix test-tempo-grafana ## Run all member-package pytest suites.

test-core: ## Run the core/ pytest suite (covers tracing, span store, corpus).
	cd core && uv run pytest

test-arize-phoenix: ## Run the arize_phoenix/ pytest suite.
	cd arize_phoenix && uv run pytest

test-tempo-grafana: ## Run the tempo_grafana/ pytest suite.
	cd tempo_grafana && uv run pytest

# Slow end-to-end LUCA-flow snapshot suite. Runs the demo as a subprocess.
luca-test:
	cd examples/luca-flow && uv run pytest -m luca_flow

luca-snapshots-update:
	cd examples/luca-flow && UPDATE_LUCA_SNAPSHOTS=1 uv run pytest -m luca_flow

# ----------------------------------------------------------------------
# Lint
# ----------------------------------------------------------------------
lint: ruff mypy ## Run ruff + mypy across the workspace.

ruff:
	uv run ruff check core arize_phoenix tempo_grafana examples
	uv run ruff format --check core arize_phoenix tempo_grafana examples

fmt: ## Format with ruff.
	uv run ruff check --fix core arize_phoenix tempo_grafana examples
	uv run ruff format core arize_phoenix tempo_grafana examples

mypy:
	@# Per-package so multiple `tests/` namespaces don't collide.
	cd core && uv run mypy src tests
	cd arize_phoenix && uv run mypy src tests
	cd tempo_grafana && uv run mypy src tests
	cd examples/luca-flow && uv run mypy src tests

# ----------------------------------------------------------------------
# Tempo + Grafana stack (otel-a2a-relay-tempo-grafana extension)
# ----------------------------------------------------------------------
tempo-up:
	docker compose -f tempo_grafana/docker/docker-compose.yml up -d
	@echo
	@echo "  Grafana:           http://localhost:3000"
	@echo "  LUCA-flow board:   http://localhost:3000/d/luca-flow/luca-flow"
	@echo "  Tempo OTLP/HTTP:   http://localhost:4318"
	@echo "  Tempo query API:   http://localhost:3200"

tempo-down:
	docker compose -f tempo_grafana/docker/docker-compose.yml down

tempo-clean:
	docker compose -f tempo_grafana/docker/docker-compose.yml down -v

tempo-logs:
	docker compose -f tempo_grafana/docker/docker-compose.yml logs -f --tail=100

tempo-status:
	docker compose -f tempo_grafana/docker/docker-compose.yml ps

tempo-harness:
	uv run o2r-tempo-harness

# ----------------------------------------------------------------------
# Arize Phoenix (otel-a2a-relay-arize-phoenix extension)
# ----------------------------------------------------------------------
phoenix-fg:
	PHOENIX_DANGEROUSLY_ENABLE_AGENTS=true uv run phoenix serve

phoenix-harness:
	uv run o2r-harness

phoenix-bootstrap:
	uv run o2r-phoenix-bootstrap

phoenix-bootstrap-dry-run:
	uv run o2r-phoenix-bootstrap --dry-run

# Regenerate the byte-exact baseline GIF that test_viz.py compares against.
# Pillow's freetype build is per-platform, so the canonical bytes are Linux.
# Run inside the same image CI uses (python:3.13-slim) when off-Linux.
gif-fixture-update:
	cd arize_phoenix && uv run python -m tests.fixtures.regen_session_gifs

# Local replay of the regen-gif-baseline GHA workflow, in docker. Use this
# instead of pushing experimental workflow changes through CI.
gif-fixture-update-ci-replay:
	scripts/replay_regen_gif_baseline.sh

# ----------------------------------------------------------------------
# LUCA-flow demo (backend-agnostic; uses whichever collector is up)
# ----------------------------------------------------------------------
luca-demo:
	@COLLECTOR=$${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}; \
	echo "🚀 luca-demo against $$COLLECTOR"; \
	uv run python -m luca.runner --collector $$COLLECTOR

# ----------------------------------------------------------------------
# Protocol decision log
# ----------------------------------------------------------------------
# Auto-generated from `git blame` on docs/protocol.md. Regenerate after any
# protocol-shape change so docs/protocol-decisions.md tracks the doc.
protocol-decisions:
	uv run python scripts/protocol_decision_log.py

protocol-decisions-check:
	uv run python scripts/protocol_decision_log.py --check

# ----------------------------------------------------------------------
# Help
# ----------------------------------------------------------------------
help:
	@echo 'Targets:'
	@echo
	@echo '  Workspace:'
	@echo '    sync                       uv sync --all-packages'
	@echo '    test                       Per-package pytest (core + arize_phoenix + tempo_grafana)'
	@echo '    lint / ruff / mypy / fmt   Workspace-wide lint'
	@echo
	@echo '  Tempo + Grafana extension:'
	@echo '    tempo-up                   docker compose up -d (Tempo + Grafana stack)'
	@echo '    tempo-down                 Stop, preserve data'
	@echo '    tempo-clean                Stop, wipe volumes'
	@echo '    tempo-logs / tempo-status  Stream / inspect'
	@echo '    tempo-harness              Post worked-example trace, print Grafana link'
	@echo
	@echo '  Arize Phoenix extension:'
	@echo '    phoenix-fg                 Run Phoenix in foreground'
	@echo '    phoenix-harness            Post worked-example trace to Phoenix'
	@echo '    phoenix-bootstrap          Provision annotation configs + datasets'
	@echo
	@echo '  LUCA-flow demo:'
	@echo '    luca-demo                  Run AURORA flow against $$OTEL_EXPORTER_OTLP_ENDPOINT'
	@echo '    luca-test                  Diff dist/ against snapshots'
	@echo '    luca-snapshots-update      Refresh snapshots after intentional change'
