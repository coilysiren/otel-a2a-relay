"""GIF rendering of a session's topology.

Public surface is intentionally tiny:

- `render_session(spans, session_id, out_path)` reduces a list of raw
  Phoenix spans into hops, lays them on a star, and writes an animated
  GIF.

Everything else is internal; the rest of the code touches Phoenix
through `otel_a2a_relay_arize_phoenix.phoenix` and writes pixels through Pillow.
"""

from __future__ import annotations

from otel_a2a_relay_arize_phoenix.viz.render import render_session

__all__ = ["render_session"]
