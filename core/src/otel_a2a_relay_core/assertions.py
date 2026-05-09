"""Reusable assertion macros for span-store tests and corpus validation.

Each macro takes either a list of canonical Phoenix-shaped span dicts or
a `MemorySpanStore`, and returns a list of violation strings. Empty list
means the invariant held. Callers turn those into pytest assertions:

    violations = every_tool_call_is_observed(spans)
    assert not violations, "\\n".join(violations)

The two macros named in the dispatch ticket (`every_tool_call_is_observed`,
`no_pii_in_attributes`) are joined by a small set of related v0.3
invariants - `agent.role` mandatory, failure-class on errors, session.id
on every span, graph.node.parent_id referential integrity. Adding a new
macro is preferred over expanding an existing one.

The macros consume the canonical (nested) attribute shape that
`MemorySpanStore` produces and that `corpus.load_fixture` returns. Pass
flat-keyed input through the store first if you have it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from otel_a2a_relay_core.span_store import MemorySpanStore

type SpanLike = dict[str, Any]
type Spans = Sequence[SpanLike] | MemorySpanStore


def _materialize(spans: Spans) -> list[SpanLike]:
    if isinstance(spans, MemorySpanStore):
        return list(spans.fetch_spans(limit=1_000_000))
    return list(spans)


def _attr(span: SpanLike, *path: str) -> Any:
    """Walk a dotted attribute path on a canonical-shape span. Returns None on miss."""
    cur: Any = span.get("attributes") or {}
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _kind(span: SpanLike) -> str:
    return str(_attr(span, "openinference", "span", "kind") or span.get("spanKind") or "")


def _is_relay_emitted(span: SpanLike) -> bool:
    """Spans the relay process emits.

    Heuristic: name starts with `a2a.` (the relay's own emission prefix
    per `docs/protocol.md`). Caller-flow spans like `llm.generate` or
    `tool.search_inventory` are NOT relay-emitted; the v0.3 invariants
    do not apply to them.
    """
    return str(span.get("name") or "").startswith("a2a.")


# Default PII patterns. Conservative: emails and US-style SSNs only. Callers
# pass `extra_patterns=[...]` for caller-specific rules. Each pattern is a
# `(label, compiled_re)` tuple so violation messages are legible.
_DEFAULT_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
)


def _walk_strings(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    """Yield `(jsonpath, string_value)` for every string leaf in `value`."""
    if isinstance(value, str):
        yield prefix or "<root>", value
    elif isinstance(value, dict):
        for k, v in value.items():
            child_prefix = f"{prefix}.{k}" if prefix else k
            yield from _walk_strings(v, child_prefix)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk_strings(v, f"{prefix}[{i}]")


def every_tool_call_is_observed(spans: Spans) -> list[str]:
    """Every LLM span that declares a tool call has a sibling TOOL span.

    Detection of "declared a tool call": the LLM span's attributes carry
    any `gen_ai.tool.*` field, or the OTel-conventional
    `llm.tool_calls` attribute, or `tools.*`. Loose by design; the
    invariant is "if you talked about a tool, the tool span shows up,"
    not a perfect schema match.

    "Sibling": same `session.id`, span kind == `TOOL`, start_time inside
    the LLM span's [start, end] window.
    """
    materialized = _materialize(spans)
    violations: list[str] = []

    tool_spans_by_session: dict[str, list[SpanLike]] = {}
    for s in materialized:
        if _kind(s) != "TOOL":
            continue
        sid = _attr(s, "session", "id")
        if isinstance(sid, str):
            tool_spans_by_session.setdefault(sid, []).append(s)

    for s in materialized:
        if _kind(s) != "LLM":
            continue
        attrs = s.get("attributes") or {}
        declares_tool = any("tool" in k or "tool_calls" in k for k in _flat_keys(attrs))
        if not declares_tool:
            continue
        sid = _attr(s, "session", "id")
        if not isinstance(sid, str):
            violations.append(f"LLM span {s.get('name')!r} declares a tool but has no session.id")
            continue
        start = s.get("startTime") or ""
        end = s.get("endTime") or ""
        candidates = tool_spans_by_session.get(sid, [])
        observed = any(
            (c.get("startTime") or "") >= start and (c.get("endTime") or "") <= end
            for c in candidates
        )
        if not observed:
            violations.append(
                f"LLM span {s.get('name')!r} (session {sid}) declares a tool call "
                f"but no TOOL span observed in its time window"
            )
    return violations


def _flat_keys(attrs: Any, prefix: str = "") -> Iterable[str]:
    if not isinstance(attrs, dict):
        return
    for k, v in attrs.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _flat_keys(v, key)
        else:
            yield key


def no_pii_in_attributes(
    spans: Spans,
    extra_patterns: Sequence[tuple[str, re.Pattern[str]]] = (),
    skip_keys: Sequence[str] = (),
) -> list[str]:
    """No string-valued attribute matches a PII pattern.

    Default patterns cover emails and US SSNs. Callers add their own:

        from otel_a2a_relay_core.assertions import no_pii_in_attributes
        custom = [("api_key", re.compile(r"sk-[A-Za-z0-9]{32,}"))]
        violations = no_pii_in_attributes(spans, extra_patterns=custom)

    `skip_keys` accepts dotted attribute paths to ignore (e.g.
    `("input.value", "output.value")` for fixtures whose payloads
    legitimately carry user-shaped strings).
    """
    patterns = tuple(_DEFAULT_PII_PATTERNS) + tuple(extra_patterns)
    skip_set = set(skip_keys)
    violations: list[str] = []
    for s in _materialize(spans):
        for path, value in _walk_strings(s.get("attributes") or {}):
            if path in skip_set:
                continue
            for label, pat in patterns:
                if pat.search(value):
                    violations.append(
                        f"span {s.get('name')!r} attribute {path!r} matched {label}: {value!r}"
                    )
                    break
        for ev in s.get("events") or []:
            for path, value in _walk_strings(ev.get("attributes") or {}):
                full = f"events[{ev.get('name')}].{path}"
                if full in skip_set or path in skip_set:
                    continue
                for label, pat in patterns:
                    if pat.search(value):
                        violations.append(
                            f"span {s.get('name')!r} event {ev.get('name')!r} "
                            f"attribute {path!r} matched {label}: {value!r}"
                        )
                        break
    return violations


def every_relay_emitted_span_carries_agent_role(spans: Spans) -> list[str]:
    """v0.3 mandate: every span the relay emits carries `agent.role`.

    Caller-flow spans (`llm.*`, `tool.*`) are out of scope.
    """
    violations: list[str] = []
    for s in _materialize(spans):
        if not _is_relay_emitted(s):
            continue
        if not _attr(s, "agent", "role"):
            violations.append(f"relay-emitted span {s.get('name')!r} missing agent.role")
    return violations


def every_relay_failure_has_class(spans: Spans) -> list[str]:
    """Any erroring relay span has `o2r.relay.failure_class`.

    "Erroring" is detected loosely: the span carries an `exception`
    event, or the span name itself signals a failure shape (`reject`,
    `forward` with a failure_class set elsewhere). The invariant is that
    the bucket attribute exists, not that it has any particular value.
    """
    violations: list[str] = []
    for s in _materialize(spans):
        if not _is_relay_emitted(s):
            continue
        has_exception = any((ev.get("name") or "") == "exception" for ev in s.get("events") or [])
        is_reject = "reject" in str(s.get("name") or "")
        if not (has_exception or is_reject):
            continue
        if not _attr(s, "o2r", "relay", "failure_class"):
            violations.append(
                f"erroring relay span {s.get('name')!r} missing o2r.relay.failure_class"
            )
    return violations


def every_relay_emitted_span_carries_session_id(spans: Spans) -> list[str]:
    """Every relay-emitted span carries `session.id`.

    Caller-flow spans inside `using_session(...)` propagate via context
    and aren't required to set the attribute redundantly.
    """
    violations: list[str] = []
    for s in _materialize(spans):
        if not _is_relay_emitted(s):
            continue
        if not _attr(s, "session", "id"):
            violations.append(f"relay-emitted span {s.get('name')!r} missing session.id")
    return violations


def graph_node_parent_resolves(spans: Spans) -> list[str]:
    """Any `graph.node.parent_id` points at an `agent.id` present in the corpus.

    Catches stale parent references from copy-pasted fixtures.
    """
    materialized = _materialize(spans)
    known_agents: set[str] = set()
    for s in materialized:
        agent_id = _attr(s, "agent", "id")
        if isinstance(agent_id, str):
            known_agents.add(agent_id)
        # `graph.node.id` can stand alone as an agent declaration.
        node_id = _attr(s, "graph", "node", "id")
        if isinstance(node_id, str):
            known_agents.add(node_id)

    violations: list[str] = []
    for s in materialized:
        parent = _attr(s, "graph", "node", "parent_id")
        if parent is None:
            continue
        if not isinstance(parent, str) or parent not in known_agents:
            violations.append(
                f"span {s.get('name')!r} has graph.node.parent_id={parent!r} "
                f"but no agent with that id is observed in the corpus"
            )
    return violations


_VALID_TASK_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"working", "canceled"}),
    "working": frozenset({"completed", "failed", "canceled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "canceled": frozenset(),
}


def task_state_progression_is_valid(spans: Spans) -> list[str]:
    """Each task span's `o2r.task.state_change` events form a valid chain.

    Valid edges: submitted -> working|canceled, working -> completed|failed|canceled.
    Terminal states have no outgoing edges.
    """
    violations: list[str] = []
    for s in _materialize(spans):
        if s.get("name") != "a2a.task":
            continue
        prev: str | None = None
        for ev in s.get("events") or []:
            if (ev.get("name") or "") != "o2r.task.state_change":
                continue
            attrs = ev.get("attributes") or {}
            from_state = attrs.get("from")
            to_state = attrs.get("to")
            if not isinstance(from_state, str) or not isinstance(to_state, str):
                violations.append(
                    f"task {s.get('name')!r} state_change event missing from/to: {attrs!r}"
                )
                continue
            if prev is not None and prev != from_state:
                violations.append(
                    f"task {s.get('name')!r} state_change sequence broken: "
                    f"prev to-state={prev!r} but next from-state={from_state!r}"
                )
            allowed = _VALID_TASK_STATE_TRANSITIONS.get(from_state)
            if allowed is None:
                violations.append(f"task {s.get('name')!r} unknown from-state {from_state!r}")
            elif to_state not in allowed:
                violations.append(
                    f"task {s.get('name')!r} invalid transition {from_state!r} -> {to_state!r}"
                )
            prev = to_state
    return violations


def stream_chunk_seqs_are_monotonic(spans: Spans) -> list[str]:
    """Each task span's `a2a.message.stream_chunk` events have strictly increasing seqs.

    The terminal chunk (final: true) must be the last and only chunk
    flagged. Catches dropped, duplicated, or reordered chunks in
    fixtures and live captures.
    """
    violations: list[str] = []
    for s in _materialize(spans):
        if s.get("name") != "a2a.task":
            continue
        seen_final = False
        last_seq: int | None = None
        for ev in s.get("events") or []:
            if (ev.get("name") or "") != "a2a.message.stream_chunk":
                continue
            attrs = ev.get("attributes") or {}
            seq = attrs.get("seq")
            final = bool(attrs.get("final"))
            if not isinstance(seq, int):
                violations.append(
                    f"task {s.get('name')!r} stream_chunk missing integer seq: {attrs!r}"
                )
                continue
            if last_seq is not None and seq <= last_seq:
                violations.append(
                    f"task {s.get('name')!r} stream_chunk seq {seq} not greater than {last_seq}"
                )
            if seen_final:
                violations.append(f"task {s.get('name')!r} stream_chunk after final: seq={seq}")
            if final:
                seen_final = True
            last_seq = seq
    return violations
