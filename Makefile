.PHONY: help up down status restart wait demo luca-demo luca-demo-no-phoenix luca-test luca-snapshots-update relay agent-a agent-b phoenix-fg send stream view get tasks cancel peers harness test ruff mypy lint logs tail-relay tail-agent-a tail-agent-b clean-phoenix-db

BG := scripts/bg.sh

# Peer registry the relay reads on startup. Override on the make line if needed.
RELAY_PEERS ?= A=http://127.0.0.1:9001,B=http://127.0.0.1:9002

help:
	@echo 'Targets:'
	@echo '  up           Bring up agent-a, agent-b, relay (Phoenix is operator-owned).'
	@echo '  down         Stop all relay/agent processes.'
	@echo '  restart      down + up + wait + status.'
	@echo '  status       Print health of phoenix + relay + agents.'
	@echo '  wait         Block until phoenix + relay + agents respond on /healthz.'
	@echo '  demo         Restart and run a two-agent smoke flow.'
	@echo '  send AS=A TO=B CTX=demo MSG="hi"   Post a message via the relay.'
	@echo '  view CTX=demo                      Reduce Phoenix spans for one session.'
	@echo '  get TASK=t-...                     tasks/get for one task id.'
	@echo '  tasks                              List tasks the relay has indexed.'
	@echo '  peers                              List peers + their AgentCards.'
	@echo '  cancel TASK=t-...                  tasks/cancel for one task id.'
	@echo '  harness                            Original Phoenix-validation harness.'
	@echo '  test / lint                        pytest / ruff + mypy.'
	@echo '  tail-relay / tail-agent-a / tail-agent-b   tail -f the running log.'
	@echo '  phoenix-fg                         Run Phoenix in foreground (operator).'
	@echo '  clean-phoenix-db                   Wipe the Phoenix sqlite (operator).'
	@echo '  luca-demo                          Run the AURORA / LUCA-flow demo (Phoenix required).'
	@echo '  luca-demo-no-phoenix               Same, without the Phoenix healthz gate.'

up: agent-a agent-b relay wait status

restart: down up

down:
	-$(BG) stop relay
	-$(BG) stop agent-a
	-$(BG) stop agent-b

status:
	@printf 'phoenix:  '
	@curl -sf http://localhost:6006/healthz >/dev/null && echo "up (operator-owned)" || echo "down (operator starts: make phoenix-fg)"
	@$(BG) status relay
	@$(BG) status agent-a
	@$(BG) status agent-b

wait:
	@scripts/wait-healthy.sh \
	  http://127.0.0.1:8080/healthz \
	  http://127.0.0.1:9001/healthz \
	  http://127.0.0.1:9002/healthz

demo: restart
	@echo
	@echo "===> A -> B  (message/send)"
	@$(MAKE) -s send AS=A TO=B CTX=demo MSG="hello B"
	@echo "===> B -> A  (message/send)"
	@$(MAKE) -s send AS=B TO=A CTX=demo MSG="hi A"
	@echo
	@echo "===> A -> B  (message/stream)"
	@$(MAKE) -s stream AS=A TO=B CTX=demo MSG="streaming hello"
	@sleep 1
	@echo
	@$(MAKE) -s view CTX=demo
	@echo
	@$(MAKE) -s tasks
	@echo
	@$(MAKE) -s peers

relay:
	OTEL_A2A_RELAY_PEERS='$(RELAY_PEERS)' $(BG) start relay -- uv run uvicorn otel_a2a_relay.server:create_app --factory --reload --host 127.0.0.1 --port 8080

agent-a:
	$(BG) start agent-a -- uv run python -m otel_a2a_relay.agent --id A --port 9001

agent-b:
	$(BG) start agent-b -- uv run python -m otel_a2a_relay.agent --id B --port 9002

phoenix-fg:
	uv run phoenix serve

send:
	AS='$(AS)' TO='$(TO)' CTX='$(CTX)' MSG='$(MSG)' uv run python -m otel_a2a_relay.client send

stream:
	AS='$(AS)' TO='$(TO)' CTX='$(CTX)' MSG='$(MSG)' uv run python -m otel_a2a_relay.client stream

view:
	CTX='$(CTX)' uv run python -m otel_a2a_relay.client view

get:
	TASK='$(TASK)' uv run python -m otel_a2a_relay.client get

tasks:
	uv run python -m otel_a2a_relay.client tasks

cancel:
	TASK='$(TASK)' uv run python -m otel_a2a_relay.client cancel

peers:
	uv run python -m otel_a2a_relay.client peers

harness:
	uv run o2r-harness

test:
	uv run pytest

# End-to-end LUCA-flow snapshot suite. Runs the demo with frozen time and
# diffs every dist artifact + per-page screenshot against tests/luca_flow/snapshots/.
# First run on a fresh checkout: `uv run playwright install chromium`.
luca-test:
	uv run pytest tests/luca_flow -m luca_flow --no-cov -p no:cacheprovider

# Regenerate the LUCA-flow snapshots in place (after an intentional change).
# Review the diff before committing.
luca-snapshots-update:
	UPDATE_LUCA_SNAPSHOTS=1 uv run pytest tests/luca_flow -m luca_flow --no-cov -p no:cacheprovider

ruff:
	uv run ruff check src tests
	uv run ruff format --check src tests

mypy:
	uv run mypy src tests

lint: ruff mypy

logs:
	@echo 'tail -f logs/relay.log'
	@echo 'tail -f logs/agent-a.log'
	@echo 'tail -f logs/agent-b.log'

tail-relay:
	tail -f logs/relay.log

tail-agent-a:
	tail -f logs/agent-a.log

tail-agent-b:
	tail -f logs/agent-b.log

clean-phoenix-db:
	rm -f $$HOME/.phoenix/phoenix.db

# LUCA-flow demo. Star-topology multi-agent choreography that produces a
# real static HTML site (the AURORA microsite) from real NASA imagery.
# Phoenix is required by default; pass --no-require-phoenix to skip.
# See examples/luca-flow/ for the spec, script, and fixtures.
luca-demo:
	uv run python -m otel_a2a_relay.luca.runner

luca-demo-no-phoenix:
	uv run python -m otel_a2a_relay.luca.runner --no-require-phoenix
