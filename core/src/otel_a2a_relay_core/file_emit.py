"""File-drop OTel span emit, side-channel from the OTLP exporter.

Why this lives alongside the OTLP path and not inside it:

The relay's primary emit target is an OTLP-compatible collector (Phoenix,
Tempo, Otel Collector). For the LUCA substrate (luca#27) we also want
spans landing in repo-recall's wipe-on-restart index, which ingests by
watching a directory for JSON files. Two emit paths, one canonical
span shape.

This module is purely additive: it does not touch `tracing.bootstrap()`,
the OTLP exporter, or any of the existing span-construction in
`server.py`. It produces a span dict that conforms to the repo-recall
ingest schema (flat, OTel-raw nano timestamps, attributes object) and
writes it atomically to the watched directory.

Callers supply trace_id and span_id rather than having the lib mint
them. That keeps parent/child threading the caller's responsibility,
matching how OTel itself works. The Claude Code subagent hook
(coilyco-ai#223), for instance, derives trace_id from the Claude Code
session UUID and span_id from a per-invocation uuid4.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_SPANS_DIR",
    "build_span_dict",
    "default_spans_dir",
    "emit_span",
]

# Default location matches repo-recall's resolver. The substrate does not
# require Phoenix or any other backend to be running; this directory is the
# whole interface.
DEFAULT_SPANS_DIR = Path.home() / ".local" / "share" / "repo-recall" / "spans"


def default_spans_dir() -> Path:
    """Resolve the spans ingest directory.

    Honors `REPO_RECALL_SPANS_DIR` first; otherwise returns the canonical
    default under `~/.local/share/repo-recall/spans/`. The directory may
    not exist yet — `emit_span` creates it on demand.
    """
    override = os.environ.get("REPO_RECALL_SPANS_DIR")
    if override:
        return Path(override)
    return DEFAULT_SPANS_DIR


def build_span_dict(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    parent_span_id: str | None = None,
    agent_role: str | None = None,
    session_id: str | None = None,
    repo: str | None = None,
    start_time_unix_nano: int | None = None,
    end_time_unix_nano: int | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical span dict the file-emit sink writes to disk.

    The shape matches repo-recall's parser (`coilysiren/repo-recall:src/spans.rs`):
    flat keys at the top level, attributes as a nested object. Protocol-
    canonical attribute names (`agent.role`, `session.id`, `repo`) live
    inside `attributes` per docs/protocol.md.

    Caller-supplied `attributes` are merged on top of the typed-arg
    convenience attributes, so a caller who wants to override
    `agent.role` via the dict path can.
    """
    if start_time_unix_nano is None:
        start_time_unix_nano = time.time_ns()
    if end_time_unix_nano is None:
        end_time_unix_nano = start_time_unix_nano

    attrs: dict[str, Any] = {}
    if agent_role is not None:
        attrs["agent.role"] = agent_role
    if session_id is not None:
        attrs["session.id"] = session_id
    if repo is not None:
        attrs["repo"] = repo
    if attributes:
        attrs.update(attributes)

    span: dict[str, Any] = {
        "trace_id": trace_id,
        "span_id": span_id,
        "name": name,
        "start_time_unix_nano": start_time_unix_nano,
        "end_time_unix_nano": end_time_unix_nano,
        "attributes": attrs,
    }
    if parent_span_id is not None:
        span["parent_span_id"] = parent_span_id
    return span


def emit_span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    parent_span_id: str | None = None,
    agent_role: str | None = None,
    session_id: str | None = None,
    repo: str | None = None,
    start_time_unix_nano: int | None = None,
    end_time_unix_nano: int | None = None,
    attributes: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Build a span dict and write it atomically to the spans ingest dir.

    Returns the path written. Creates the target directory if missing.

    Atomicity: writes to `<final>.tmp.<random>` then renames into place,
    so repo-recall's scanner cannot observe a half-written file. The
    rename is atomic on POSIX when source and target are on the same
    filesystem, which holds here because both paths sit under the
    user's home dir / explicit override.
    """
    span = build_span_dict(
        trace_id=trace_id,
        span_id=span_id,
        name=name,
        parent_span_id=parent_span_id,
        agent_role=agent_role,
        session_id=session_id,
        repo=repo,
        start_time_unix_nano=start_time_unix_nano,
        end_time_unix_nano=end_time_unix_nano,
        attributes=attributes,
    )

    target_dir = output_dir if output_dir is not None else default_spans_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    final = target_dir / f"{trace_id}_{span_id}.json"
    tmp = target_dir / f".{final.name}.tmp.{uuid.uuid4().hex}"
    tmp.write_text(json.dumps(span))
    tmp.replace(final)
    return final
