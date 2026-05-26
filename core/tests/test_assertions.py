"""Tests for the reusable assertion macros plus corpus-wide invariant checks."""

from __future__ import annotations

import re
from typing import Any

from otel_a2a_relay_core.assertions import (
    every_relay_emitted_span_carries_agent_role,
    every_relay_emitted_span_carries_session_id,
    every_relay_failure_has_class,
    every_tool_call_is_observed,
    graph_node_parent_resolves,
    no_pii_in_attributes,
    stream_chunk_seqs_are_monotonic,
    task_state_progression_is_valid,
)
from otel_a2a_relay_core.corpus import list_fixtures, load_fixture
from otel_a2a_relay_core.span_store import MemorySpanStore


def _llm_span(name: str, sid: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "session": {"id": sid},
        "openinference": {"span": {"kind": "LLM"}},
        "agent": {"id": "B", "role": "worker"},
    }
    attrs.update(extra)
    return {
        "name": name,
        "spanKind": "INTERNAL",
        "startTime": start,
        "endTime": end,
        "attributes": attrs,
        "events": [],
    }


def _tool_span(name: str, sid: str, start: str, end: str) -> dict[str, Any]:
    return {
        "name": name,
        "spanKind": "INTERNAL",
        "startTime": start,
        "endTime": end,
        "attributes": {
            "session": {"id": sid},
            "openinference": {"span": {"kind": "TOOL"}},
        },
        "events": [],
    }


def test_every_tool_call_is_observed_passes_when_paired() -> None:
    spans = [
        _llm_span(
            "llm",
            "s",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:10Z",
            **{"gen_ai": {"tool": {"name": "search"}}},
        ),
        _tool_span("tool.search", "s", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z"),
    ]
    assert every_tool_call_is_observed(spans) == []


def test_every_tool_call_is_observed_flags_missing_tool() -> None:
    spans = [
        _llm_span(
            "llm",
            "s",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:10Z",
            **{"gen_ai": {"tool": {"name": "search"}}},
        ),
    ]
    violations = every_tool_call_is_observed(spans)
    assert violations
    assert "no TOOL span observed" in violations[0]


def test_every_tool_call_is_observed_flags_missing_session_id() -> None:
    span = _llm_span(
        "llm",
        "s",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:10Z",
        **{"gen_ai": {"tool": {"name": "search"}}},
    )
    span["attributes"].pop("session")
    violations = every_tool_call_is_observed([span])
    assert any("has no session.id" in v for v in violations)


def test_every_tool_call_is_observed_ignores_llm_without_tool_attr() -> None:
    spans = [_llm_span("llm", "s", "2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z")]
    assert every_tool_call_is_observed(spans) == []


def test_every_tool_call_is_observed_ignores_orphan_tool_span() -> None:
    """A TOOL span with no LLM trigger is allowed - the macro asserts on the
    LLM side, not the TOOL side."""
    spans = [_tool_span("tool", "s", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z")]
    assert every_tool_call_is_observed(spans) == []


def test_every_tool_call_is_observed_skips_tool_span_with_non_string_session() -> None:
    tool = _tool_span("tool", "s", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z")
    tool["attributes"]["session"] = "scalar"  # malformed
    spans = [
        _llm_span(
            "llm",
            "s",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:10Z",
            **{"gen_ai": {"tool": {"name": "search"}}},
        ),
        tool,
    ]
    violations = every_tool_call_is_observed(spans)
    assert violations  # malformed tool can't index by session


def test_no_pii_flags_email() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {"input": {"value": "ping someone@example.com"}},
            "events": [],
        }
    ]
    violations = no_pii_in_attributes(spans)
    assert any("email" in v for v in violations)


def test_no_pii_flags_ssn() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {"note": "ID 123-45-6789"},
            "events": [],
        }
    ]
    violations = no_pii_in_attributes(spans)
    assert any("ssn" in v for v in violations)


def test_no_pii_skip_keys_silences_known_payload_attrs() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {"input": {"value": "user@example.com"}},
            "events": [],
        }
    ]
    assert no_pii_in_attributes(spans, skip_keys=["input.value"]) == []


def test_no_pii_extra_patterns_catch_caller_specific_secrets() -> None:
    custom = [("api_key", re.compile(r"sk-[A-Za-z0-9]{32,}"))]
    spans = [
        {
            "name": "n",
            "attributes": {"meta": {"key": "sk-abcdefghijklmnopqrstuvwxyz0123456789"}},
            "events": [],
        }
    ]
    assert any("api_key" in v for v in no_pii_in_attributes(spans, extra_patterns=custom))


def test_no_pii_walks_list_values() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {"recipients": ["one@example.com", "two@example.com"]},
            "events": [],
        }
    ]
    violations = no_pii_in_attributes(spans)
    assert any("recipients[0]" in v for v in violations)
    assert any("recipients[1]" in v for v in violations)


def test_flat_keys_no_op_on_non_dict_input() -> None:
    """Importing _flat_keys directly to exercise the early-return branch
    when handed a non-dict (e.g. a stray scalar attribute)."""
    from otel_a2a_relay_core.assertions import _flat_keys

    assert list(_flat_keys("not a dict")) == []


def test_no_pii_walks_event_attributes() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {},
            "events": [{"name": "tick", "attributes": {"who": "person@example.com"}}],
        }
    ]
    violations = no_pii_in_attributes(spans)
    assert any("event 'tick'" in v for v in violations)


def test_no_pii_event_skip_keys_full_path() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {},
            "events": [{"name": "tick", "attributes": {"who": "person@example.com"}}],
        }
    ]
    violations = no_pii_in_attributes(spans, skip_keys=["events[tick].who"])
    assert violations == []


def test_no_pii_event_skip_keys_relative() -> None:
    spans = [
        {
            "name": "n",
            "attributes": {},
            "events": [{"name": "tick", "attributes": {"who": "person@example.com"}}],
        }
    ]
    violations = no_pii_in_attributes(spans, skip_keys=["who"])
    assert violations == []


def test_macro_accepts_memoryspanstore() -> None:
    """All macros accept either a list or a MemorySpanStore."""
    store = MemorySpanStore()
    store.add({"name": "a2a.task", "attributes": {"session.id": "x", "agent.role": "worker"}})
    assert every_relay_emitted_span_carries_session_id(store) == []
    assert every_relay_emitted_span_carries_agent_role(store) == []


def test_relay_emitted_role_invariant_flags_missing_role() -> None:
    spans = [{"name": "a2a.task", "attributes": {"session": {"id": "x"}}}]
    violations = every_relay_emitted_span_carries_agent_role(spans)
    assert violations and "agent.role" in violations[0]


def test_relay_emitted_role_invariant_skips_non_relay_spans() -> None:
    """Caller-flow spans (`llm.*`, `tool.*`) are out of scope."""
    spans = [
        {"name": "llm.generate", "attributes": {}},
        {"name": "tool.search", "attributes": {}},
    ]
    assert every_relay_emitted_span_carries_agent_role(spans) == []


def test_failure_class_invariant_flags_exception_without_class() -> None:
    spans = [
        {
            "name": "a2a.task",
            "attributes": {"agent": {"role": "worker"}, "session": {"id": "x"}},
            "events": [{"name": "exception", "attributes": {}}],
        }
    ]
    assert every_relay_failure_has_class(spans)


def test_failure_class_invariant_passes_when_set() -> None:
    spans = [
        {
            "name": "a2a.relay.reject",
            "attributes": {"o2r": {"relay": {"failure_class": "topology_violation"}}},
            "events": [],
        }
    ]
    assert every_relay_failure_has_class(spans) == []


def test_failure_class_invariant_ignores_clean_relay_span() -> None:
    spans = [{"name": "a2a.task", "events": []}]
    assert every_relay_failure_has_class(spans) == []


def test_session_id_invariant_flags_missing() -> None:
    spans = [{"name": "a2a.task", "attributes": {"agent": {"role": "worker"}}}]
    violations = every_relay_emitted_span_carries_session_id(spans)
    assert violations


def test_graph_parent_resolves_passes() -> None:
    spans = [
        {"name": "a2a.client.send", "attributes": {"agent": {"id": "A"}}},
        {
            "name": "a2a.task",
            "attributes": {"agent": {"id": "B"}, "graph": {"node": {"parent_id": "A"}}},
        },
    ]
    assert graph_node_parent_resolves(spans) == []


def test_graph_parent_resolves_flags_dangling_parent() -> None:
    spans = [
        {
            "name": "a2a.task",
            "attributes": {"agent": {"id": "B"}, "graph": {"node": {"parent_id": "GHOST"}}},
        }
    ]
    violations = graph_node_parent_resolves(spans)
    assert violations and "GHOST" in violations[0]


def test_graph_parent_accepts_graph_node_id_as_agent_declaration() -> None:
    """A span that only sets `graph.node.id` (no `agent.id`) still
    declares an agent for parent resolution."""
    spans = [
        {"name": "a2a.client.send", "attributes": {"graph": {"node": {"id": "A"}}}},
        {
            "name": "a2a.task",
            "attributes": {"agent": {"id": "B"}, "graph": {"node": {"parent_id": "A"}}},
        },
    ]
    assert graph_node_parent_resolves(spans) == []


def test_task_state_progression_passes_for_completed_flow() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "submitted", "to": "working"},
                },
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "working", "to": "completed"},
                },
            ],
        }
    ]
    assert task_state_progression_is_valid(spans) == []


def test_task_state_progression_flags_invalid_transition() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "submitted", "to": "completed"},
                },
            ],
        }
    ]
    violations = task_state_progression_is_valid(spans)
    assert violations and "invalid transition" in violations[0]


def test_task_state_progression_flags_broken_chain() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "submitted", "to": "working"},
                },
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "submitted", "to": "completed"},
                },
            ],
        }
    ]
    violations = task_state_progression_is_valid(spans)
    assert any("sequence broken" in v for v in violations)


def test_task_state_progression_flags_missing_fields() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [{"name": "o2r.task.state_change", "attributes": {}}],
        }
    ]
    assert any("missing from/to" in v for v in task_state_progression_is_valid(spans))


def test_task_state_progression_flags_unknown_state() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {
                    "name": "o2r.task.state_change",
                    "attributes": {"from": "imaginary", "to": "completed"},
                },
            ],
        }
    ]
    assert any("unknown from-state" in v for v in task_state_progression_is_valid(spans))


def test_stream_chunk_seqs_monotonic_passes() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 0, "final": False}},
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 1, "final": False}},
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 2, "final": True}},
            ],
        }
    ]
    assert stream_chunk_seqs_are_monotonic(spans) == []


def test_stream_chunk_seqs_monotonic_flags_regression() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 1, "final": False}},
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 1, "final": False}},
            ],
        }
    ]
    assert any("not greater than" in v for v in stream_chunk_seqs_are_monotonic(spans))


def test_stream_chunk_seqs_monotonic_flags_chunk_after_final() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 0, "final": True}},
                {"name": "a2a.message.stream_chunk", "attributes": {"seq": 1, "final": False}},
            ],
        }
    ]
    assert any("after final" in v for v in stream_chunk_seqs_are_monotonic(spans))


def test_stream_chunk_seqs_monotonic_flags_missing_seq() -> None:
    spans = [
        {
            "name": "a2a.task",
            "events": [
                {"name": "a2a.message.stream_chunk", "attributes": {"final": False}},
            ],
        }
    ]
    assert any("missing integer seq" in v for v in stream_chunk_seqs_are_monotonic(spans))


# --- Corpus-wide invariant checks: every macro x every fixture. ---


def test_corpus_satisfies_pii_invariant() -> None:
    """The corpus must be PII-clean. Fixtures route message content through
    `input.value` / `output.value`; those are skipped because the strings
    are JSON payloads with no real PII."""
    skip = ["input.value", "output.value", "tool.input", "tool.output"]
    for name in list_fixtures():
        spans = load_fixture(name)
        violations = no_pii_in_attributes(spans, skip_keys=skip)
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_relay_spans_carry_session_id() -> None:
    for name in list_fixtures():
        violations = every_relay_emitted_span_carries_session_id(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_relay_spans_carry_agent_role() -> None:
    for name in list_fixtures():
        violations = every_relay_emitted_span_carries_agent_role(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_failure_fixtures_carry_failure_class() -> None:
    for name in list_fixtures():
        violations = every_relay_failure_has_class(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_graph_parents_resolve() -> None:
    for name in list_fixtures():
        violations = graph_node_parent_resolves(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_task_state_progressions_are_valid() -> None:
    for name in list_fixtures():
        violations = task_state_progression_is_valid(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_stream_chunk_seqs_are_monotonic() -> None:
    for name in list_fixtures():
        violations = stream_chunk_seqs_are_monotonic(load_fixture(name))
        assert not violations, f"{name}:\n  " + "\n  ".join(violations)


def test_corpus_tool_call_fixture_satisfies_invariant() -> None:
    """The dedicated tool_call_flow fixture exercises the
    `every_tool_call_is_observed` macro. Other fixtures are not expected
    to declare tool calls, so we run the macro only against the targeted
    fixture rather than the whole corpus."""
    spans = load_fixture("tool_call_flow")
    assert every_tool_call_is_observed(spans) == []
