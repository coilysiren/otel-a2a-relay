"""Memory-only span store. Zero IO. For tests and fixture-corpus replay.

Phoenix is the production span store. The harness, client, and viz all
read spans in Phoenix's GraphQL response shape. This module produces
the same shape from a list of in-process spans, so tests can exercise
the same query helpers that prod uses without standing up Phoenix.

Canonical span shape (what Phoenix returns, what this store stores):

  name        - str
  spanKind    - str (OTel span kind, all caps)
  startTime   - ISO-8601 string
  endTime     - ISO-8601 string
  attributes  - re-nested dict (dotted keys folded back into a tree)
  events      - list of `{name, attributes}` dicts

Two ingestion paths:

- `add(dict)`: drop in a Phoenix-shaped span node directly. Attributes
  may be supplied either nested (Phoenix's exact wire shape) or flat
  with dotted keys. Flat input is folded at ingest so consumers always
  see the canonical shape on the way out.
- `MemorySpanProcessor(store)`: an OTel SpanProcessor that converts
  each finished ReadableSpan into the canonical shape on export.

The store is the smallest concrete unblock for the trace-zoo (#17) and
the assertion macros (#71). Production reads still go through Phoenix.
"""

from __future__ import annotations

import copy
import datetime as _dt
import threading
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor


def unflatten(d: dict[str, Any]) -> dict[str, Any]:
    """Fold dotted keys (`session.id`) back into a nested dict.

    Inverse of `arize_phoenix.phoenix.flatten`. Phoenix returns the
    nested shape over its wire; this is what tests need to round-trip
    flat-keyed test inputs through the same query helpers production
    uses.
    """
    out: dict[str, Any] = {}
    for key, value in d.items():
        parts = key.split(".")
        cur = out
        for p in parts[:-1]:
            existing = cur.get(p)
            if not isinstance(existing, dict):
                existing = {}
                cur[p] = existing
            cur = existing
        cur[parts[-1]] = value
    return out


def _normalize_attrs(attrs: Any) -> dict[str, Any]:
    if not isinstance(attrs, dict):
        return {}
    if any("." in k for k in attrs):
        return unflatten(attrs)
    return copy.deepcopy(attrs)


def _normalize_span(span: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(span)
    out["attributes"] = _normalize_attrs(span.get("attributes") or {})
    events = []
    for ev in span.get("events") or []:
        events.append(
            {
                "name": ev.get("name"),
                "attributes": _normalize_attrs(ev.get("attributes") or {}),
            }
        )
    out["events"] = events
    return out


def _session_id_of(span: dict[str, Any]) -> Any:
    session = (span.get("attributes") or {}).get("session")
    if not isinstance(session, dict):
        return None
    return session.get("id")


class MemorySpanStore:
    """Thread-safe in-memory span store. Returns Phoenix-shaped dicts.

    Spans come out as deep copies; mutating a returned span never
    affects the store. Insertion order is preserved.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: list[dict[str, Any]] = []

    def add(self, span: dict[str, Any]) -> None:
        normalized = _normalize_span(span)
        with self._lock:
            self._spans.append(normalized)

    def add_all(self, spans: list[dict[str, Any]]) -> None:
        for s in spans:
            self.add(s)

    def fetch_spans(self, limit: int = 200) -> list[dict[str, Any]]:
        """All spans in insertion order, deep-copied, capped at `limit`."""
        with self._lock:
            return [copy.deepcopy(s) for s in self._spans[:limit]]

    def session_spans(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Spans where `attributes.session.id == session_id`.

        Sorted by `(startTime, name)` so consumers see the same
        deterministic ordering Phoenix's `session_spans` produces.
        """
        out = [s for s in self.fetch_spans(limit) if _session_id_of(s) == session_id]
        out.sort(key=lambda s: (s.get("startTime") or "", s.get("name") or ""))
        return out

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._spans)


def _iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    return _dt.datetime.fromtimestamp(ns / 1e9, tz=_dt.UTC).isoformat()


def readable_span_to_dict(span: ReadableSpan) -> dict[str, Any]:
    """Convert an OTel ReadableSpan to the canonical Phoenix dict shape.

    Public so tests can render fixtures from real instrumentation runs
    without standing up the SpanProcessor wiring.
    """
    events = []
    for ev in span.events or []:
        events.append(
            {
                "name": ev.name,
                "attributes": unflatten(dict(ev.attributes or {})),
            }
        )
    kind = span.kind.name if span.kind is not None else ""
    return {
        "name": span.name,
        "spanKind": kind,
        "startTime": _iso(span.start_time),
        "endTime": _iso(span.end_time),
        "attributes": unflatten(dict(span.attributes or {})),
        "events": events,
    }


class MemorySpanProcessor(SpanProcessor):
    """OTel SpanProcessor that records finished spans into a MemorySpanStore.

    Pair with a `TracerProvider` (or `tracing.bootstrap(extra_processor=...)`)
    so the test driver and the prod-facing instrumentation traverse the
    same code path.
    """

    def __init__(self, store: MemorySpanStore) -> None:
        self._store = store

    def on_start(
        self, _span: Any, _parent_context: Any = None
    ) -> None:  # pragma: no cover - SDK contract
        return None

    def on_end(self, span: ReadableSpan) -> None:
        self._store.add(readable_span_to_dict(span))

    def shutdown(self) -> None:  # pragma: no cover - SDK contract
        return None

    def force_flush(self, _timeout_millis: int = 30000) -> bool:
        return True
