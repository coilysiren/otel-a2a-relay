"""Reusable Agent Channel coordination layer.

The protocol is in docs/channels-protocol.md. This package ships the
implementation: FastAPI router + Postgres schema + Pydantic models. Mount it
into any FastAPI app by injecting a connection-pool provider and an auth
dependency.
"""

from .ids import ID_ALPHABET, ID_LEN, new_id, norm_id
from .models import ChannelCreate, EventCreate
from .onboarding import ONBOARDING, channel_markdown, pick_format
from .router import (
    MODE_NAME,
    SCHEMA,
    SENTINEL_NOTE,
    SENTINEL_SHAPE,
    make_router,
)

__all__ = [
    "ID_ALPHABET",
    "ID_LEN",
    "MODE_NAME",
    "ONBOARDING",
    "SCHEMA",
    "SENTINEL_NOTE",
    "SENTINEL_SHAPE",
    "ChannelCreate",
    "EventCreate",
    "channel_markdown",
    "make_router",
    "new_id",
    "norm_id",
    "pick_format",
]
