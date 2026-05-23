"""Pydantic models for channel and event creation requests."""

import typing

import pydantic


class ChannelCreate(pydantic.BaseModel):
    """Request body for POST /agent-channel."""

    title: str = pydantic.Field(default="", max_length=200)
    created_by: str = pydantic.Field(default="", max_length=128)


class EventCreate(pydantic.BaseModel):
    """Request body for POST /agent-channel/{id}/event."""

    kind: str = pydantic.Field(min_length=1, max_length=64)
    author: str = pydantic.Field(default="", max_length=128)
    payload: dict[str, typing.Any]
