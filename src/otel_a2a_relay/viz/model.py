"""Reduce raw Phoenix spans into a hop list and a star layout.

A `Hop` is one A2A interaction edge: a source endpoint hands work to a
destination endpoint at a particular instant. The renderer's job is to
animate hops in start-time order, against a fixed star layout where
the hub is the relay and every other endpoint is a leaf on the rim.

The hub is auto-detected from spans (`agent.id == "relay"` or
`agent.name == "o2r"`) so this module never needs configuration. If
the relay is missing from the spans entirely (degenerate case), the
first node by sort order is treated as the hub so the rendering still
produces a recognizable star instead of crashing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from otel_a2a_relay.phoenix import attrs as span_attrs

HUB_AGENT_IDS = frozenset({"relay"})
HUB_AGENT_NAMES = frozenset({"o2r"})


@dataclass(frozen=True)
class Hop:
    """One animated edge in the topology."""

    src: str  # endpoint id (relay or agent.id)
    dst: str  # endpoint id (relay or agent.id)
    start: float  # unix-ish ordering scalar; only relative order matters
    duration: float  # seconds, for footer wall-clock math
    status: str  # 'completed' | 'failed' | 'in-flight'
    label: str  # span name, for hover/debug; not currently rendered
    text: str  # `o2r.message.text` if present, else "" - rendered in the right log


@dataclass(frozen=True)
class Session:
    """Reduced view of one session's spans."""

    session_id: str
    hub: str
    leaves: tuple[str, ...]  # sorted, deterministic
    hops: tuple[Hop, ...]
    span_count: int
    duration_s: float


def _parse_time(s: str | None) -> float:
    """Phoenix returns ISO-8601 with `Z`. Normalize to a float for sort."""
    if not s:
        return 0.0
    # `fromisoformat` accepts `+00:00` but not the trailing `Z` until
    # 3.11+. The project pins 3.13 so this is fine, but be defensive.
    cleaned = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return 0.0


def _is_hub(a: dict[str, Any]) -> bool:
    return a.get("agent.id") in HUB_AGENT_IDS or a.get("agent.name") in HUB_AGENT_NAMES


def _endpoint_for(span: dict[str, Any]) -> str:
    """The endpoint id for a span: hub-name when the span is the relay's,
    else the `agent.id`. Falls back to the span name for spans that are
    missing both (shouldn't happen in well-formed sessions, but the
    renderer should still produce something instead of crashing).
    """
    a = span_attrs(span)
    if _is_hub(a):
        return "relay"
    return str(a.get("agent.id") or a.get("agent.name") or span.get("name") or "?")


def _status_for(span: dict[str, Any]) -> str:
    a = span_attrs(span)
    state = a.get("o2r.task.state")
    if state == "failed":
        return "failed"
    if state in {"working", "submitted", "input-required"}:
        return "in-flight"
    if state == "completed":
        return "completed"
    # Span carries no explicit task state - synthesize from the events
    # that the relay emits on state change. A `final=true` event
    # implies the hop completed.
    for ev in span.get("events") or []:
        ev_attrs = span_attrs(ev)
        if ev_attrs.get("final") is True:
            return "completed"
    return "completed"


def reduce_spans(
    spans: list[dict[str, Any]],
    session_id: str,
) -> Session:
    """Project spans onto the hop model. Caller has already filtered to
    one session and sorted by `(startTime, name)`.

    The hop derivation is conservative: one hop per span that has a
    `graph.node.parent_id`, going parent -> agent. Spans without a
    parent are the originating client-side spans and contribute a
    self-loop on the originator (rendered as a node pulse, not an
    edge).
    """
    if not spans:
        return Session(
            session_id=session_id, hub="relay", leaves=(), hops=(), span_count=0, duration_s=0.0
        )

    starts = [_parse_time(s.get("startTime")) for s in spans]
    ends = [_parse_time(s.get("endTime") or s.get("startTime")) for s in spans]
    duration = max(0.0, max(ends) - min(starts))

    hops: list[Hop] = []
    endpoints: set[str] = set()
    hub_seen = False

    for s, st in zip(spans, starts, strict=True):
        a = span_attrs(s)
        agent = _endpoint_for(s)
        endpoints.add(agent)
        if agent == "relay":
            hub_seen = True
        parent = a.get("graph.node.parent_id")
        if not parent:
            # Self-loop: the agent originates work. Renderer treats the
            # zero-length hop as a node-pulse animation.
            hops.append(
                Hop(
                    src=agent,
                    dst=agent,
                    start=st,
                    duration=max(0.0, ends[spans.index(s)] - st),
                    status=_status_for(s),
                    label=str(s.get("name") or ""),
                    text=str(a.get("o2r.message.text") or ""),
                )
            )
            continue
        src = "relay" if parent in HUB_AGENT_IDS else str(parent)
        endpoints.add(src)
        if src == "relay":
            hub_seen = True
        hops.append(
            Hop(
                src=src,
                dst=agent,
                start=st,
                duration=max(0.0, ends[spans.index(s)] - st),
                status=_status_for(s),
                label=str(s.get("name") or ""),
                text=str(a.get("o2r.message.text") or ""),
            )
        )

    hub = "relay" if hub_seen else sorted(endpoints)[0]
    leaves = tuple(sorted(e for e in endpoints if e != hub))
    return Session(
        session_id=session_id,
        hub=hub,
        leaves=leaves,
        hops=tuple(hops),
        span_count=len(spans),
        duration_s=duration,
    )


def star_layout(
    hub: str,
    leaves: tuple[str, ...],
    width: int,
    height: int,
    margin: int = 36,
) -> dict[str, tuple[float, float]]:
    """Place the hub at the canvas center and arrange leaves on a circle.

    Leaf order is the input order, which the caller has already made
    deterministic by sorting alphabetically. The first leaf is placed
    at 12 o'clock and the rest go clockwise. With only one leaf, two
    leaves opposite, three at 12/4/8 - the standard star you'd draw on
    a whiteboard.
    """
    cx, cy = width / 2.0, height / 2.0
    radius = min(width, height) / 2.0 - margin
    out: dict[str, tuple[float, float]] = {hub: (cx, cy)}
    n = len(leaves)
    if n == 0:
        return out
    # Two leaves on a vertical line read as boring; rotate to horizontal
    # so the chord runs across the canvas and the bow on each direction
    # shows above/below the hub. For n>=3 the natural top-anchored star
    # is recognizable, so we keep it.
    start = 0.0 if n == 2 else -math.pi / 2
    for i, leaf in enumerate(leaves):
        theta = start + (2 * math.pi * i / n)
        x = cx + radius * math.cos(theta)
        y = cy + radius * math.sin(theta)
        out[leaf] = (x, y)
    return out
