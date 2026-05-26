"""Tests for the dogfood CLI client.

The client is a thin wrapper over httpx + the OTel SDK. Tests stub both at the
boundary: a fake httpx.post / httpx.get / httpx.stream captures the outgoing
envelope and returns canned responses, and `make_provider` is replaced with a
no-op TracerProvider so tests never try to ship OTLP.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from otel_a2a_relay_arize_phoenix import client as client_mod
from otel_a2a_relay_arize_phoenix.client import (
    _attrs,
    _env,
    _fetch_spans,
    _flatten,
    cmd_cancel,
    cmd_get,
    cmd_gif,
    cmd_peers,
    cmd_send,
    cmd_stream,
    cmd_tasks,
    cmd_view,
    main,
)


@pytest.fixture(autouse=True)
def _no_op_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace make_provider so the OTel SDK never opens a socket."""
    monkeypatch.setattr(client_mod, "make_provider", lambda: TracerProvider())


class FakeResponse:
    def __init__(
        self, payload: Any = None, *, status_code: int = 200, raise_for_status_err: bool = False
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self._raise = raise_for_status_err

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self._raise:
            raise httpx.HTTPError("boom")


class FakeStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines


def test_flatten_dotted_keys() -> None:
    nested = {"session": {"id": "abc"}, "agent": {"id": "A", "name": "alpha"}}
    flat = _flatten(nested)
    assert flat["session.id"] == "abc"
    assert flat["agent.id"] == "A"
    assert flat["agent.name"] == "alpha"


def test_flatten_handles_scalar() -> None:
    assert _flatten("not-a-dict") == {}


def test_attrs_parses_json_string_attribute_blob() -> None:
    span = {"attributes": '{"session": {"id": "ctx"}}'}
    assert _attrs(span)["session.id"] == "ctx"


def test_attrs_handles_already_dict() -> None:
    span = {"attributes": {"agent": {"id": "A"}}}
    assert _attrs(span)["agent.id"] == "A"


def test_attrs_returns_empty_when_unparseable() -> None:
    span = {"attributes": "not-json"}
    assert _attrs(span) == {}


def test_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO", "bar")
    assert _env("FOO") == "bar"


def test_env_optional_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOO", raising=False)
    assert _env("FOO", required=False, default="fallback") == "fallback"


def test_env_required_missing_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOO", raising=False)
    with pytest.raises(SystemExit) as exc:
        _env("FOO")
    assert exc.value.code == 2


# --------------------------------------------------------------------------- send


def _send_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    defaults = {"AS": "A", "CTX": "ctx", "MSG": "hello", "TO": "B"}
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OTEL_A2A_RELAY_URL", raising=False)


def test_cmd_send_happy_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse({"result": {"status": {"state": "completed"}}})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert cmd_send() == 0
    out = capsys.readouterr().out
    assert "task=" in out
    assert "state=completed" in out
    assert captured["json"]["method"] == "message/send"
    assert captured["json"]["params"]["message"]["metadata"]["agent.target"] == "B"


def test_cmd_send_without_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch, TO="")
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: FakeResponse({"result": {"status": {"state": "ok"}}})
    )
    assert cmd_send() == 0
    out = capsys.readouterr().out
    assert "->" not in out


def test_cmd_send_relay_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch)

    def bad_post(*_a: Any, **_k: Any) -> FakeResponse:
        raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "post", bad_post)
    assert cmd_send() == 1
    assert "relay unreachable" in capsys.readouterr().err


def test_cmd_send_relay_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch)
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: FakeResponse({"error": {"code": -1, "message": "x"}})
    )
    assert cmd_send() == 1
    assert "error:" in capsys.readouterr().err


# --------------------------------------------------------------------------- stream


def test_cmd_stream_happy_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch)

    def _sse(obj: dict[str, Any]) -> str:
        return f"data: {json.dumps(obj)}"

    chunks = [
        _sse(
            {
                "result": {
                    "kind": "artifact-update",
                    "artifact": {"parts": [{"text": "hi "}]},
                    "lastChunk": False,
                }
            }
        ),
        _sse(
            {
                "result": {
                    "kind": "artifact-update",
                    "artifact": {"parts": [{"text": "there"}]},
                    "lastChunk": True,
                }
            }
        ),
        _sse(
            {
                "result": {
                    "kind": "status-update",
                    "status": {"state": "completed"},
                    "final": True,
                }
            }
        ),
        "",
        "data: not-json",
    ]

    def fake_stream(method: str, url: str, **_kw: Any) -> FakeStream:
        return FakeStream(chunks)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    assert cmd_stream() == 0
    out = capsys.readouterr().out
    assert "hi there" in out
    assert "stream done state=completed" in out


def test_cmd_stream_relay_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch)

    def bad_stream(*_a: Any, **_k: Any) -> FakeStream:
        raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "stream", bad_stream)
    assert cmd_stream() == 1
    assert "relay unreachable" in capsys.readouterr().err


def test_cmd_stream_no_target(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _send_env(monkeypatch, TO="")
    monkeypatch.setattr(httpx, "stream", lambda *_a, **_k: FakeStream([]))
    assert cmd_stream() == 0


# --------------------------------------------------------------------------- view


def _phoenix_payload(spans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "data": {
            "projects": {"edges": [{"node": {"spans": {"edges": [{"node": s} for s in spans]}}}]}
        }
    }


def test_fetch_spans_returns_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: FakeResponse(_phoenix_payload([{"name": "x"}]))
    )
    assert _fetch_spans("http://phoenix") == [{"name": "x"}]


def test_fetch_spans_empty_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: FakeResponse({"data": {"projects": {"edges": []}}})
    )
    assert _fetch_spans("http://phoenix") == []


def test_fetch_spans_raises_on_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse({"errors": ["bad"]}))
    with pytest.raises(RuntimeError):
        _fetch_spans("http://phoenix")


def test_cmd_view_renders_matching_spans(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CTX", "ctx")
    monkeypatch.setenv("PHOENIX_URL", "http://phoenix")
    spans: list[dict[str, Any]] = [
        {
            "name": "a2a.task",
            "spanKind": "SERVER",
            "startTime": "2026-01-01T00:00:00Z",
            "attributes": {
                "session": {"id": "ctx"},
                "agent": {"id": "B"},
                "graph": {"node": {"parent_id": "A"}},
                "openinference": {"span": {"kind": "AGENT"}},
                "o2r": {
                    "task": {"id": "t1", "state": "completed"},
                    "message": {"text": "hi", "reply_text": "echo from B: hi"},
                },
            },
            "events": [
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 0, "final": True}}
            ],
        },
        {
            "name": "other",
            "spanKind": "INTERNAL",
            "startTime": "2026-01-01T00:00:01Z",
            "attributes": {"session": {"id": "different"}},
            "events": [],
        },
    ]
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse(_phoenix_payload(spans)))
    assert cmd_view() == 0
    out = capsys.readouterr().out
    assert "A->B" in out
    assert "in: hi" in out
    assert "out: echo from B: hi" in out
    assert "seq=0" in out
    assert "other" not in out


def test_cmd_view_no_matches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CTX", "ctx")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse(_phoenix_payload([])))
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    assert cmd_view() == 0
    assert "no spans" in capsys.readouterr().out


def test_cmd_view_phoenix_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CTX", "ctx")

    def bad_post(*_a: Any, **_k: Any) -> FakeResponse:
        raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "post", bad_post)
    assert cmd_view() == 1
    assert "phoenix query failed" in capsys.readouterr().err


# --------------------------------------------------------------------------- gif


def test_cmd_gif_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
) -> None:
    """End-to-end: stub Phoenix, render the demo fixture, file appears."""
    from tests.fixtures.sessions import DEMO_SESSION_ID, demo_session_spans

    monkeypatch.setenv("CTX", DEMO_SESSION_ID)
    monkeypatch.setenv("PHOENIX_URL", "http://phoenix")
    out = tmp_path / "out.gif"
    monkeypatch.setenv("OUT", str(out))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_a, **_k: FakeResponse(_phoenix_payload(demo_session_spans())),
    )
    assert cmd_gif() == 0
    assert out.exists() and out.stat().st_size > 0
    summary = capsys.readouterr().out
    assert f"wrote {out}" in summary
    assert "hub=relay" in summary


def test_cmd_gif_default_output_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
) -> None:
    """When OUT is unset, the GIF lands at `assets/sessions/<ctx>.gif`."""
    from tests.fixtures.sessions import DEMO_SESSION_ID, demo_session_spans

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CTX", DEMO_SESSION_ID)
    monkeypatch.delenv("OUT", raising=False)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_a, **_k: FakeResponse(_phoenix_payload(demo_session_spans())),
    )
    assert cmd_gif() == 0
    expected = tmp_path / "assets" / "sessions" / f"{DEMO_SESSION_ID}.gif"
    assert expected.exists()
    assert "wrote" in capsys.readouterr().out


def test_cmd_gif_phoenix_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CTX", "ctx")

    def bad_post(*_a: Any, **_k: Any) -> FakeResponse:
        raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "post", bad_post)
    assert cmd_gif() == 1
    assert "phoenix query failed" in capsys.readouterr().err


def test_cmd_gif_no_spans_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The issue mandates: no spans for the session id => non-zero exit."""
    monkeypatch.setenv("CTX", "missing")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse(_phoenix_payload([])))
    assert cmd_gif() == 1
    assert "no spans" in capsys.readouterr().err


def test_cmd_gif_render_error_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Any,
) -> None:
    """If the renderer raises ValueError mid-flight, surface it as exit 1."""
    monkeypatch.setenv("CTX", "ctx")
    monkeypatch.setenv("OUT", str(tmp_path / "x.gif"))
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_a, **_k: FakeResponse(
            _phoenix_payload(
                [
                    {
                        "name": "a2a.client.send",
                        "spanKind": "CLIENT",
                        "startTime": "2026-01-01T00:00:00Z",
                        "endTime": "2026-01-01T00:00:01Z",
                        # Session matches but the span has no agent.id and no parent,
                        # so reduce_spans produces zero hops and zero leaves.
                        "attributes": {"session": {"id": "ctx"}},
                        "events": [],
                    }
                ]
            )
        ),
    )
    from otel_a2a_relay_arize_phoenix import client as client_mod

    def fake_render(*_a: Any, **_k: Any) -> Any:
        raise ValueError("synthesized render failure")

    monkeypatch.setattr("otel_a2a_relay_arize_phoenix.viz.render_session", fake_render)
    # The cmd_gif imports render_session lazily inside the function, so
    # monkeypatching the module attribute is the right surface.
    monkeypatch.setattr(client_mod, "_attrs", lambda s: {"session.id": "ctx"})
    assert cmd_gif() == 1
    assert "synthesized render failure" in capsys.readouterr().err


# --------------------------------------------------------------- get/tasks/cancel/peers


def test_cmd_get_happy(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse({"result": {"id": "t1"}}))
    assert cmd_get() == 0
    assert '"id": "t1"' in capsys.readouterr().out


def test_cmd_get_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: (_ for _ in ()).throw(httpx.HTTPError("x"))
    )
    assert cmd_get() == 1
    assert "relay unreachable" in capsys.readouterr().err


def test_cmd_get_error_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse({"error": {"message": "no"}}))
    assert cmd_get() == 1
    assert "error:" in capsys.readouterr().err


def test_cmd_tasks_lists_all(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *_a, **_k: FakeResponse(
            {"tasks": [{"id": "t1", "contextId": "ctx", "status": {"state": "completed"}}]}
        ),
    )
    assert cmd_tasks() == 0
    assert "t1 ctx=ctx state=completed" in capsys.readouterr().out


def test_cmd_tasks_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: FakeResponse({"tasks": []}))
    assert cmd_tasks() == 0
    assert "(no tasks)" in capsys.readouterr().out


def test_cmd_tasks_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: (_ for _ in ()).throw(httpx.HTTPError("x")))
    assert cmd_tasks() == 1
    assert "relay unreachable" in capsys.readouterr().err


def test_cmd_cancel_happy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_a, **_k: FakeResponse({"result": {"status": {"state": "canceled"}}}),
    )
    assert cmd_cancel() == 0
    assert "task=t1 state=canceled" in capsys.readouterr().out


def test_cmd_cancel_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_k: (_ for _ in ()).throw(httpx.HTTPError("x"))
    )
    assert cmd_cancel() == 1


def test_cmd_cancel_error_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: FakeResponse({"error": {"message": "x"}}))
    assert cmd_cancel() == 1


def test_cmd_peers_lists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "peers": [
            {
                "id": "B",
                "url": "http://b",
                "card": {
                    "name": "B-echo",
                    "protocolVersion": "0.2.5",
                    "skills": [{"id": "echo"}],
                },
            },
            {"id": "C", "url": "http://c", "card_error": "timeout"},
        ]
    }
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: FakeResponse(payload))
    assert cmd_peers() == 0
    out = capsys.readouterr().out
    assert "B http://b  proto=0.2.5" in out
    assert "C http://c  error=timeout" in out


def test_cmd_peers_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: FakeResponse({"peers": []}))
    assert cmd_peers() == 0
    assert "(no peers configured)" in capsys.readouterr().out


def test_cmd_peers_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: (_ for _ in ()).throw(httpx.HTTPError("x")))
    assert cmd_peers() == 1


# --- main dispatch ---


def test_main_no_args_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_main_unknown_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nope"]) == 2
    assert "unknown subcommand" in capsys.readouterr().err


def test_main_dispatches_to_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TASK", "t1")
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: FakeResponse({"tasks": []}))
    assert main(["tasks"]) == 0
