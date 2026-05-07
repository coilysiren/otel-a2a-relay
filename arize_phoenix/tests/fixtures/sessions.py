"""Synthetic Phoenix span fixtures for the topology GIF visual diff.

These mirror the shape Phoenix returns from the GraphQL endpoint, so
the visual diff test can render a deterministic GIF without needing a
live Phoenix in the loop. The fixture is deliberately small but
exercises the parts of the renderer that matter:

- multiple leaves on the star, so the layout has more than one angle,
- multiple hops in both directions, so direction-encoding is exercised,
- one hop with a `failed` status, so the failure color is exercised,
- two hops with the same start time, so tick-quantization is exercised.

Times use trivially-incrementing seconds so the duration footer is
predictable. Span ids do not appear in the renderer's output, so they
are omitted; Phoenix returns them but our reducer never reads them.
"""

from __future__ import annotations

from typing import Any

# A two-leaf, four-hop session. The shape mimics:
#   A -> relay -> B  (forward, completed)
#   B -> relay -> A  (reply, completed)
#   A -> relay (forward to B that fails on the peer side, status=failed)
#   B -> relay (a final ack, completed)
#
# Two pairs of spans share start times so the tick-quantizer collapses
# them into the same frame, producing the visible crossings the issue
# calls out as the visual story.

DEMO_SESSION_ID = "demo-fixture"


def _span(
    name: str,
    start: str,
    end: str,
    agent_id: str,
    *,
    parent_id: str | None = None,
    state: str | None = None,
    span_kind: str = "SERVER",
    text: str | None = None,
) -> dict[str, Any]:
    """Build one Phoenix-shaped span dict.

    The reducer reads `attributes.session.id`, `attributes.agent.id`,
    `attributes.graph.node.parent_id`, `attributes.o2r.task.state`,
    and `attributes.o2r.message.text`, so we populate exactly those.
    """
    attrs: dict[str, Any] = {
        "session": {"id": DEMO_SESSION_ID},
        "agent": {"id": agent_id, "name": "o2r" if agent_id == "relay" else agent_id},
    }
    if parent_id is not None:
        attrs.setdefault("graph", {}).setdefault("node", {})["parent_id"] = parent_id
    if state is not None:
        attrs.setdefault("o2r", {}).setdefault("task", {})["state"] = state
    if text is not None:
        attrs.setdefault("o2r", {}).setdefault("message", {})["text"] = text
    return {
        "name": name,
        "spanKind": span_kind,
        "startTime": start,
        "endTime": end,
        "attributes": attrs,
        "events": [],
    }


def demo_session_spans() -> list[dict[str, Any]]:
    """Return the synthetic span list for `DEMO_SESSION_ID`.

    Hand-tuned timestamps drive a 4-tick animation:

      tick 0: A originates, A->relay
      tick 1: relay->B
      tick 2: B->relay (reply), A->relay (second send)
      tick 3: relay->A (delivered), relay->B (failed)
    """
    spans = [
        _span(
            "a2a.client.send",
            "2026-05-07T10:00:00.0Z",
            "2026-05-07T10:00:00.05Z",
            "A",
            span_kind="CLIENT",
            text="hello B",
        ),
        _span(
            "a2a.task",
            "2026-05-07T10:00:00.1Z",
            "2026-05-07T10:00:00.2Z",
            "relay",
            parent_id="A",
            state="completed",
            text="hello B",
        ),
        _span(
            "a2a.relay.forward",
            "2026-05-07T10:00:00.3Z",
            "2026-05-07T10:00:00.4Z",
            "relay",
            parent_id="A",
            state="completed",
            text="hello B",
        ),
        _span(
            "a2a.task",
            "2026-05-07T10:00:00.5Z",
            "2026-05-07T10:00:00.6Z",
            "B",
            parent_id="relay",
            state="completed",
            text="hello B",
        ),
        _span(
            "a2a.client.send",
            "2026-05-07T10:00:00.7Z",
            "2026-05-07T10:00:00.8Z",
            "B",
            span_kind="CLIENT",
            text="hi A",
        ),
        _span(
            "a2a.task",
            "2026-05-07T10:00:00.7Z",
            "2026-05-07T10:00:00.85Z",
            "relay",
            parent_id="B",
            state="completed",
            text="hi A",
        ),
        _span(
            "a2a.relay.forward",
            "2026-05-07T10:00:00.9Z",
            "2026-05-07T10:00:01.0Z",
            "relay",
            parent_id="B",
            state="completed",
            text="hi A",
        ),
        _span(
            "a2a.task",
            "2026-05-07T10:00:01.0Z",
            "2026-05-07T10:00:01.1Z",
            "A",
            parent_id="relay",
            state="completed",
            text="hi A",
        ),
        _span(
            "a2a.relay.forward",
            "2026-05-07T10:00:01.2Z",
            "2026-05-07T10:00:01.3Z",
            "relay",
            parent_id="A",
            state="failed",
            text="ping?",
        ),
        _span(
            "a2a.task",
            "2026-05-07T10:00:01.4Z",
            "2026-05-07T10:00:01.45Z",
            "B",
            parent_id="relay",
            state="failed",
            text="ping?",
        ),
    ]
    spans.sort(key=lambda s: (s.get("startTime") or "", s.get("name") or ""))
    return spans
