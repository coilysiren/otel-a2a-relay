#!/usr/bin/env python3
"""Verify Phoenix recorded the LUCA-flow spans after `make luca-demo`.

Used by the luca-demo CI workflow as the final gate. Exits non-zero if
no `luca-*` session is found, or if the session has fewer traces than the
flow should produce.
"""
from __future__ import annotations

import json
import sys
import urllib.request

import time

PHOENIX = "http://localhost:6006/graphql"
# Query every project's sessions, not just the first. The relay's TracerProvider
# sets `service.name=o2r` and no `openinference.project.name`, so its spans land
# in a different Phoenix project than the LUCA peers' spans (`demo`). Looking at
# only `projects(first:1)` was finding whichever project Phoenix returned first
# (often the relay's, which only sees the rogue bypass session because that
# session is the one with no upstream LUCA tracer in play). Aggregating across
# every project picks up the LUCA peers' `luca-aurora-*` session reliably.
QUERY_SESSIONS = (
    "{ projects(first:50) { edges { node { name sessions(first:50) "
    "{ edges { node { sessionId numTraces } } } } } } }"
)
QUERY_PROJECT_SPANS = (
    "{ projects(first:50) { edges { node { name "
    "spans(first:1000) { edges { node { name attributes } } } } } } }"
)
# The orchestrator wraps the whole AURORA flow in a single `orchestrator.flow`
# span, and every step span / relay span / peer span is propagated as a child
# under that root via traceparent injection. So the orchestrator session has
# exactly one trace (the flow root), not one trace per routed message. The
# old >=15 invariant predated traceparent propagation, when each message/send
# started its own trace at the relay. The structural assertion that survives
# the propagation change: the orchestrator session AND the rogue-bootstrap
# session must both exist (proves star-topology coordination + the rogue's
# bypass attempt both reached Phoenix) and the orchestrator session's trace
# must hold many spans (proves the workers all checked in under it).
MIN_ORCHESTRATOR_SPANS = 25
# Phoenix in CI lags on ingest. The 5s baseline produced flakes (#95) where
# only luca-rogue-bootstrap landed and every other LUCA session was missing.
# Workers also dropped their last few spans because os._exit skipped the OTel
# atexit shutdown - that's fixed in luca/worker.py - but giving Phoenix more
# headroom is the cheap belt to the fix's suspenders.
INGEST_WAIT_SECS = 15


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


def count_session_spans(session_id: str) -> int:
    """Walk every span in every project and count those carrying
    `session.id == session_id`. The orchestrator session can have spans
    in both the LUCA peers' project and the relay's project; both count."""
    body = _post(QUERY_PROJECT_SPANS)
    count = 0
    for project in body["data"]["projects"]["edges"]:
        for edge in project["node"]["spans"]["edges"]:
            attrs = edge["node"].get("attributes") or "{}"
            try:
                parsed = json.loads(attrs) if isinstance(attrs, str) else attrs
            except json.JSONDecodeError:
                continue
            if parsed.get("session.id") == session_id:
                count += 1
    return count


def main() -> int:
    print(f"Waiting {INGEST_WAIT_SECS}s for Phoenix ingest to settle...")
    time.sleep(INGEST_WAIT_SECS)
    luca = list_luca_sessions()
    print("luca sessions:", luca)
    if not luca:
        print("FAIL: no luca-* sessions found in Phoenix", file=sys.stderr)
        return 1
    aurora = [s for s in luca if s["sessionId"].startswith("luca-aurora-")]
    rogue = [s for s in luca if s["sessionId"] == "luca-rogue-bootstrap"]
    if not aurora:
        print("FAIL: no luca-aurora-* session found", file=sys.stderr)
        return 1
    if not rogue:
        print("FAIL: luca-rogue-bootstrap session missing", file=sys.stderr)
        return 1
    primary = aurora[0]
    spans = count_session_spans(primary["sessionId"])
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
