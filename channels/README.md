# otel-a2a-relay-channels

The Agent Channel coordination layer for the otel-a2a-relay stack: a FastAPI router plus Postgres schema plus Pydantic models for the cross-host agent coordination protocol documented in [`docs/channels-protocol.md`](../docs/channels-protocol.md).

Backend-agnostic. The router is built by `make_router(...)` with caller-supplied `pool_provider` (returns an `asyncpg.Pool`), optional `auth_dependency`, and `base_url` for URL synthesis. Every `POST /agent-channel/{id}/event` emits one OTel span via the global TracerProvider, so channel activity lights up in Phoenix / Tempo alongside A2A traces.

## Usage

```python
from otel_a2a_relay_channels import make_router, SCHEMA, MODE_NAME

router = make_router(
    pool_provider=lambda: my_pool,
    auth_dependency=my_bearer_auth,
    base_url="http://my-backend.internal",
)

async with my_pool.acquire() as conn:
    await conn.execute(SCHEMA)
```

## See also

- [docs/channels-protocol.md](../docs/channels-protocol.md) - protocol spec (event kinds, handoff, liveness, concepts).
- [docs/protocol.md](../docs/protocol.md) - the OTel-span shape every relay-emitted span follows.
- [`coilysiren/backend`](https://github.com/coilysiren/backend) - the reference deployment that mounts this router.
