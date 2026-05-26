"""Pure tests for content negotiation + markdown rendering."""

from __future__ import annotations

import typing

from otel_a2a_relay_channels import channel_markdown, pick_format


def test_pick_format_explicit_overrides_accept() -> None:
    assert pick_format("yaml", "text/markdown") == "yaml"
    assert pick_format("md", "") == "markdown"
    assert pick_format("json", "application/yaml") == "json"
    assert pick_format("nonsense", "") == "json"


def test_pick_format_from_accept_header() -> None:
    assert pick_format(None, "application/yaml") == "yaml"
    assert pick_format(None, "text/markdown") == "markdown"
    assert pick_format(None, "application/json") == "json"
    assert pick_format(None, "") == "json"


def test_channel_markdown_render() -> None:
    data: dict[str, typing.Any] = {
        "channel": {
            "id": "VHGC",
            "title": "demo",
            "created_by": "claude-test",
            "created_at": "2026-05-22T00:00:00+00:00",
            "closed_at": None,
            "url": "http://api/agent-channel/VHGC",
        },
        "onboarding": "welcome",
        "participate": {"read_state": "GET /agent-channel/VHGC/state"},
        "spec": {"mission": "test"},
        "state": {"handoff": {"holder": "claude-x"}},
        "recent_events": [
            {
                "id": 1,
                "kind": "state",
                "author": "claude-x",
                "created_at": "2026-05-22T00:00:01+00:00",
                "payload": {"phase": "started"},
            }
        ],
    }
    md = channel_markdown(data)
    assert "# Agent Channel VHGC" in md
    assert "demo" in md
    assert "claude-test" in md
    assert "## Charter" in md
    assert "## Current state" in md
    assert "## Recent events" in md
    assert "claude-x" in md


def test_channel_markdown_handles_missing_optionals() -> None:
    data: dict[str, typing.Any] = {
        "channel": {
            "id": "ABCD",
            "title": "",
            "created_by": "",
            "created_at": "2026-05-22T00:00:00+00:00",
            "closed_at": "2026-05-22T01:00:00+00:00",
            "url": "http://api/agent-channel/ABCD",
        },
        "participate": {},
        "spec": None,
        "state": None,
        "recent_events": [],
    }
    md = channel_markdown(data)
    assert "_(untitled channel)_" in md
    assert "(unknown)" in md
    assert "closed at 2026-05-22T01:00:00+00:00" in md
    assert "_No spec event yet._" in md
    assert "_No state event yet._" in md
    assert "_No events yet._" in md


def test_channel_markdown_top_level_scalar_spec() -> None:
    # Scalar spec/state exercises _md_lines's top-level non-collection branch.
    data: dict[str, typing.Any] = {
        "channel": {
            "id": "ABCD",
            "title": "x",
            "created_by": "y",
            "created_at": "t",
            "closed_at": None,
            "url": "u",
        },
        "participate": {},
        "spec": "raw scalar charter",
        "state": None,
        "recent_events": [],
    }
    md = channel_markdown(data)
    assert "raw scalar charter" in md


def test_channel_markdown_nested_payload() -> None:
    data: dict[str, typing.Any] = {
        "channel": {
            "id": "ABCD",
            "title": "x",
            "created_by": "y",
            "created_at": "t",
            "closed_at": None,
            "url": "u",
        },
        "participate": {"nested": {"a": [1, 2, {"deep": True}]}},
        "spec": [None, False, True],
        "state": None,
        "recent_events": [
            {
                "id": 9,
                "kind": "comms",
                "author": "",
                "created_at": "t",
                "payload": {"nested": [{"a": 1}]},
            }
        ],
    }
    md = channel_markdown(data)
    assert "(no author)" in md
    assert "**deep**: true" in md
    assert "_(none)_" in md
