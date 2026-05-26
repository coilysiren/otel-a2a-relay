#!/usr/bin/env python3
"""Render the simplest-case relay topology diagram for the README.

Output: assets/topology.png

Run:
    uv run --with matplotlib python scripts/render_topology.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "assets" / "topology.png"

BG = "#fbfaf6"
INK = "#1c1c1c"
MUTE = "#6b6b6b"
HAIR = "#d8d4ca"

CLIENT_FILL = "#e7f1f7"
CLIENT_EDGE = "#3f7fa3"
RELAY_FILL = "#fbe8cf"
RELAY_EDGE = "#d27a1e"
PEER_FILL = "#dff0ec"
PEER_EDGE = "#2a8270"

TRACE_LINE = "#b48a3d"


def rounded_box(ax, x, y, w, h, fill, edge, lw=1.6, radius=0.18):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.02,rounding_size={radius}",
        linewidth=lw,
        facecolor=fill,
        edgecolor=edge,
        zorder=2,
    )
    ax.add_patch(box)


def header(ax, x, y, label, port, edge):
    ax.text(
        x,
        y,
        label,
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
        color=INK,
        zorder=3,
    )
    if port:
        ax.text(
            x,
            y - 0.42,
            port,
            ha="center",
            va="center",
            fontsize=10.5,
            color=edge,
            family="monospace",
            zorder=3,
        )


def span_lines(ax, x, y, lines):
    for i, (name, kind) in enumerate(lines):
        ax.text(
            x,
            y - i * 0.42,
            name,
            ha="center",
            va="center",
            fontsize=10,
            color=INK,
            family="monospace",
            zorder=3,
        )
        ax.text(
            x,
            y - i * 0.42 - 0.22,
            kind,
            ha="center",
            va="center",
            fontsize=8.5,
            color=MUTE,
            style="italic",
            zorder=3,
        )


def arrow(ax, x0, x1, y, label_top, label_bottom):
    a = FancyArrowPatch(
        (x0, y),
        (x1, y),
        arrowstyle="-|>,head_length=10,head_width=6",
        mutation_scale=1.0,
        linewidth=2.2,
        color=INK,
        zorder=2,
        shrinkA=0,
        shrinkB=0,
    )
    ax.add_patch(a)
    midx = (x0 + x1) / 2
    ax.text(
        midx,
        y + 0.32,
        label_top,
        ha="center",
        va="bottom",
        fontsize=10.5,
        color=INK,
        family="monospace",
        fontweight="bold",
    )
    ax.text(
        midx,
        y - 0.34,
        label_bottom,
        ha="center",
        va="top",
        fontsize=9,
        color=MUTE,
        style="italic",
    )


def main():
    fig, ax = plt.subplots(figsize=(13, 6.5), dpi=170)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 6.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # title
    ax.text(
        6.5,
        6.1,
        "Relay topology",
        ha="center",
        va="center",
        fontsize=18,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        6.5,
        5.65,
        "simplest case: one client, one relay, one peer, one trace",
        ha="center",
        va="center",
        fontsize=11.5,
        color=MUTE,
        style="italic",
    )

    # nodes
    cx_client, cx_relay, cx_peer = 2.0, 6.5, 11.0
    box_w, box_h = 2.4, 2.6
    box_y = 1.8
    box_top = box_y + box_h

    # client
    rounded_box(ax, cx_client - box_w / 2, box_y, box_w, box_h, CLIENT_FILL, CLIENT_EDGE)
    header(ax, cx_client, box_top - 0.45, "make send", "client.py", CLIENT_EDGE)
    span_lines(
        ax,
        cx_client,
        box_top - 1.55,
        [
            ("a2a.client.send", "CLIENT"),
        ],
    )

    # relay (slightly taller emphasis via thicker edge)
    rounded_box(
        ax,
        cx_relay - box_w / 2,
        box_y,
        box_w,
        box_h,
        RELAY_FILL,
        RELAY_EDGE,
        lw=2.2,
    )
    header(ax, cx_relay, box_top - 0.45, "relay", ":8080", RELAY_EDGE)
    span_lines(
        ax,
        cx_relay,
        box_top - 1.55,
        [
            ("a2a.task", "SERVER"),
            ("a2a.relay.forward", "CLIENT"),
        ],
    )

    # peer
    rounded_box(ax, cx_peer - box_w / 2, box_y, box_w, box_h, PEER_FILL, PEER_EDGE)
    header(ax, cx_peer, box_top - 0.45, "agent B", ":9002", PEER_EDGE)
    span_lines(
        ax,
        cx_peer,
        box_top - 1.55,
        [
            ("a2a.task", "SERVER, kind=AGENT"),
        ],
    )

    # arrows between boxes
    arrow_y = box_y + box_h / 2
    arrow(
        ax,
        cx_client + box_w / 2 + 0.1,
        cx_relay - box_w / 2 - 0.1,
        arrow_y,
        "message/send",
        "+ traceparent",
    )
    arrow(
        ax,
        cx_relay + box_w / 2 + 0.1,
        cx_peer - box_w / 2 - 0.1,
        arrow_y,
        "message/send",
        "+ traceparent",
    )

    # one-trace footer
    line_y = 1.2
    ax.plot(
        [cx_client - box_w / 2, cx_peer + box_w / 2],
        [line_y, line_y],
        color=TRACE_LINE,
        linewidth=1.6,
        linestyle=(0, (4, 3)),
        zorder=1,
    )
    ax.text(
        6.5,
        line_y - 0.32,
        "one W3C trace_id end-to-end",
        ha="center",
        va="top",
        fontsize=10.5,
        color=TRACE_LINE,
        fontweight="bold",
    )

    # peer registry hint
    ax.text(
        6.5,
        0.35,
        "peers from OTEL_A2A_RELAY_PEERS=A=http://...,B=http://...",
        ha="center",
        va="center",
        fontsize=9,
        color=MUTE,
        family="monospace",
    )

    # subtle frame
    frame = FancyBboxPatch(
        (0.25, 0.05),
        12.5,
        6.4,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=1.0,
        facecolor="none",
        edgecolor=HAIR,
        zorder=0,
    )
    ax.add_patch(frame)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor=BG)
    print(f"wrote {OUT.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
