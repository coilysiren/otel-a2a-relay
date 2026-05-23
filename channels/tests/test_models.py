"""Pure tests for the channel + event Pydantic models."""

from __future__ import annotations

import pydantic
import pytest
from otel_a2a_relay_channels import ChannelCreate, EventCreate


def test_event_requires_kind() -> None:
    with pytest.raises(pydantic.ValidationError):
        EventCreate(kind="", author="a", payload={})
    ok = EventCreate(kind="state", author="claude-x", payload={"a": 1})
    assert ok.kind == "state"
    assert ok.payload == {"a": 1}


def test_channel_create_defaults_are_empty() -> None:
    body = ChannelCreate()
    assert body.title == ""
    assert body.created_by == ""


def test_channel_create_respects_max_length() -> None:
    with pytest.raises(pydantic.ValidationError):
        ChannelCreate(title="a" * 201)
    with pytest.raises(pydantic.ValidationError):
        ChannelCreate(created_by="a" * 129)


def test_event_kind_max_length() -> None:
    with pytest.raises(pydantic.ValidationError):
        EventCreate(kind="a" * 65, author="a", payload={})
