"""Color and typography for the topology GIF.

Centralized so the visual diff test, the renderer, and the README can
all reason about a single source of truth. Colors are tuned to read on
both light and dark GitHub themes: deep indigo background, hot pink
hub, a small rotation of accent colors for agents.

Inspired by the charm.land terminal aesthetic and the muted purple
sparkle accents on coilysiren.me. Engineering audience, so the
typography is monospace throughout - JetBrains Mono ships embedded
in the package so rendering is freetype-deterministic and does not
depend on whatever fonts the host happens to have installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

# RGB tuples. PIL wants tuples not hex strings, but we keep the source
# values as hex constants for readability.

BG = (0x0E, 0x10, 0x1A)  # deep indigo
BG_GLOW = (0x18, 0x16, 0x2C)  # hub vignette inner
GRID = (0x20, 0x22, 0x32)  # faint background grid
INK = (0xEA, 0xEC, 0xF2)  # primary text
MUTE = (0x6A, 0x6F, 0x82)  # secondary text
HAIR = (0x2A, 0x2D, 0x40)  # frame outlines

HUB = (0xFF, 0x5F, 0xBE)  # charm-pink for the relay
HUB_INNER = (0xFF, 0xC8, 0xE6)  # softer pink for the inner ring

# Agent palette. Assigned by sorted-name index so two runs over the
# same session id put the same color on the same agent. The first two
# slots are picked to be maximally distinct hues from each other AND
# from the hub's hot pink: cyan (cool blue-green), amber (warm orange).
# The two-leaf dogfood demo lands on cyan + amber against pink, which
# is the trio of colors that read as three different objects at a
# glance even on a low-color GIF palette.
AGENTS = (
    (0x5F, 0xD7, 0xFF),  # cyan
    (0xFF, 0xB0, 0x5F),  # amber
    (0x9D, 0xFF, 0x9C),  # mint
    (0xC8, 0xA0, 0xFF),  # violet
    (0xFF, 0xCC, 0x66),  # gold
)

# Edge state palette. Direction (outbound vs return) is encoded by
# whether the source is the hub. Status (completed / failed / in-flight)
# is encoded by the trail style and head color.
COMPLETED = INK
FAILED = (0xFF, 0x5F, 0x5F)
IN_FLIGHT = (0xFF, 0xE0, 0x6B)


@dataclass(frozen=True)
class Theme:
    """A frozen bundle of every color and font path the renderer needs."""

    bg: tuple[int, int, int] = BG
    bg_glow: tuple[int, int, int] = BG_GLOW
    grid: tuple[int, int, int] = GRID
    ink: tuple[int, int, int] = INK
    mute: tuple[int, int, int] = MUTE
    hair: tuple[int, int, int] = HAIR
    hub: tuple[int, int, int] = HUB
    hub_inner: tuple[int, int, int] = HUB_INNER
    agents: tuple[tuple[int, int, int], ...] = AGENTS
    completed: tuple[int, int, int] = COMPLETED
    failed: tuple[int, int, int] = FAILED
    in_flight: tuple[int, int, int] = IN_FLIGHT

    @property
    def font_path(self) -> Path:
        """Absolute path to the bundled JetBrains Mono Regular TTF."""
        # importlib.resources guarantees this resolves whether the package
        # is installed or running from a source checkout.
        return Path(str(files("otel_a2a_relay.viz.assets").joinpath("JetBrainsMono-Regular.ttf")))

    def agent_color(self, name: str) -> tuple[int, int, int]:
        """Pick a stable agent color from the palette by name."""
        # `sum(name)` is deterministic and stable under the same input.
        # We sort agents by name once before color assignment, so this
        # is only used as a fallback for non-listed agents.
        idx = sum(ord(c) for c in name) % len(self.agents)
        return self.agents[idx]


DEFAULT = Theme()
