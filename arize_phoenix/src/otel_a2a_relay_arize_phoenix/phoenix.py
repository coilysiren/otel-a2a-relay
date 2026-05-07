"""Phoenix GraphQL helpers shared between `view` and `gif`.

Phoenix exposes spans through a single GraphQL endpoint at `/graphql`.
The relay only ever needs the per-session reduction: pull spans, filter
by `session.id == $CTX`, sort deterministically. Both the readable
transcript (`view`) and the animated topology GIF (`gif`) consume the
same shape, so the fetch and the attribute flattener live here.

The flattener exists because Phoenix returns attributes as a re-nested
dict (dotted keys folded back into a tree), and every consumer wants
them dotted again so they can ask for `session.id` or `agent.name`
directly.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

DEFAULT_PHOENIX_URL = "http://127.0.0.1:6006"

GRAPHQL = """
query SpansBySession($limit: Int!) {
  projects(first: 1) {
    edges {
      node {
        spans(first: $limit) {
          edges {
            node {
              name
              spanKind
              startTime
              endTime
              attributes
              events {
                name
                attributes
              }
            }
          }
        }
      }
    }
  }
}
"""


def fetch_spans(phoenix_url: str, limit: int = 200) -> list[dict[str, Any]]:
    """Pull every span Phoenix knows about, up to `limit`.

    Returns the raw span nodes as dicts. Filtering by session is the
    caller's job because consumers want different post-processing.
    """
    r = httpx.post(
        f"{phoenix_url.rstrip('/')}/graphql",
        json={"query": GRAPHQL, "variables": {"limit": limit}},
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"graphql errors: {data['errors']}")
    edges = data["data"]["projects"]["edges"]
    if not edges:
        return []
    span_edges = edges[0]["node"]["spans"]["edges"]
    return [e["node"] for e in span_edges]


def flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    """Re-flatten Phoenix's nested attribute dict back to dotted keys."""
    out: dict[str, Any] = {}
    if not isinstance(d, dict):
        return {prefix: d} if prefix else {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def attrs(span: dict[str, Any]) -> dict[str, Any]:
    """Return a span's attributes flattened to dotted keys."""
    raw = span.get("attributes")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return flatten(raw or {})


def session_spans(
    phoenix_url: str,
    session_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Spans for one session, sorted by `(startTime, name)` for determinism.

    The secondary sort on `name` matters when two spans share a start
    time (relay-side and peer-side of the same hop, since they wrap the
    same instant). Stable input order is what makes the rendered GIF
    byte-identical run over run.
    """
    spans = [s for s in fetch_spans(phoenix_url, limit) if attrs(s).get("session.id") == session_id]
    spans.sort(key=lambda s: (s.get("startTime") or "", s.get("name") or ""))
    return spans
