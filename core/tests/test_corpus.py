"""Tests for the trace-zoo fixture corpus loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from otel_a2a_relay_core.corpus import (
    CORPUS_DIR,
    list_fixtures,
    load_all,
    load_fixture,
    load_into_store,
)
from otel_a2a_relay_core.span_store import MemorySpanStore


def test_corpus_dir_exists() -> None:
    assert CORPUS_DIR.is_dir(), f"corpus dir missing at {CORPUS_DIR}"


def test_list_fixtures_finds_at_least_ten() -> None:
    """The dispatch ticket asks for 10-20 fixtures. Guard the lower bound."""
    assert len(list_fixtures()) >= 10


def test_list_fixtures_is_sorted() -> None:
    names = list_fixtures()
    assert names == sorted(names)


def test_every_fixture_loads_to_a_list_of_dicts() -> None:
    for name in list_fixtures():
        spans = load_fixture(name)
        assert isinstance(spans, list), f"{name} did not load as a list"
        assert spans, f"{name} is empty"
        for span in spans:
            assert isinstance(span, dict), f"{name} contains a non-dict span"
            assert "name" in span, f"{name} has a span missing 'name'"


def test_worked_example_completed_carries_expected_session() -> None:
    spans = load_fixture("worked_example_completed")
    sessions = {s.get("attributes", {}).get("session", {}).get("id") for s in spans}
    assert sessions == {"ws-completed"}


def test_load_into_store_creates_fresh_store_when_none_passed() -> None:
    store = load_into_store("worked_example_completed")
    assert isinstance(store, MemorySpanStore)
    out = store.session_spans("ws-completed")
    assert len(out) == 5
    assert out[0]["name"] == "a2a.client.send"


def test_load_into_store_appends_to_existing_store() -> None:
    store = MemorySpanStore()
    load_into_store("single_send_sync", store=store)
    load_into_store("worked_example_failed", store=store)
    assert len(store) == 2 + 2  # 2 spans in single_send_sync + 2 in failed


def test_load_all_keys_match_list_fixtures() -> None:
    fixtures = load_all()
    assert set(fixtures.keys()) == set(list_fixtures())


def test_load_fixture_raises_for_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_fixture("does-not-exist", corpus_dir=tmp_path)


def test_load_fixture_rejects_non_list_payload(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "not a list"}))
    with pytest.raises(ValueError, match="not a list of spans"):
        load_fixture("bad", corpus_dir=tmp_path)


def test_failure_class_fixtures_label_their_bucket() -> None:
    """Each failure-mode fixture must carry `o2r.relay.failure_class`.

    Lets the assertion macros (#71) assert against the failure-class
    coverage of the corpus without parsing fixture names.
    """
    expected = {
        "worked_example_failed": "peer_jsonrpc_error",
        "peer_404": "peer_404",
        "peer_timeout": "timeout",
        "relay_reject_topology": "topology_violation",
    }
    for name, want in expected.items():
        spans = load_fixture(name)
        seen = {
            ((s.get("attributes") or {}).get("o2r") or {}).get("relay", {}).get("failure_class")
            for s in spans
        }
        assert want in seen, f"{name} missing failure_class={want}"
