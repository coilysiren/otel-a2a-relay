"""pyinvoke tasks for otel-a2a-relay."""

from __future__ import annotations

from invoke import task


@task
def sync(c):  # type: ignore[no-untyped-def]
    """Install deps via uv."""
    c.run("uv sync")


@task(help={"endpoint": "Phoenix OTLP host:port (default http://localhost:6006)."})
def harness(c, endpoint=None):  # type: ignore[no-untyped-def]
    """Post the worked-example spans to Phoenix and exit. Validates the v0.1 protocol shape."""
    env = f"OTEL_EXPORTER_OTLP_ENDPOINT={endpoint} " if endpoint else ""
    c.run(f"{env}uv run otel-a2a-relay-harness")


@task
def phoenix(c):  # type: ignore[no-untyped-def]
    """Start a local Phoenix on :6006 in the foreground. Ctrl-C to stop."""
    c.run("uv run phoenix serve")


@task
def test(c):  # type: ignore[no-untyped-def]
    """Run pytest."""
    c.run("uv run pytest")


@task
def ruff(c):  # type: ignore[no-untyped-def]
    """Lint + format (check mode)."""
    c.run("uv run ruff check src tasks.py tests")
    c.run("uv run ruff format --check src tasks.py tests")


@task
def mypy(c):  # type: ignore[no-untyped-def]
    """Type-check src and tests."""
    c.run("uv run mypy src tests")
