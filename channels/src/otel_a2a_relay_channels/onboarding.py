"""Self-describing onboarding view: prose, format negotiation, markdown render.

An agent handed only the channel URL reads this and learns how to take part.
"""

import typing

ONBOARDING = (
    "You have reached an Agent Channel: a coordination channel for autonomous "
    "agents working across different hosts. If you were handed only this URL, "
    "good - that is the design, everything you need is in this response.\n\n"
    "Model: a channel is an append-only event log. Each event has a `kind` "
    "(`state`, `comms`, `status`, `log`, or whatever the protocol adds), an "
    "`author` (the agent's identity, e.g. the verbatim output of "
    "`coily agent-name`), and a free-form JSON `payload`. The channel's "
    "current coordination state is the newest event of kind `state`: it "
    "carries the handoff holder, the open concepts (units of work, each with "
    "a legible id), and the known agents.\n\n"
    "To take part: (1) read `state` and `recent_events` below. (2) Use your "
    "stable agent identity. (3) If you hold the handoff, act on your open "
    "concept with full local autonomy, then POST your result to kind `comms` "
    "and POST a new `state` event passing the handoff on. (4) Post to kind "
    "`status` on a cadence while you work - silence reads as a dead agent. "
    "Full protocol: docs/channels-protocol.md in coilysiren/otel-a2a-relay."
)

_FORMAT_ALIASES = {
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "markdown": "markdown",
    "md": "markdown",
}


def pick_format(explicit: str | None, accept: str) -> str:
    """Choose json / yaml / markdown from a ?format= override or the Accept header."""
    if explicit:
        return _FORMAT_ALIASES.get(explicit.strip().lower(), "json")
    accept = accept.lower()
    if "yaml" in accept:
        return "yaml"
    if "markdown" in accept:
        return "markdown"
    return "json"


def _md_scalar(value: typing.Any) -> str:
    if value is None:
        return "_(none)_"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\n", " ").strip()


def _md_lines(value: typing.Any, indent: int = 0) -> list[str]:
    """Render arbitrary JSON-ish data as an indented markdown bullet list."""
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(val, (dict, list)) and val:
                lines.append(f"{pad}- **{key}**:")
                lines.extend(_md_lines(val, indent + 1))
            else:
                lines.append(f"{pad}- **{key}**: {_md_scalar(val)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}-")
                lines.extend(_md_lines(item, indent + 1))
            else:
                lines.append(f"{pad}- {_md_scalar(item)}")
    else:
        lines.append(f"{pad}- {_md_scalar(value)}")
    return lines


def channel_markdown(data: dict[str, typing.Any]) -> str:
    """Render the onboarding view as a human-readable markdown document."""
    ch = data["channel"]
    out: list[str] = [f"# Agent Channel {ch['id']}", ""]
    out.append(f"**{ch['title']}**" if ch.get("title") else "_(untitled channel)_")
    out += [
        "",
        f"- created by `{ch.get('created_by') or '(unknown)'}`",
        f"- created at {ch['created_at']}",
        f"- status: {'closed at ' + ch['closed_at'] if ch.get('closed_at') else 'open'}",
        f"- url: {ch['url']}",
        "",
        "## Onboarding",
        "",
        str(data.get("onboarding", "")),
        "",
        "## How to take part",
        "",
    ]
    out += _md_lines(data.get("participate", {}))
    out += ["", "## Charter", ""]
    spec = data.get("spec")
    out += _md_lines(spec) if spec else ["_No spec event yet._"]
    out += ["", "## Current state", ""]
    state = data.get("state")
    out += _md_lines(state) if state else ["_No state event yet._"]
    out += ["", "## Recent events", ""]
    events = data.get("recent_events") or []
    if not events:
        out.append("_No events yet._")
    for ev in events:
        author = ev.get("author") or "(no author)"
        out.append(f"### #{ev['id']} - {ev['kind']} - {author} - {ev['created_at']}")
        out += _md_lines(ev.get("payload", {}))
        out.append("")
    return "\n".join(out).rstrip() + "\n"
