"""Frozen-time shim for the LUCA-flow demo.

When `LUCA_FREEZE_TIME` is set in the environment, every timestamp that
gets serialized into `dist/` (changelog "Generated", trace `ts_human`,
trace `ts_unix`) returns a fixed value. That makes the demo's outputs
byte-deterministic so they can be locked in via snapshot tests.

The shim deliberately does NOT replace `time.time()` callsites used for
poll loops or sleeps - only the ones whose values land in the dist
artifacts. Those are routed through `now_iso()` / `now_unix()` here.

Env var format: an ISO-8601 UTC timestamp like `2026-01-01T00:00:00Z`.
Anything `datetime.fromisoformat` accepts works (the trailing `Z` is
normalized to `+00:00`).
"""

from __future__ import annotations

import os
import time as _real_time
import uuid as _real_uuid
from datetime import UTC, datetime
from itertools import count

_FREEZE_ENV = "LUCA_FREEZE_TIME"
_id_counter = count(1)


def _frozen_dt() -> datetime | None:
    raw = os.environ.get(_FREEZE_ENV)
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def now_iso() -> str:
    """UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` shape; frozen if env var set."""
    dt = _frozen_dt() or datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_unix() -> float:
    """POSIX seconds; frozen if env var set."""
    dt = _frozen_dt()
    if dt is None:
        return _real_time.time()
    return dt.timestamp()


def is_frozen() -> bool:
    return os.environ.get(_FREEZE_ENV) is not None


def hex8() -> str:
    """8-char hex id; counter-based when frozen, real uuid otherwise.

    Used for JSON-RPC `id` and A2A messageId/taskId fields. The counter is
    per-process, which is enough because each LUCA peer runs in its own
    subprocess with its own deterministic call order.
    """
    if not is_frozen():
        return _real_uuid.uuid4().hex[:8]
    return f"{next(_id_counter):08x}"
