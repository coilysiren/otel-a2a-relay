"""Phoenix GraphQL helper tests.

The helpers used to live in `client.py`. Moving them to `phoenix.py`
keeps the surface small enough that two consumers (the readable
transcript and the topology GIF) can share the fetch + flatten path
without reaching into client internals.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from otel_a2a_relay import phoenix as phx_mod
from otel_a2a_relay.phoenix import attrs, fetch_spans, flatten, session_spans


class FakeResponse:
    def __init__(self, payload: Any, *, raise_err: bool = False) -> None:
        self._payload = payload
        self._raise = raise_err
        self.status_code = 200

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self._raise:
            raise httpx.HTTPError("boom")


def _capturing_post(captured: dict[str, Any], payload: Any) -> Any:
    def fake(url: str, **kw: Any) -> FakeResponse:
        captured["url"] = url
        captured["json"] = kw.get("json")
        return FakeResponse(payload)

    return fake


def test_flatten_reverses_nesting() -> None:
    nested = {"session": {"id": "x"}, "agent": {"id": "A", "name": "alpha"}}
    flat = flatten(nested)
    assert flat == {"session.id": "x", "agent.id": "A", "agent.name": "alpha"}


def test_flatten_handles_scalar_root() -> None:
    assert flatten("scalar") == {}
    assert flatten("scalar", prefix="x") == {"x": "scalar"}


def test_attrs_parses_string_payload() -> None:
    span = {"attributes": '{"session": {"id": "demo"}}'}
    assert attrs(span) == {"session.id": "demo"}


def test_attrs_returns_empty_for_invalid_string() -> None:
    span = {"attributes": "not json"}
    assert attrs(span) == {}


def test_attrs_handles_missing_attributes_field() -> None:
    assert attrs({}) == {}


def test_fetch_spans_unwraps_graphql_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    payload = {
        "data": {
            "projects": {
                "edges": [
                    {
                        "node": {
                            "spans": {
                                "edges": [
                                    {"node": {"name": "a2a.task", "spanKind": "SERVER"}},
                                    {"node": {"name": "a2a.client.send", "spanKind": "CLIENT"}},
                                ]
                            }
                        }
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(httpx, "post", _capturing_post(captured, payload))

    spans = fetch_spans("http://phoenix:6006")
    assert [s["name"] for s in spans] == ["a2a.task", "a2a.client.send"]
    assert captured["url"] == "http://phoenix:6006/graphql"
    assert captured["json"]["variables"] == {"limit": 200}


def test_fetch_spans_returns_empty_when_no_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_kw: FakeResponse({"data": {"projects": {"edges": []}}})
    )
    assert fetch_spans("http://phoenix:6006") == []


def test_fetch_spans_raises_on_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post", lambda *_a, **_kw: FakeResponse({"errors": [{"message": "bad query"}]})
    )
    with pytest.raises(RuntimeError, match="graphql errors"):
        fetch_spans("http://phoenix:6006")


def test_session_spans_filters_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spans in a session come out sorted by `(startTime, name)` and other
    sessions are dropped, so the renderer gets stable input."""

    def make_span(name: str, start: str, sid: str) -> dict[str, Any]:
        return {
            "name": name,
            "spanKind": "SERVER",
            "startTime": start,
            "attributes": {"session": {"id": sid}},
        }

    payload = {
        "data": {
            "projects": {
                "edges": [
                    {
                        "node": {
                            "spans": {
                                "edges": [
                                    {"node": make_span("late", "2026-01-01T00:00:02Z", "ours")},
                                    {"node": make_span("early-b", "2026-01-01T00:00:00Z", "ours")},
                                    {"node": make_span("other", "2026-01-01T00:00:01Z", "theirs")},
                                    {"node": make_span("early-a", "2026-01-01T00:00:00Z", "ours")},
                                ]
                            }
                        }
                    }
                ]
            }
        }
    }
    monkeypatch.setattr(httpx, "post", lambda *_a, **_kw: FakeResponse(payload))
    out = session_spans("http://phoenix:6006", "ours")
    assert [s["name"] for s in out] == ["early-a", "early-b", "late"], (
        "session_spans must produce stable order: tie-broken by span name"
    )


def test_module_advertises_default_phoenix_url() -> None:
    assert phx_mod.DEFAULT_PHOENIX_URL.startswith("http://")
