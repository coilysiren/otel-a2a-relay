"""Visual diff + behavioral tests for the topology GIF renderer.

Two layers of test, in priority order:

1. Byte-exact GIF comparison against `tests/fixtures/sessions/*.gif`.
   This is the hard guard: any change in the renderer or its inputs
   that would alter the published artifact fails the build. To
   intentionally update the baseline, run `make gif-fixture-update`
   and commit the diff.

2. Behavioral checks on the reduce-and-layout step. These confirm the
   star is recognizable, the hub is auto-detected, leaves are sorted
   for stable color assignment, and tick quantization respects the
   target frame budget.

The fixture lives in `tests/fixtures/sessions.py` as plain Python data,
so a regression in the synthetic span shape causes a noisy test failure
rather than silently using stale recorded input.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from otel_a2a_relay.viz import render_session
from otel_a2a_relay.viz.model import reduce_spans, star_layout
from otel_a2a_relay.viz.render import (
    FRAME_MS,
    FRAMES_PER_TICK,
    HEIGHT,
    WIDTH,
    _quantize_ticks,
)
from tests.fixtures.sessions import DEMO_SESSION_ID, demo_session_spans

# The byte-exact baseline doubles as the README hero artifact. One file,
# one source of truth, regenerated through `make gif-fixture-update`.
BASELINE_PATH = Path(__file__).parent.parent / "assets" / "session-topology.gif"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_demo_session_gif_byte_exact(tmp_path: Path) -> None:
    """Render the demo fixture and assert bytes match the committed baseline.

    This is the visual diff in CI. Failure modes:
    - someone changed the renderer (intentional or not) without
      regenerating the baseline,
    - the synthetic fixture changed,
    - Pillow upgraded across a determinism-affecting boundary.

    The fix in all three cases is the same: review the new GIF visually,
    then `make gif-fixture-update` to commit it as the new baseline.
    """
    out = tmp_path / "session.gif"
    render_session(demo_session_spans(), DEMO_SESSION_ID, out)
    assert BASELINE_PATH.exists(), (
        f"missing baseline at {BASELINE_PATH}; run `make gif-fixture-update` to create it"
    )
    actual = _sha256(out)
    expected = _sha256(BASELINE_PATH)
    assert actual == expected, (
        f"GIF bytes drifted from baseline.\n"
        f"  baseline sha: {expected}\n"
        f"  current sha:  {actual}\n"
        f"If this change is intentional, run `make gif-fixture-update` "
        f"and commit the new baseline."
    )


def test_demo_session_gif_is_byte_stable_across_runs(tmp_path: Path) -> None:
    """Two renders of the same input must produce identical bytes."""
    a = tmp_path / "a.gif"
    b = tmp_path / "b.gif"
    spans = demo_session_spans()
    render_session(spans, DEMO_SESSION_ID, a)
    render_session(spans, DEMO_SESSION_ID, b)
    assert a.read_bytes() == b.read_bytes()


def test_reduce_spans_detects_hub_and_sorts_leaves() -> None:
    """`reduce_spans` should pick the relay as hub and sort leaves alphabetically."""
    session = reduce_spans(demo_session_spans(), DEMO_SESSION_ID)
    assert session.hub == "relay"
    assert session.leaves == ("A", "B"), "leaves must come out sorted for stable color assignment"
    assert session.span_count == 10
    assert session.duration_s > 0


def test_reduce_spans_marks_failed_hops() -> None:
    """Spans tagged `state=failed` should produce hops with status='failed'."""
    session = reduce_spans(demo_session_spans(), DEMO_SESSION_ID)
    failed = [h for h in session.hops if h.status == "failed"]
    assert len(failed) == 2, "fixture has two failed hops; renderer must surface both"


def test_reduce_spans_empty() -> None:
    """Empty span list returns an empty session, no exception."""
    session = reduce_spans([], "nope")
    assert session.hub == "relay"
    assert session.leaves == ()
    assert session.hops == ()
    assert session.span_count == 0


def test_star_layout_places_hub_at_center() -> None:
    layout = star_layout("relay", ("A", "B", "C"), 600, 400)
    cx, cy = layout["relay"]
    assert (cx, cy) == (300.0, 200.0)
    # All leaves equidistant from hub.
    radii = [((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for k, (x, y) in layout.items() if k != "relay"]
    assert max(radii) - min(radii) < 1e-6


def test_star_layout_horizontal_for_two_leaves() -> None:
    """Two leaves should sit on the horizontal axis, not vertical."""
    layout = star_layout("relay", ("A", "B"), 600, 400)
    a_y, b_y = layout["A"][1], layout["B"][1]
    cy = layout["relay"][1]
    assert abs(a_y - cy) < 1e-6 and abs(b_y - cy) < 1e-6, (
        "two-leaf layout should be horizontal so the chord crosses the canvas"
    )


def test_star_layout_zero_leaves_returns_only_hub() -> None:
    layout = star_layout("relay", (), 600, 400)
    assert layout == {"relay": (300.0, 200.0)}


def test_quantize_ticks_pads_small_sessions() -> None:
    """A session with one hop should still get at least one tick so the
    GIF doesn't render as a single static frame.
    """
    session = reduce_spans(demo_session_spans()[:1], DEMO_SESSION_ID)
    ticks = _quantize_ticks(session.hops)
    assert ticks, "even a single-hop session must produce at least one tick"


def test_quantize_ticks_handles_empty() -> None:
    assert _quantize_ticks(()) == {}


def test_canvas_constants_are_sane() -> None:
    """Sanity floor: the canvas is bigger than a thumbnail and the frame
    rate is in a viewable range. Catches accidental edits to the
    geometry constants (which would invalidate every baseline).
    """
    assert WIDTH >= 480 and HEIGHT >= 320
    assert 40 <= FRAME_MS <= 200
    assert 3 <= FRAMES_PER_TICK <= 12


def test_render_session_raises_on_empty_spans(tmp_path: Path) -> None:
    """The issue calls out: fail loudly on empty input. No synthetic fallback."""
    import pytest

    with pytest.raises(ValueError, match="no spans"):
        render_session([], "nope", tmp_path / "x.gif")
