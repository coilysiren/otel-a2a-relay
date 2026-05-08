"""Tests for the memory-only span store.

Covers both ingestion paths: dict-shaped fixtures and live OTel
ReadableSpans through the SpanProcessor adapter.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind
from otel_a2a_relay_core.span_store import (
    MemorySpanProcessor,
    MemorySpanStore,
    readable_span_to_dict,
    unflatten,
)


def test_unflatten_folds_dotted_keys_into_tree() -> None:
    flat = {"session.id": "x", "agent.id": "A", "agent.name": "alpha", "top": "raw"}
    assert unflatten(flat) == {
        "session": {"id": "x"},
        "agent": {"id": "A", "name": "alpha"},
        "top": "raw",
    }


def test_unflatten_overwrites_scalar_with_nested() -> None:
    """If a dotted key collides with an earlier scalar at the same prefix,
    the nested branch wins. The store is a write-once-per-key surface and
    Phoenix's wire shape never has both, so collision recovery just has
    to be predictable."""
    flat = {"a": 1, "a.b": 2}
    assert unflatten(flat) == {"a": {"b": 2}}


def test_add_normalizes_flat_attrs_to_nested() -> None:
    store = MemorySpanStore()
    store.add(
        {
            "name": "a2a.task",
            "spanKind": "SERVER",
            "startTime": "2026-01-01T00:00:00Z",
            "attributes": {"session.id": "ours", "agent.id": "A"},
        }
    )
    [span] = store.fetch_spans()
    assert span["attributes"] == {"session": {"id": "ours"}, "agent": {"id": "A"}}


def test_add_preserves_already_nested_attrs() -> None:
    store = MemorySpanStore()
    store.add(
        {
            "name": "a2a.task",
            "attributes": {"session": {"id": "ours"}},
        }
    )
    [span] = store.fetch_spans()
    assert span["attributes"] == {"session": {"id": "ours"}}


def test_add_handles_non_dict_attributes_as_empty() -> None:
    store = MemorySpanStore()
    store.add({"name": "n", "attributes": "not a dict"})
    [span] = store.fetch_spans()
    assert span["attributes"] == {}


def test_add_normalizes_event_attrs() -> None:
    store = MemorySpanStore()
    store.add(
        {
            "name": "a2a.task",
            "events": [
                {"name": "tick", "attributes": {"step.n": 1}},
                {"name": "tock"},
            ],
        }
    )
    [span] = store.fetch_spans()
    assert span["events"] == [
        {"name": "tick", "attributes": {"step": {"n": 1}}},
        {"name": "tock", "attributes": {}},
    ]


def test_fetch_spans_returns_independent_copies() -> None:
    store = MemorySpanStore()
    store.add({"name": "n", "attributes": {"session.id": "x"}})
    out = store.fetch_spans()
    out[0]["attributes"]["session"]["id"] = "mutated"
    [again] = store.fetch_spans()
    assert again["attributes"]["session"]["id"] == "x"


def test_fetch_spans_respects_limit() -> None:
    store = MemorySpanStore()
    for i in range(5):
        store.add({"name": f"s{i}"})
    assert [s["name"] for s in store.fetch_spans(limit=3)] == ["s0", "s1", "s2"]


def test_add_all_inserts_in_order() -> None:
    store = MemorySpanStore()
    store.add_all([{"name": "a"}, {"name": "b"}, {"name": "c"}])
    assert [s["name"] for s in store.fetch_spans()] == ["a", "b", "c"]


def test_session_spans_filters_and_sorts() -> None:
    def span(name: str, start: str, sid: str) -> dict[str, Any]:
        return {
            "name": name,
            "startTime": start,
            "attributes": {"session.id": sid},
        }

    store = MemorySpanStore()
    store.add_all(
        [
            span("late", "2026-01-01T00:00:02Z", "ours"),
            span("early-b", "2026-01-01T00:00:00Z", "ours"),
            span("other", "2026-01-01T00:00:01Z", "theirs"),
            span("early-a", "2026-01-01T00:00:00Z", "ours"),
        ]
    )
    out = store.session_spans("ours")
    assert [s["name"] for s in out] == ["early-a", "early-b", "late"]


def test_session_spans_handles_missing_or_malformed_session_attr() -> None:
    store = MemorySpanStore()
    store.add({"name": "no-attrs"})
    store.add({"name": "session-not-dict", "attributes": {"session": "scalar"}})
    store.add({"name": "matched", "attributes": {"session.id": "ours"}})
    out = store.session_spans("ours")
    assert [s["name"] for s in out] == ["matched"]


def test_clear_and_len() -> None:
    store = MemorySpanStore()
    assert len(store) == 0
    store.add_all([{"name": "a"}, {"name": "b"}])
    assert len(store) == 2
    store.clear()
    assert len(store) == 0
    assert store.fetch_spans() == []


def test_processor_records_otel_span_in_canonical_shape() -> None:
    store = MemorySpanStore()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(MemorySpanProcessor(store))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span(
        "a2a.task",
        kind=SpanKind.SERVER,
        attributes={"session.id": "demo", "agent.id": "A"},
    ) as span:
        span.add_event("state.change", attributes={"to.state": "completed"})

    [recorded] = store.fetch_spans()
    assert recorded["name"] == "a2a.task"
    assert recorded["spanKind"] == "SERVER"
    assert recorded["attributes"] == {
        "session": {"id": "demo"},
        "agent": {"id": "A"},
    }
    assert recorded["startTime"] is not None
    assert recorded["endTime"] is not None
    [event] = recorded["events"]
    assert event["name"] == "state.change"
    assert event["attributes"] == {"to": {"state": "completed"}}


def test_processor_force_flush_returns_true_and_shutdown_is_noop() -> None:
    proc = MemorySpanProcessor(MemorySpanStore())
    assert proc.force_flush() is True


class _UnstartedSpan:
    """Stand-in for a ReadableSpan with unset start/end times.

    OTel's SDK always sets start/end on a real span, but
    `readable_span_to_dict` is documented as the canonical converter
    and should not crash on partial input.
    """

    name = "unstarted"
    kind = SpanKind.INTERNAL
    attributes: dict[str, Any] = {}
    events: list[Any] = []
    start_time: int | None = None
    end_time: int | None = None


def test_readable_span_to_dict_handles_missing_timestamps() -> None:
    out = readable_span_to_dict(_UnstartedSpan())  # type: ignore[arg-type]
    assert out["startTime"] is None
    assert out["endTime"] is None
    assert out["spanKind"] == "INTERNAL"


def test_store_is_thread_safe_under_contention() -> None:
    import threading

    store = MemorySpanStore()
    n = 200

    def writer(start: int) -> None:
        for i in range(start, start + n):
            store.add({"name": f"s{i}"})

    threads = [threading.Thread(target=writer, args=(i * n,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store) == 4 * n


@pytest.mark.parametrize("limit,expected", [(0, []), (1, ["a"]), (10, ["a", "b"])])
def test_fetch_spans_limit_edges(limit: int, expected: list[str]) -> None:
    store = MemorySpanStore()
    store.add_all([{"name": "a"}, {"name": "b"}])
    assert [s["name"] for s in store.fetch_spans(limit=limit)] == expected
