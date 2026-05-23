"""FastAPI router factory for the Agent Channel coordination layer.

The router is parameterized so the package stays backend-agnostic: callers
inject a `pool_provider` (returns an asyncpg.Pool), an optional auth
dependency, and a base URL used when synthesizing the self-describing
onboarding view's URL fields.

Every POST /agent-channel/{id}/event emits one OTel span so channel activity
lights up alongside A2A traces in any OTLP-native backend (Phoenix, Tempo,
Honeycomb, ...). Tracing is opt-in via the global TracerProvider - if the
host process has not bootstrapped OTel, the no-op tracer is used and the
endpoint behaves identically.
"""

import json
import typing
from collections.abc import Callable

import asyncpg
import fastapi
import opentelemetry.trace
import yaml

from .ids import norm_id
from .models import ChannelCreate, EventCreate
from .onboarding import ONBOARDING, channel_markdown, pick_format

MODE_NAME = "agent-channel"

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_channels (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS agent_channel_events (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES agent_channels(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_channel_events_chan_created_idx
    ON agent_channel_events (channel_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_channel_events_chan_kind_idx
    ON agent_channel_events (channel_id, kind, created_at DESC);
"""

SENTINEL_SHAPE: dict[str, typing.Any] = {
    "channel_id": "ABCD",
    "kind": "state | comms | status | log",
    "author": "agent identity (e.g. `coily agent-name`)",
    "payload": {"any": "json"},
}

SENTINEL_NOTE = (
    "agent coordination channels: a registry of 4-char-id channels plus an "
    "append-only per-channel event log. GET /agent-channel/{id} self-describes."
)

PoolProvider = Callable[[], asyncpg.Pool]


def _channel_row(record: asyncpg.Record, base_url: str) -> dict[str, typing.Any]:
    return {
        "id": record["id"],
        "title": record["title"],
        "created_by": record["created_by"],
        "created_at": record["created_at"].isoformat(),
        "closed_at": record["closed_at"].isoformat() if record["closed_at"] else None,
        "url": f"{base_url}/agent-channel/{record['id']}",
    }


def _event_row(record: asyncpg.Record) -> dict[str, typing.Any]:
    return {
        "id": record["id"],
        "channel_id": record["channel_id"],
        "kind": record["kind"],
        "author": record["author"],
        "payload": record["payload"],
        "created_at": record["created_at"].isoformat(),
    }


async def _load_channel(pool: asyncpg.Pool, cid: str) -> asyncpg.Record:
    record = await pool.fetchrow("SELECT * FROM agent_channels WHERE id = $1", cid)
    if record is None:
        raise fastapi.HTTPException(status_code=404, detail="no such channel")
    return record


def make_router(
    *,
    pool_provider: PoolProvider,
    auth_dependency: Callable[..., typing.Any] | None = None,
    base_url: str = "http://api",
) -> fastapi.APIRouter:
    """Build the agent-channel router wired to a caller-supplied pool + auth."""
    deps = [fastapi.Depends(auth_dependency)] if auth_dependency else []
    router = fastapi.APIRouter(tags=[MODE_NAME], dependencies=deps)
    tracer = opentelemetry.trace.get_tracer("otel_a2a_relay_channels")

    def channel_url(cid: str) -> str:
        return f"{base_url}/agent-channel/{cid}"

    @router.post("/agent-channel")
    async def create_channel(body: ChannelCreate) -> dict[str, typing.Any]:
        """Create a channel with a fresh 4-char id. Returns the channel and its URL."""
        from .ids import new_id

        pool = pool_provider()
        for _ in range(20):
            try:
                record = await pool.fetchrow(
                    "INSERT INTO agent_channels (id, title, created_by) "
                    "VALUES ($1, $2, $3) RETURNING *",
                    new_id(),
                    body.title,
                    body.created_by,
                )
                return _channel_row(record, base_url)
            except asyncpg.UniqueViolationError:
                continue
        raise fastapi.HTTPException(status_code=500, detail="could not allocate a channel id")

    @router.get("/agent-channel")
    async def list_channels(
        limit: int = 50, include_closed: bool = True
    ) -> list[dict[str, typing.Any]]:
        """List channels, newest first. Set include_closed=false to hide closed ones."""
        limit = max(1, min(limit, 500))
        pool = pool_provider()
        if include_closed:
            records = await pool.fetch(
                "SELECT * FROM agent_channels ORDER BY created_at DESC LIMIT $1", limit
            )
        else:
            records = await pool.fetch(
                "SELECT * FROM agent_channels WHERE closed_at IS NULL "
                "ORDER BY created_at DESC LIMIT $1",
                limit,
            )
        return [_channel_row(r, base_url) for r in records]

    @router.get("/agent-channel/{channel_id}", response_model=None)
    async def get_channel(
        channel_id: str,
        request: fastapi.Request,
        format_: str | None = fastapi.Query(default=None, alias="format"),
    ) -> fastapi.Response | dict[str, typing.Any]:
        """Self-describing onboarding view: prose, channel meta, latest state, recent events.

        Content-negotiates the response: JSON by default, YAML for an
        `application/yaml` Accept header, Markdown for `text/markdown`. A
        `?format=json|yaml|markdown` query param overrides the Accept header.
        """
        cid = norm_id(channel_id)
        pool = pool_provider()
        channel = await _load_channel(pool, cid)
        state = await pool.fetchrow(
            "SELECT * FROM agent_channel_events WHERE channel_id = $1 AND kind = 'state' "
            "ORDER BY created_at DESC LIMIT 1",
            cid,
        )
        spec = await pool.fetchrow(
            "SELECT * FROM agent_channel_events WHERE channel_id = $1 AND kind = 'spec' "
            "ORDER BY created_at DESC LIMIT 1",
            cid,
        )
        recent = await pool.fetch(
            "SELECT * FROM agent_channel_events WHERE channel_id = $1 "
            "ORDER BY created_at DESC LIMIT 20",
            cid,
        )
        data: dict[str, typing.Any] = {
            "channel": _channel_row(channel, base_url),
            "onboarding": ONBOARDING,
            "participate": {
                "read_this": f"GET {channel_url(cid)}",
                "read_spec": f"GET {channel_url(cid)}/spec",
                "read_state": f"GET {channel_url(cid)}/state",
                "read_events": f"GET {channel_url(cid)}/events?kind=<kind>&limit=<n>",
                "append_event": f"POST {channel_url(cid)}/event "
                '{"kind": "...", "author": "...", "payload": {...}}',
                "formats": f"GET {channel_url(cid)}?format=json|yaml|markdown "
                "(or send a matching Accept header)",
                "auth": "Authorization: Bearer <token> - deployment-defined",
                "your_name": "agent identity (e.g. `coily agent-name`)",
            },
            "spec": _event_row(spec)["payload"] if spec else None,
            "state": _event_row(state)["payload"] if state else None,
            "recent_events": [_event_row(r) for r in recent],
        }
        chosen = pick_format(format_, request.headers.get("accept", ""))
        if chosen == "yaml":
            return fastapi.Response(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                media_type="application/yaml",
            )
        if chosen == "markdown":
            return fastapi.Response(channel_markdown(data), media_type="text/markdown")
        return data

    @router.get("/agent-channel/{channel_id}/state")
    async def get_state(channel_id: str) -> dict[str, typing.Any]:
        """Return the newest `state` event's payload, or 404 if the channel has none yet."""
        cid = norm_id(channel_id)
        pool = pool_provider()
        await _load_channel(pool, cid)
        record = await pool.fetchrow(
            "SELECT * FROM agent_channel_events WHERE channel_id = $1 AND kind = 'state' "
            "ORDER BY created_at DESC LIMIT 1",
            cid,
        )
        if record is None:
            raise fastapi.HTTPException(status_code=404, detail="channel has no state event yet")
        payload: dict[str, typing.Any] = _event_row(record)["payload"]
        return payload

    @router.get("/agent-channel/{channel_id}/spec")
    async def get_spec(channel_id: str) -> dict[str, typing.Any]:
        """Return the newest `spec` event's payload (the channel charter), or 404."""
        cid = norm_id(channel_id)
        pool = pool_provider()
        await _load_channel(pool, cid)
        record = await pool.fetchrow(
            "SELECT * FROM agent_channel_events WHERE channel_id = $1 AND kind = 'spec' "
            "ORDER BY created_at DESC LIMIT 1",
            cid,
        )
        if record is None:
            raise fastapi.HTTPException(status_code=404, detail="channel has no spec event yet")
        payload: dict[str, typing.Any] = _event_row(record)["payload"]
        return payload

    @router.get("/agent-channel/{channel_id}/events")
    async def list_events(
        channel_id: str,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, typing.Any]]:
        """List a channel's events, newest first. Optional `kind` filter. Luca polls this."""
        cid = norm_id(channel_id)
        limit = max(1, min(limit, 500))
        pool = pool_provider()
        await _load_channel(pool, cid)
        if kind is None:
            records = await pool.fetch(
                "SELECT * FROM agent_channel_events WHERE channel_id = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                cid,
                limit,
            )
        else:
            records = await pool.fetch(
                "SELECT * FROM agent_channel_events WHERE channel_id = $1 AND kind = $2 "
                "ORDER BY created_at DESC LIMIT $3",
                cid,
                kind,
                limit,
            )
        return [_event_row(r) for r in records]

    @router.post("/agent-channel/{channel_id}/event")
    async def append_event(channel_id: str, body: EventCreate) -> dict[str, typing.Any]:
        """Append an event. State, comms, status, and logs all land here.

        Emits one OTel span so the event lights up in Phoenix / Tempo alongside
        A2A traces. `session.id` is the channel id so every event for a channel
        groups under one session in OTel-native UIs.
        """
        cid = norm_id(channel_id)
        pool = pool_provider()
        await _load_channel(pool, cid)
        with tracer.start_as_current_span(f"agent-channel.event.{body.kind}") as span:
            span.set_attribute("session.id", cid)
            span.set_attribute("agent.id", body.author or "(anonymous)")
            span.set_attribute("openinference.span.kind", "AGENT")
            span.set_attribute("o2r.channel.id", cid)
            span.set_attribute("o2r.channel.event.kind", body.kind)
            span.set_attribute("input.value", json.dumps(body.payload, default=str))
            record = await pool.fetchrow(
                "INSERT INTO agent_channel_events (channel_id, kind, author, payload) "
                "VALUES ($1, $2, $3, $4) RETURNING *",
                cid,
                body.kind,
                body.author,
                body.payload,
            )
        return _event_row(record)

    @router.post("/agent-channel/{channel_id}/close")
    async def close_channel(channel_id: str) -> dict[str, typing.Any]:
        """Mark a channel closed. Events stay readable; this just stamps closed_at."""
        cid = norm_id(channel_id)
        pool = pool_provider()
        await _load_channel(pool, cid)
        record = await pool.fetchrow(
            "UPDATE agent_channels SET closed_at = now() WHERE id = $1 RETURNING *", cid
        )
        return _channel_row(record, base_url)

    return router
