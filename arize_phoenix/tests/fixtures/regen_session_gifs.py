"""Regenerate the byte-exact baseline GIF used by the visual diff and README.

`make gif-fixture-update` invokes this. It writes a single canonical
GIF at `assets/session-topology.gif`. The visual diff test in
`tests/test_viz.py` hashes that file's bytes; intentional renderer
changes are picked up by re-running this and committing the diff.

One file, two roles: the byte-exact baseline AND the README hero
artifact. Keeping it one file avoids the trap where the README and
the test get out of sync.
"""

from __future__ import annotations

from pathlib import Path

from otel_a2a_relay_arize_phoenix.viz import render_session

from tests.fixtures.sessions import DEMO_SESSION_ID, demo_session_spans

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "assets" / "session-topology.gif"


def main() -> int:
    session = render_session(demo_session_spans(), DEMO_SESSION_ID, BASELINE_PATH)
    print(
        f"wrote {BASELINE_PATH}  hub={session.hub}  leaves={len(session.leaves)}  "
        f"hops={len(session.hops)}  spans={session.span_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
