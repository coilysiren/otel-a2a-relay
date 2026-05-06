from __future__ import annotations

from otel_a2a_relay.client import _attrs, _flatten


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
    attrs = _attrs(span)
    assert attrs["session.id"] == "ctx"


def test_attrs_handles_already_dict() -> None:
    span = {"attributes": {"agent": {"id": "A"}}}
    assert _attrs(span)["agent.id"] == "A"


def test_attrs_returns_empty_when_unparseable() -> None:
    span = {"attributes": "not-json"}
    assert _attrs(span) == {}


def test_server_parse_peers_handles_whitespace_and_empty() -> None:
    from otel_a2a_relay.server import parse_peers

    assert parse_peers(None) == {}
    assert parse_peers("") == {}
    assert parse_peers(" A=http://a , B=http://b ") == {"A": "http://a", "B": "http://b"}
    assert parse_peers("malformed,A=http://a") == {"A": "http://a"}
