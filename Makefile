.PHONY: up down status relay agent-a agent-b phoenix-fg send view get tasks cancel peers harness test ruff mypy lint logs tail-relay tail-agent-a tail-agent-b clean-phoenix-db

BG := scripts/bg.sh

# Peer registry the relay reads on startup. Override on the make line if needed.
RELAY_PEERS ?= A=http://127.0.0.1:9001,B=http://127.0.0.1:9002

up: agent-a agent-b relay status

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
	uv run otel-a2a-relay-harness

test:
	uv run pytest

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
