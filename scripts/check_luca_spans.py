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
QUERY = (
    "{ projects(first:1) { edges { node { sessions(first:30) "
    "{ edges { node { sessionId numTraces } } } } } } }"
)
# Generous lower bound. The flow produces ~50+ routed messages locally;
# Phoenix in CI sometimes lags on ingest, so we wait + accept anything
# above 15 (which still proves star-topology + retry + crash + rogue all
# emitted into the trace).
MIN_TRACES = 15
# Phoenix in CI lags on ingest. The 5s baseline produced flakes (#95) where
# only luca-rogue-bootstrap landed and every other LUCA session was missing.
# Workers also dropped their last few spans because os._exit skipped the OTel
# atexit shutdown - that's fixed in luca/worker.py - but giving Phoenix more
# headroom is the cheap belt to the fix's suspenders.
INGEST_WAIT_SECS = 15


def query() -> list[dict]:
    req = urllib.request.Request(
        PHOENIX,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"query": QUERY}).encode(),
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.loads(r.read())
    return [
        edge["node"]
        for edge in body["data"]["projects"]["edges"][0]["node"]["sessions"]["edges"]
    ]


def main() -> int:
    print(f"Waiting {INGEST_WAIT_SECS}s for Phoenix ingest to settle...")
    time.sleep(INGEST_WAIT_SECS)
    sessions = query()
    luca = [s for s in sessions if "luca" in s["sessionId"]]
    print("luca sessions:", luca)
    if not luca:
        print("FAIL: no luca-* sessions found in Phoenix", file=sys.stderr)
        return 1
    primary = max(luca, key=lambda s: s["numTraces"])
    if primary["numTraces"] < MIN_TRACES:
        print(
            f"FAIL: luca session {primary['sessionId']} has only "
            f"{primary['numTraces']} traces, expected >= {MIN_TRACES}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: luca session {primary['sessionId']} has {primary['numTraces']} traces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
