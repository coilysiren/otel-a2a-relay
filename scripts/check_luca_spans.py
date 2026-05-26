#!/usr/bin/env python3
"""Verify Phoenix recorded the LUCA-flow spans after `make luca-demo`.

Used by the luca-demo CI workflow as the final gate. Exits non-zero if
no `luca-*` session is found, or if the session has fewer traces than the
flow should produce.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

PHOENIX = "http://localhost:6006/graphql"
# Aggregate across every project; relay spans (o2r) and peer spans (demo) split.
QUERY_SESSIONS = (
    "{ projects(first:50) { edges { node { name sessions(first:50) "
    "{ edges { node { sessionId numTraces } } } } } } }"
)
QUERY_PROJECT_SPANS = (
    "{ projects(first:50) { edges { node { name "
    "spans(first:1000) { edges { node { name attributes } } } } } } }"
)
# Post-traceparent: orchestrator session has one trace; require many spans on it.
MIN_ORCHESTRATOR_SPANS = 25
# Poll-until-landed instead of a fixed sleep; OTLP HTTP has no ack primitive.
INGEST_POLL_TIMEOUT_SECS = 30
INGEST_POLL_INTERVAL_SECS = 1.0


def _post(query: str) -> dict:
    req = urllib.request.Request(
        PHOENIX,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"query": query}).encode(),
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def list_luca_sessions() -> list[dict]:
    body = _post(QUERY_SESSIONS)
    out: list[dict] = []
    for project in body["data"]["projects"]["edges"]:
        project_name = project["node"]["name"]
        for edge in project["node"]["sessions"]["edges"]:
            node = edge["node"]
            if "luca" not in node["sessionId"]:
                continue
            node["projectName"] = project_name
            out.append(node)
    return out


def _flatten(d: object, prefix: str = "") -> dict:
    """Re-flatten Phoenix's nested attribute dict back to dotted keys.
    Phoenix folds `session.id` to {"session": {"id": ...}} on the way out."""
    out: dict = {}
    if not isinstance(d, dict):
        return {prefix: d} if prefix else {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _span_session_id(span: dict) -> str | None:
    raw = span.get("attributes")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    flat = _flatten(raw or {})
    val = flat.get("session.id")
    return val if isinstance(val, str) else None


def count_session_spans(session_id: str) -> int:
    """Walk every span in every project and count those carrying
    `session.id == session_id`. The orchestrator session can have spans
    in both the LUCA peers' project and the relay's project; both count."""
    body = _post(QUERY_PROJECT_SPANS)
    count = 0
    for project in body["data"]["projects"]["edges"]:
        for edge in project["node"]["spans"]["edges"]:
            if _span_session_id(edge["node"]) == session_id:
                count += 1
    return count


def _poll_until_span_count(session_id: str, target: int) -> int:
    """Poll the per-span count until the target is reached or the deadline passes.

    Returns the last count observed. Caller is responsible for asserting it
    meets the target.
    """
    deadline = time.monotonic() + INGEST_POLL_TIMEOUT_SECS
    spans = 0
    while True:
        spans = count_session_spans(session_id)
        if spans >= target:
            return spans
        if time.monotonic() >= deadline:
            return spans
        time.sleep(INGEST_POLL_INTERVAL_SECS)


def _poll_until_both_sessions_landed() -> tuple[list[dict], list[dict], list[dict]]:
    """Poll Phoenix until both expected sessions land or the deadline passes.

    Returns (all_luca_sessions, aurora_sessions, rogue_sessions). Caller is
    responsible for asserting non-emptiness. The poll handles the async
    nature of OTLP HTTP ingest deterministically: zero dead-wait when ingest
    is fast, bounded retry when slow.
    """
    deadline = time.monotonic() + INGEST_POLL_TIMEOUT_SECS
    luca: list[dict] = []
    aurora: list[dict] = []
    rogue: list[dict] = []
    while True:
        luca = list_luca_sessions()
        aurora = [s for s in luca if s["sessionId"].startswith("luca-aurora-")]
        rogue = [s for s in luca if s["sessionId"] == "luca-rogue-bootstrap"]
        if aurora and rogue:
            return luca, aurora, rogue
        if time.monotonic() >= deadline:
            return luca, aurora, rogue
        time.sleep(INGEST_POLL_INTERVAL_SECS)


def main() -> int:
    print(f"Polling Phoenix for ingest up to {INGEST_POLL_TIMEOUT_SECS}s...")
    luca, aurora, rogue = _poll_until_both_sessions_landed()
    print("luca sessions:", luca)
    if not luca:
        print("FAIL: no luca-* sessions found in Phoenix", file=sys.stderr)
        return 1
    if not aurora:
        print("FAIL: no luca-aurora-* session found", file=sys.stderr)
        return 1
    if not rogue:
        print("FAIL: luca-rogue-bootstrap session missing", file=sys.stderr)
        return 1
    primary = aurora[0]
    spans = _poll_until_span_count(primary["sessionId"], MIN_ORCHESTRATOR_SPANS)
    print(f"orchestrator session {primary['sessionId']} has {spans} spans")
    if spans < MIN_ORCHESTRATOR_SPANS:
        print(
            f"FAIL: orchestrator session {primary['sessionId']} has only "
            f"{spans} spans, expected >= {MIN_ORCHESTRATOR_SPANS}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: orchestrator session has {spans} spans, rogue session present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
