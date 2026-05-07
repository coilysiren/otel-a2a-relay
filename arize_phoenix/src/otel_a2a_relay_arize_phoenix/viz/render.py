"""Pillow-only frame compositor and GIF assembler.

Why no matplotlib: Pillow ships its own copy of FreeType, so font
rasterization is byte-stable across Linux, macOS, and Windows runners
provided the same Pillow wheel. Matplotlib leans on the host's
fontconfig, which makes byte-exact baselines impractical without a
fully pinned container. For a "regenerate the GIF in CI and assert
the bytes" loop, Pillow is the right floor.

The renderer draws every frame at 2x and downsamples with LANCZOS for
free supersampling, then quantizes the multi-frame stack to a single
adaptive palette so the output is one cohesive GIF rather than a per-
frame palette flicker. PIL's GIF writer is deterministic when called
with explicit `disposal`, `loop`, and `duration`, no `info` carry-over,
and `optimize=False`. We rely on that.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from otel_a2a_relay_arize_phoenix.viz.model import Hop, Session, reduce_spans, star_layout
from otel_a2a_relay_arize_phoenix.viz.theme import DEFAULT, Theme

# Canvas geometry, in output pixels. Doubled internally for AA.
WIDTH = 720
HEIGHT = 340
SUPERSAMPLE = 2

# Region budget: title strip up top, message log on the right, footer
# strip at the bottom, star fills the remainder. Tuned by eye so the
# star sits visually centered in the area between the title and the
# scrubber.
SIDEBAR_W = 220
TOP_STRIP = 56
BOTTOM_STRIP = 64

# Animation pacing.
FRAMES_PER_TICK = 5  # how many GIF frames each logical tick spans
FRAME_MS = 130  # ~7.7fps - readable, not frantic
PALETTE_COLORS = 128  # roomy enough to keep pink/amber/red dots clearly distinct
MIN_TICKS = 4  # stretch tiny sessions so the GIF feels paced
MAX_TICKS = 14  # cap big sessions so the GIF stays under ~10s

# Visual constants. All in 1x (output) coordinates; the supersampler
# multiplies them.
NODE_R = 16
HUB_R = 22
NODE_RING_W = 3
EDGE_W = 3
PARTICLE_R = 7
LABEL_GAP = 14  # gap between node edge and label, in 1x output pixels
TRAIL_FADE_TICKS = 3  # how many ticks an edge keeps a trail after firing
LOG_LINES = 8  # cap on the append-only message log
LOG_TEXT_MAX = 22  # truncation for long message bodies


def _quantize_ticks(hops: tuple[Hop, ...]) -> dict[Hop, int]:
    """Bucket hops into discrete ticks by start time.

    Within a tick, hops are considered simultaneous - the visual story.
    Outside the bucket, they are strictly ordered by start time. We
    aim for between MIN_TICKS and MAX_TICKS distinct buckets so the
    GIF lasts roughly 3-8 seconds at FRAMES_PER_TICK frames each.
    """
    if not hops:
        return {}
    # Sort by start, but preserve input ordering as the secondary key
    # so two hops with identical timestamps come out in a stable order.
    indexed = list(enumerate(hops))
    indexed.sort(key=lambda iv: (iv[1].start, iv[0]))
    starts = [iv[1].start for iv in indexed]

    # Pick the number of ticks. With unique start times, every hop is
    # its own tick (clamped to MAX_TICKS). With clumped starts,
    # collapse to the natural cluster count.
    unique_starts = sorted(set(starts))
    if len(unique_starts) <= MAX_TICKS:
        # Honor the natural clustering - one tick per unique start time.
        tick_of_start = {s: i for i, s in enumerate(unique_starts)}
        n_ticks = max(MIN_TICKS, len(unique_starts))
        # If we padded with empty ticks, push the real ticks toward the
        # middle so the animation has lead-in and lead-out breathing room.
        offset = (n_ticks - len(unique_starts)) // 2
        return {
            hops[i]: tick_of_start[s] + offset for (i, _), s in zip(indexed, starts, strict=True)
        }

    # Many distinct starts - quantize uniformly into MAX_TICKS buckets.
    lo, hi = unique_starts[0], unique_starts[-1]
    span = max(hi - lo, 1e-9)
    out: dict[Hop, int] = {}
    for (i, _), s in zip(indexed, starts, strict=True):
        bucket = min(MAX_TICKS - 1, int((s - lo) / span * MAX_TICKS))
        out[hops[i]] = bucket
    return out


def _ease_in_out(t: float) -> float:
    """Smoothstep so particles accelerate and decelerate, not linear."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _arc_point(
    src: tuple[float, float],
    dst: tuple[float, float],
    t: float,
    bow: float = 0.0,
) -> tuple[float, float]:
    """Quadratic Bezier from src to dst with a control point offset
    perpendicular to the chord by `bow` * length. Bow=0 is a straight
    line; bow!=0 gives the gentle arc that lets crossings be visible.
    """
    sx, sy = src
    dx, dy = dst
    mx, my = (sx + dx) / 2, (sy + dy) / 2
    if bow != 0.0:
        chord_dx, chord_dy = dx - sx, dy - sy
        length = max(math.hypot(chord_dx, chord_dy), 1e-9)
        # Perpendicular unit vector (rotate chord 90deg).
        px, py = -chord_dy / length, chord_dx / length
        mx += px * bow * length
        my += py * bow * length
    # B(t) = (1-t)^2 P0 + 2(1-t)t C + t^2 P1
    one = 1.0 - t
    bx = one * one * sx + 2 * one * t * mx + t * t * dx
    by = one * one * sy + 2 * one * t * my + t * t * dy
    return bx, by


def _bow_for(src: str, dst: str, hub: str) -> float:
    """Pick a perpendicular offset that lets parallel hops separate.

    Both directions of the same chord (out vs return) need to bow
    opposite ways or they overdraw. The convention: hub-outbound bows
    one way, return bows the other. Non-hub-touching hops (rare in
    star topology, and a sign of a malformed session) get a small
    default bow so they're at least visible.
    """
    if src == hub:
        return 0.28
    if dst == hub:
        return -0.28
    return 0.14


def _color_for(
    theme: Theme,
    agent_color: dict[str, tuple[int, int, int]],
    hop: Hop,
    hub: str,
) -> tuple[int, int, int]:
    """Edge / particle color: the immediate emitter's color.

    `agent a -> relay` is agent a's color; `relay -> agent b` is the
    relay's color, regardless of who originally produced the message
    body. Status (completed / failed / in-flight) is intentionally
    not encoded in the hue here - the renderer leans on edge style
    elsewhere if a status signal is needed.
    """
    if hop.src == hub:
        hub_color: tuple[int, int, int] = theme.hub
        return hub_color
    color: tuple[int, int, int] = agent_color.get(hop.src) or theme.ink
    return color


def _alpha_blend(
    base: tuple[int, int, int],
    overlay: tuple[int, int, int],
    a: float,
) -> tuple[int, int, int]:
    """Linear-RGB-naive blend, but good enough for trail fades."""
    a = max(0.0, min(1.0, a))
    return (
        int(base[0] * (1 - a) + overlay[0] * a),
        int(base[1] * (1 - a) + overlay[1] * a),
        int(base[2] * (1 - a) + overlay[2] * a),
    )


def _draw_background(draw: ImageDraw.ImageDraw, w: int, h: int, theme: Theme) -> None:
    """Subtle grid + radial vignette toward the hub for depth."""
    # Vignette: concentric rings of slightly brighter color near center.
    cx, cy = w / 2, h / 2
    max_r = math.hypot(cx, cy)
    rings = 6
    for i in range(rings, 0, -1):
        r = max_r * (i / rings)
        a = (rings - i + 1) / rings * 0.35  # outer rings are dim
        c = _alpha_blend(theme.bg, theme.bg_glow, a)
        # Filled ellipse, drawn back-to-front.
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    # Sparse grid lines, just visible enough to read as a coordinate
    # plane without competing with the topology.
    step = 60
    for x in range(0, w, step):
        draw.line([(x, 0), (x, h)], fill=theme.grid, width=1)
    for y in range(0, h, step):
        draw.line([(0, y), (w, y)], fill=theme.grid, width=1)


def _draw_node(
    draw: ImageDraw.ImageDraw,
    pos: tuple[float, float],
    color: tuple[int, int, int],
    inner: tuple[int, int, int],
    radius: int,
    pulse: float,
    theme: Theme,
) -> None:
    """A node is a filled ring with an optional pulse halo around it.

    `pulse` in [0,1] makes the outer halo larger and brighter when the
    node is the source or target of a currently-firing hop.
    """
    x, y = pos
    halo_r = radius + int(radius * 0.7 * pulse)
    if pulse > 0:
        halo_color = _alpha_blend(theme.bg, color, 0.35 * pulse + 0.15)
        draw.ellipse([x - halo_r, y - halo_r, x + halo_r, y + halo_r], fill=halo_color)
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=color,
        outline=color,
    )
    # Inner ring so the node reads as a token rather than a flat dot.
    inner_r = radius - NODE_RING_W * 2
    draw.ellipse(
        [x - inner_r, y - inner_r, x + inner_r, y + inner_r],
        fill=inner,
    )


def _draw_label(
    draw: ImageDraw.ImageDraw,
    pos: tuple[float, float],
    text: str,
    color: tuple[int, int, int],
    font: ImageFont.FreeTypeFont,
    node_radius_ss: int,
    *,
    above: bool,
) -> None:
    """One-line label centered horizontally on `pos`, sat just outside the node.

    `pos` and `node_radius_ss` are in supersampled coordinates. The
    gap between the node edge and the label is `LABEL_GAP` 1x pixels,
    multiplied internally to match.
    """
    x, y = pos
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    gap = LABEL_GAP * SUPERSAMPLE
    dy = -node_radius_ss - gap - th if above else node_radius_ss + gap
    draw.text((x - tw / 2, y + dy), text, fill=color, font=font)


def _draw_arc(
    draw: ImageDraw.ImageDraw,
    src: tuple[float, float],
    dst: tuple[float, float],
    bow: float,
    color: tuple[int, int, int],
    width: int,
    progress: float,
    *,
    segments: int = 60,
) -> None:
    """Stroke a quadratic Bezier as a poly-line up to `progress` in [0,1].

    Pillow has no native arc-polyline primitive that varies width with
    arc length, so we step in fixed segments. 60 is enough to read as
    smooth at the canvas size we render.
    """
    if progress <= 0:
        return
    n = max(2, int(segments * progress))
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / segments  # always step in fixed deltas, even if progress < 1
        if t > progress:
            break
        pts.append(_arc_point(src, dst, t, bow))
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=width, joint="curve")


def _render_frame(
    session: Session,
    layout: dict[str, tuple[float, float]],
    agent_color: dict[str, tuple[int, int, int]],
    hop_ticks: dict[Hop, int],
    n_ticks: int,
    frame_idx: int,
    theme: Theme,
    font_node: ImageFont.FreeTypeFont,
    font_footer: ImageFont.FreeTypeFont,
    font_log: ImageFont.FreeTypeFont,
) -> Image.Image:
    """Composite one frame at 2x and return the supersampled image.

    The caller is responsible for downsampling to output resolution
    after every frame is built.
    """
    w, h = WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE
    # Scale geometry constants up to supersampled space.
    scale = SUPERSAMPLE
    img = Image.new("RGB", (w, h), theme.bg)
    draw = ImageDraw.Draw(img)

    _draw_background(draw, w, h, theme)

    # Frame -> tick is straightforward: every FRAMES_PER_TICK frames is
    # one logical tick. Within a tick, sub-progress drives the
    # particle's traversal and the trailing edges' fade.
    tick = frame_idx // FRAMES_PER_TICK
    sub = (frame_idx % FRAMES_PER_TICK) / FRAMES_PER_TICK
    eased = _ease_in_out(sub)

    # Pre-scale layout coords into supersampled space.
    pos = {k: (vx * scale, vy * scale) for k, (vx, vy) in layout.items()}

    # Draw faded trails for hops that fired in the last TRAIL_FADE_TICKS
    # ticks. Older trails are dropped entirely.
    for hop, hop_tick in hop_ticks.items():
        if hop.src == hop.dst:
            continue  # self-loops are node pulses, not edges
        if hop.src not in pos or hop.dst not in pos:
            continue
        delta = tick - hop_tick
        if delta < 0 or delta > TRAIL_FADE_TICKS:
            continue
        # Trail strength: 1.0 right after firing, fades to 0 over
        # TRAIL_FADE_TICKS. Past trails sit at 1.0 progress (full edge).
        if delta == 0:
            strength = 0.55  # while the particle is still in flight
            progress = eased
        else:
            strength = max(0.0, 1.0 - (delta - 1 + sub) / TRAIL_FADE_TICKS)
            progress = 1.0
        col = _color_for(theme, agent_color, hop, session.hub)
        col = _alpha_blend(theme.bg, col, strength)
        bow = _bow_for(hop.src, hop.dst, session.hub)
        _draw_arc(
            draw,
            pos[hop.src],
            pos[hop.dst],
            bow,
            col,
            EDGE_W * scale,
            progress,
        )

    # Particle on the currently-firing hops. Drawn after trails so it
    # stays on top.
    for hop, hop_tick in hop_ticks.items():
        if hop_tick != tick:
            continue
        if hop.src == hop.dst:
            continue
        if hop.src not in pos or hop.dst not in pos:
            continue
        col = _color_for(theme, agent_color, hop, session.hub)
        bow = _bow_for(hop.src, hop.dst, session.hub)
        px, py = _arc_point(pos[hop.src], pos[hop.dst], eased, bow)
        r = PARTICLE_R * scale
        # Outer halo for the particle, then the bright core.
        halo = _alpha_blend(theme.bg, col, 0.45)
        draw.ellipse([px - r * 1.7, py - r * 1.7, px + r * 1.7, py + r * 1.7], fill=halo)
        draw.ellipse([px - r, py - r, px + r, py + r], fill=col)

    # Hub + leaves on top of edges.
    hub_pulse = _node_pulse(session.hub, hop_ticks, tick, sub)
    _draw_node(
        draw,
        pos[session.hub],
        theme.hub,
        theme.hub_inner,
        HUB_R * scale,
        hub_pulse,
        theme,
    )
    for leaf in session.leaves:
        if leaf not in pos:
            continue
        pulse = _node_pulse(leaf, hop_ticks, tick, sub)
        c = agent_color.get(leaf) or theme.ink
        _draw_node(draw, pos[leaf], c, theme.bg, NODE_R * scale, pulse, theme)

    # Labels: hub is always below (the title fills the upper-left).
    _draw_label(
        draw,
        pos[session.hub],
        _label_for(session.hub, session.hub),
        theme.ink,
        font_node,
        HUB_R * scale,
        above=False,
    )
    for leaf in session.leaves:
        if leaf not in pos:
            continue
        # Label above when the leaf sits in the top half of the canvas.
        cy = pos[leaf][1]
        _draw_label(
            draw,
            pos[leaf],
            _label_for(leaf, session.hub),
            theme.ink,
            font_node,
            NODE_R * scale,
            above=cy < HEIGHT * scale / 2,
        )

    _draw_log(draw, w, h, hop_ticks, agent_color, session.hub, tick, theme, font_log)
    _draw_footer(draw, w, h, session, tick, n_ticks, theme, font_footer)
    return img


def _node_pulse(
    name: str,
    hop_ticks: dict[Hop, int],
    tick: int,
    sub: float,
) -> float:
    """Pulse intensity for a node at a given (tick, sub) inside the tick.

    A node pulses when it is the source or destination of a hop firing
    in the current tick. The intensity rises sharply at the start of
    the tick and decays through the tick, so it reads as a punctuation
    rather than a sustained glow.
    """
    pulse = 0.0
    for hop, hop_tick in hop_ticks.items():
        if hop_tick != tick:
            continue
        if hop.src == name or hop.dst == name:
            # Sharp attack, slow decay across the tick.
            decay = max(0.0, 1.0 - sub * 0.85)
            pulse = max(pulse, decay)
    return pulse


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    w: int,
    h: int,
    session: Session,
    tick: int,
    n_ticks: int,
    theme: Theme,
    font: ImageFont.FreeTypeFont,
) -> None:
    """Title strip up top, factual footer line, scrubber as a thin
    full-width track at the very bottom edge.

    The scrubber lives in its own row below the footer text instead of
    sharing the row, so the bar can never visually collide with the
    duration text on the right side.
    """
    pad = 20 * SUPERSAMPLE

    # Title (top-left).
    draw.text(
        (pad, pad),
        "session topology",
        fill=theme.ink,
        font=font,
    )
    draw.text(
        (pad, pad + 16 * SUPERSAMPLE),
        "real OTel spans, animated by start time",
        fill=theme.mute,
        font=font,
    )

    # Footer text: factual line at the lower edge of the canvas.
    text_h = 12 * SUPERSAMPLE
    track_h = 3 * SUPERSAMPLE
    track_y = h - track_h - 6 * SUPERSAMPLE
    text_y = track_y - text_h - 8 * SUPERSAMPLE
    line = (
        f"session={session.session_id}  spans={session.span_count}  "
        f"duration={session.duration_s:.2f}s"
    )
    draw.text((pad, text_y), line, fill=theme.mute, font=font)

    # Scrubber: thin full-width track at the bottom edge, no overlap
    # with the footer text above.
    track_x_lo = pad
    track_x_hi = w - pad
    track_w = track_x_hi - track_x_lo
    draw.rounded_rectangle(
        [track_x_lo, track_y, track_x_hi, track_y + track_h],
        radius=track_h // 2,
        fill=theme.hair,
    )
    progress = (tick + 1) / max(1, n_ticks)
    fill_w = int(track_w * progress)
    if fill_w > 0:
        draw.rounded_rectangle(
            [track_x_lo, track_y, track_x_lo + fill_w, track_y + track_h],
            radius=track_h // 2,
            fill=theme.hub,
        )


def _draw_log(
    draw: ImageDraw.ImageDraw,
    w: int,
    h: int,
    hop_ticks: dict[Hop, int],
    agent_color: dict[str, tuple[int, int, int]],
    hub: str,
    tick: int,
    theme: Theme,
    font: ImageFont.FreeTypeFont,
) -> None:
    """Right-side message log, append-only.

    Each hop with a text body becomes one log line in the order it
    fires (oldest at top, newest at the bottom). Lines never disappear
    or fade, so the log reads as a rolling transcript - the eye can
    re-trace the conversation any time during playback. Self-loops
    are skipped (they duplicate the onward hop's text); otherwise
    no de-dup, since two real sends of the same message body are
    two real events.
    """
    pad = 14 * SUPERSAMPLE
    sidebar_x = (WIDTH - SIDEBAR_W) * SUPERSAMPLE + pad
    title_y = TOP_STRIP * SUPERSAMPLE
    line_h = 20 * SUPERSAMPLE
    dot_r = 4 * SUPERSAMPLE
    dot_gap = 12 * SUPERSAMPLE

    draw.text((sidebar_x, title_y - 18 * SUPERSAMPLE), "messages", fill=theme.ink, font=font)
    # Hairline divider under the title to anchor the log visually.
    draw.line(
        [
            (sidebar_x, title_y - 4 * SUPERSAMPLE),
            (w - pad, title_y - 4 * SUPERSAMPLE),
        ],
        fill=theme.hair,
        width=1,
    )

    # Append-only ordered list of every fired hop with text, capped at
    # LOG_LINES so a chatty session doesn't run off the canvas.
    visible: list[tuple[Hop, int]] = []
    for hop, t in sorted(hop_ticks.items(), key=lambda iv: iv[1]):
        if t > tick or not hop.text or hop.src == hop.dst:
            continue
        visible.append((hop, t))
        if len(visible) >= LOG_LINES:
            break

    for i, (hop, _t) in enumerate(visible):
        y = title_y + i * line_h
        # Color = immediate emitter, matching the on-canvas edge/particle.
        # `agent a -> relay` is agent-a colored; `relay -> agent b` is
        # relay-colored. Status is not encoded in hue.
        emitter_color = theme.hub if hop.src == hub else (agent_color.get(hop.src) or theme.ink)
        text_color = emitter_color
        dot_color = emitter_color
        cx = sidebar_x + dot_r
        cy = y + 6 * SUPERSAMPLE
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=dot_color)
        text = hop.text
        if len(text) > LOG_TEXT_MAX:
            text = text[: LOG_TEXT_MAX - 1] + "..."
        prefix = f"{_label_for(hop.src, hub)} -> {_label_for(hop.dst, hub)}: "
        draw.text((cx + dot_gap, y), prefix + text, fill=text_color, font=font)


def _label_for(name: str, hub: str) -> str:
    """Render-time name transform: the hub keeps its own id (relay /
    o2r), every leaf gets the `agent <name>` prefix so the labels
    read as English instead of single-letter abbreviations.
    """
    if name == hub:
        return name
    return f"agent {name.lower()}"


def _assign_agent_colors(leaves: tuple[str, ...], theme: Theme) -> dict[str, tuple[int, int, int]]:
    """Each leaf gets a stable color from the palette by sorted index.

    Sorted order is the caller's responsibility but is what `Session.leaves`
    guarantees, so the assignment is reproducible across runs.
    """
    return {leaf: theme.agents[i % len(theme.agents)] for i, leaf in enumerate(leaves)}


def _build_frames(
    session: Session,
    theme: Theme,
) -> list[Image.Image]:
    """Render every frame for the session, downsampled to output size.

    Star area is the canvas minus the title strip (top), the message log
    (right), and the footer strip (bottom). The hub centers in that
    area, not in the full canvas - that's what fixes the off-center
    look when the log + title + footer are added.
    """
    star_w = WIDTH - SIDEBAR_W
    star_h = HEIGHT - TOP_STRIP - BOTTOM_STRIP
    raw_layout = star_layout(session.hub, session.leaves, star_w, star_h)
    layout = {k: (x, y + TOP_STRIP) for k, (x, y) in raw_layout.items()}
    agent_color = _assign_agent_colors(session.leaves, theme)
    hop_ticks = _quantize_ticks(session.hops)
    n_ticks = max(MIN_TICKS, max(hop_ticks.values(), default=0) + 1) if hop_ticks else MIN_TICKS

    font_node = ImageFont.truetype(str(theme.font_path), 18 * SUPERSAMPLE)
    font_footer = ImageFont.truetype(str(theme.font_path), 12 * SUPERSAMPLE)
    font_log = ImageFont.truetype(str(theme.font_path), 11 * SUPERSAMPLE)

    total_frames = n_ticks * FRAMES_PER_TICK
    frames: list[Image.Image] = []
    for i in range(total_frames):
        big = _render_frame(
            session,
            layout,
            agent_color,
            hop_ticks,
            n_ticks,
            i,
            theme,
            font_node,
            font_footer,
            font_log,
        )
        frames.append(big.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS))
    return frames


def _save_gif(frames: list[Image.Image], out_path: Path) -> None:
    """Quantize the frame stack to one shared adaptive palette and write
    a single GIF. Explicit `disposal`, `loop`, and `duration`; no
    optimization, so the output is byte-deterministic.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not frames:
        # Empty session: write a single blank frame so the file exists
        # and CI does not have to special-case absence.
        blank = Image.new("RGB", (WIDTH, HEIGHT), DEFAULT.bg)
        blank.save(out_path, format="GIF")
        return
    # Build a master palette from a composite of every frame so the
    # palette is representative; quantize all frames against it.
    composite = frames[0].copy()
    for f in frames[1:]:
        composite = Image.blend(composite, f, 0.5)
    pal_image = composite.convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=PALETTE_COLORS, dither=Image.Dither.NONE
    )
    quantized = [f.quantize(palette=pal_image, dither=Image.Dither.NONE) for f in frames]
    # `optimize=True` lets Pillow store per-frame diff rectangles when
    # consecutive frames overlap, which cuts the file by ~3-4x without
    # affecting determinism (Pillow's optimizer is a pure function of
    # the frame stack, no timestamp embedding).
    quantized[0].save(
        out_path,
        format="GIF",
        save_all=True,
        append_images=quantized[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=2,
        optimize=True,
    )


def render_session(
    spans: list[dict[str, Any]],
    session_id: str,
    out_path: Path,
    theme: Theme | None = None,
) -> Session:
    """Reduce, lay out, render, and write the GIF.

    Returns the reduced session so callers can print a summary line.
    Raises if `spans` is empty - the issue is explicit that we must
    fail loudly rather than render synthetic content.
    """
    if not spans:
        raise ValueError(f"no spans for session.id={session_id}")
    theme = theme or DEFAULT
    session = reduce_spans(spans, session_id)
    if not session.hops and not session.leaves:
        raise ValueError(f"session.id={session_id} has spans but no usable hops")
    frames = _build_frames(session, theme)
    _save_gif(frames, out_path)
    return session
