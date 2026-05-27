# Animated session topology

`assets/topology.png` is the protocol-shape illustration, a fixed cartoon. `assets/session-topology.gif` (the README hero) is the temporal one: real OTel spans for one session, animated by start time, against the same star.

```sh
make phoenix-fg                # operator-owned, in another terminal
make demo                      # produces a `demo` session
OUT=mine.gif make gif CTX=demo # writes mine.gif from real Phoenix spans
```

The renderer pulls every span tagged with `session.id == $CTX` from Phoenix's GraphQL endpoint, reduces them into hops (parent -> agent), auto-detects the relay as the hub, sorts the leaves alphabetically for a stable color palette, and animates each hop in start-time order. Two hops in the same tick render with their arcs bowed in opposite directions, so a forward-and-return pair reads as crossings rather than a single overdrawn line.

Determinism is baked in: same `session.id` against the same Phoenix DB produces a byte-identical GIF. Tests assert this against a synthetic-span fixture in `arize_phoenix/tests/fixtures/sessions.py`, so a renderer regression fails CI before the README hero drifts. The renderer is Pillow-only (no matplotlib); freetype ships with Pillow, JetBrains Mono ships in `arize_phoenix/src/otel_a2a_relay_arize_phoenix/viz/assets/`, the GIF palette is built once and reused across frames.

To intentionally regenerate the README hero after a renderer change, run `python -m tests.fixtures.regen_session_gifs` from `arize_phoenix/` and commit the new bytes.

The viz extra is opt-in:

```sh
uv sync --extra viz
```

`make gif` does this automatically. The base relay install stays Pillow-free.

## See also

- [README.md](../README.md) - where the hero GIF lives.
- [quickstart.md](quickstart.md) - bring-up recipes for both backends.
