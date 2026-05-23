"""Router-shape tests: paths, methods, deps, and base_url propagation.

Live-pool integration tests stay in the consumer (e.g. `coilysiren/backend`'s
`tests/test_datastore.py` family) gated on a real Postgres URL. These tests
only validate the wiring of the FastAPI router itself.
"""

from __future__ import annotations

import asyncpg
import fastapi
from otel_a2a_relay_channels import (
    MODE_NAME,
    SCHEMA,
    SENTINEL_NOTE,
    SENTINEL_SHAPE,
    make_router,
)


def _dummy_pool() -> asyncpg.Pool:
    raise RuntimeError("pool_provider should not be called by router-shape tests")


def _dummy_auth() -> None:
    return None


def test_make_router_attaches_auth_dependency() -> None:
    router = make_router(pool_provider=_dummy_pool, auth_dependency=_dummy_auth)
    assert isinstance(router, fastapi.APIRouter)
    assert len(router.dependencies) == 1


def test_make_router_no_auth_when_dependency_omitted() -> None:
    router = make_router(pool_provider=_dummy_pool)
    assert router.dependencies == []


def test_make_router_registers_every_route() -> None:
    router = make_router(pool_provider=_dummy_pool, auth_dependency=_dummy_auth)
    paths = {
        (getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", set()) - {"HEAD"})))
        for r in router.routes
    }
    assert ("/agent-channel", ("POST",)) in paths
    assert ("/agent-channel", ("GET",)) in paths
    assert ("/agent-channel/{channel_id}", ("GET",)) in paths
    assert ("/agent-channel/{channel_id}/state", ("GET",)) in paths
    assert ("/agent-channel/{channel_id}/spec", ("GET",)) in paths
    assert ("/agent-channel/{channel_id}/events", ("GET",)) in paths
    assert ("/agent-channel/{channel_id}/event", ("POST",)) in paths
    assert ("/agent-channel/{channel_id}/close", ("POST",)) in paths


def test_make_router_tags_routes_for_mcp_discovery() -> None:
    router = make_router(pool_provider=_dummy_pool)
    assert router.tags == [MODE_NAME]


def test_constants_are_stable_for_consumers() -> None:
    assert MODE_NAME == "agent-channel"
    assert "agent_channels" in SCHEMA
    assert "agent_channel_events" in SCHEMA
    assert "channel_id" in SENTINEL_SHAPE
    assert "kind" in SENTINEL_SHAPE
    assert "append-only" in SENTINEL_NOTE
