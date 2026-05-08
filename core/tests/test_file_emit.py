"""Tests for the file-drop span emit side-channel (otel-a2a-relay#103).

Covers default-dir resolution (env override + fallback), the typed-arg
build path, attributes merge precedence, atomic write, and round-trip
shape compatibility with the repo-recall ingest contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from otel_a2a_relay_core import (
    DEFAULT_SPANS_DIR,
    build_span_dict,
    default_spans_dir,
    emit_span,
)


def test_default_spans_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REPO_RECALL_SPANS_DIR", str(tmp_path / "custom"))
    assert default_spans_dir() == tmp_path / "custom"


def test_default_spans_dir_falls_back_to_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPO_RECALL_SPANS_DIR", raising=False)
    assert default_spans_dir() == DEFAULT_SPANS_DIR


def test_build_span_dict_minimal() -> None:
    span = build_span_dict(trace_id="t1", span_id="s1", name="agent.run")
    assert span["trace_id"] == "t1"
    assert span["span_id"] == "s1"
    assert span["name"] == "agent.run"
    assert span["attributes"] == {}
    assert "parent_span_id" not in span
    # Default timestamps are present and equal (caller didn't supply).
    assert span["start_time_unix_nano"] == span["end_time_unix_nano"]
    assert span["start_time_unix_nano"] > 0


def test_build_span_dict_typed_args_populate_attributes() -> None:
    span = build_span_dict(
        trace_id="t",
        span_id="s",
        name="subagent",
        parent_span_id="p",
        agent_role="attacker",
        session_id="sess",
        repo="luca",
        start_time_unix_nano=100,
        end_time_unix_nano=200,
    )
    assert span["parent_span_id"] == "p"
    assert span["start_time_unix_nano"] == 100
    assert span["end_time_unix_nano"] == 200
    assert span["attributes"] == {
        "agent.role": "attacker",
        "session.id": "sess",
        "repo": "luca",
    }


def test_build_span_dict_user_attributes_override_typed_args() -> None:
    # Caller-supplied dict wins; lets a producer override the convenience
    # typed args without us needing a special-case API for every attribute.
    span = build_span_dict(
        trace_id="t",
        span_id="s",
        name="x",
        agent_role="attacker",
        attributes={"agent.role": "inspector", "custom.key": "v"},
    )
    assert span["attributes"]["agent.role"] == "inspector"
    assert span["attributes"]["custom.key"] == "v"


def test_emit_span_writes_file_in_dir(tmp_path: Path) -> None:
    out = emit_span(
        trace_id="trace-a",
        span_id="span-1",
        name="agent.run",
        agent_role="attacker",
        session_id="sess",
        repo="luca",
        start_time_unix_nano=1700000000000000000,
        end_time_unix_nano=1700000001000000000,
        output_dir=tmp_path,
    )
    assert out == tmp_path / "trace-a_span-1.json"
    assert out.exists()
    body: dict[str, Any] = json.loads(out.read_text())
    assert body["trace_id"] == "trace-a"
    assert body["span_id"] == "span-1"
    assert body["attributes"]["session.id"] == "sess"


def test_emit_span_creates_missing_target_dir(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c"
    assert not nested.exists()
    emit_span(trace_id="t", span_id="s", name="x", output_dir=nested)
    assert nested.is_dir()
    assert (nested / "t_s.json").exists()


def test_emit_span_falls_back_to_default_dir_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Redirect both HOME and the env override so default_spans_dir() lands
    # under tmp_path. Confirms emit_span() works without a `dir` arg.
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("REPO_RECALL_SPANS_DIR", raising=False)
    # Path.home() reads $HOME on POSIX; override DEFAULT_SPANS_DIR
    # explicitly to keep the test independent of how Path.home() resolves
    # at import time.
    monkeypatch.setattr(
        "otel_a2a_relay_core.file_emit.DEFAULT_SPANS_DIR",
        fake_home / ".local" / "share" / "repo-recall" / "spans",
    )
    out = emit_span(trace_id="t", span_id="s", name="x")
    assert out.is_relative_to(fake_home)
    assert out.exists()


def test_emit_span_uses_env_override_when_dir_arg_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "envdir"
    monkeypatch.setenv("REPO_RECALL_SPANS_DIR", str(target))
    out = emit_span(trace_id="t", span_id="s", name="x")
    assert out.parent == target
    assert out.exists()


def test_emit_span_atomic_no_partial_files_left_behind(tmp_path: Path) -> None:
    emit_span(trace_id="t", span_id="s", name="x", output_dir=tmp_path)
    # Only the final file should be present, no leftover .tmp.* siblings.
    visible = sorted(p.name for p in tmp_path.iterdir())
    assert visible == ["t_s.json"]


def test_emit_span_re_emit_overwrites(tmp_path: Path) -> None:
    # Same (trace_id, span_id) should overwrite — useful for idempotent
    # producers (a hook that re-fires on retry).
    emit_span(trace_id="t", span_id="s", name="first", output_dir=tmp_path)
    emit_span(trace_id="t", span_id="s", name="second", output_dir=tmp_path)
    body = json.loads((tmp_path / "t_s.json").read_text())
    assert body["name"] == "second"


def test_emit_span_round_trips_json_keys_for_repo_recall(tmp_path: Path) -> None:
    # The whole point of the file-drop sink: produce a JSON shape
    # repo-recall's parser accepts. Mirrors what tests/smoke.rs in
    # repo-recall expects post-#65 alignment (session.id not session.uuid).
    out = emit_span(
        trace_id="trace-x",
        span_id="span-y",
        name="agent.subagent",
        parent_span_id="span-root",
        agent_role="inspector",
        session_id="session-uuid-from-claude-code",
        repo="luca",
        output_dir=tmp_path,
    )
    body = json.loads(out.read_text())
    # Required fields repo-recall's spans.rs parser keys on:
    assert set(body.keys()) >= {
        "trace_id",
        "span_id",
        "parent_span_id",
        "name",
        "start_time_unix_nano",
        "end_time_unix_nano",
        "attributes",
    }
    assert body["attributes"]["agent.role"] == "inspector"
    assert body["attributes"]["session.id"] == "session-uuid-from-claude-code"
    assert body["attributes"]["repo"] == "luca"
