.PHONY: up down status relay phoenix-fg send view harness test ruff mypy logs clean-phoenix-db

BG := scripts/bg.sh

up: relay status

down:
	$(BG) stop relay

status:
	@printf 'phoenix: '
	@curl -sf http://localhost:6006/healthz >/dev/null && echo "up (operator-owned)" || echo "down (operator starts: make phoenix-fg)"
	@$(BG) status relay

relay:
	$(BG) start relay -- uv run uvicorn otel_a2a_relay.server:create_app --factory --reload --host 127.0.0.1 --port 8080

phoenix-fg:
	uv run phoenix serve

send:
	AS='$(AS)' CTX='$(CTX)' MSG='$(MSG)' uv run python -m otel_a2a_relay.client send

view:
	CTX='$(CTX)' uv run python -m otel_a2a_relay.client view

harness:
	uv run otel-a2a-relay-harness

test:
	uv run pytest

ruff:
	uv run ruff check src tests
	uv run ruff format --check src tests

mypy:
	uv run mypy src tests

logs:
	@echo 'tail -f logs/relay.log'
	@echo 'tail -f logs/phoenix.log   # if you redirect phoenix-fg there'

clean-phoenix-db:
	rm -f $$HOME/.phoenix/phoenix.db
