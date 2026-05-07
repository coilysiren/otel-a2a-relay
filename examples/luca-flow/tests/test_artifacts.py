"""Lock the LUCA-flow demo's text artifacts via byte-level snapshot diff.

Covers `CHANGELOG.md`, `delivery-report.md`, `delivery-report.json`, and
every generated HTML page. The visual layer of the site is locked
separately by `test_visual.py`.

To regenerate baselines after an intentional change, run with
`UPDATE_LUCA_SNAPSHOTS=1`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots" / "dist"
UPDATE = os.environ.get("UPDATE_LUCA_SNAPSHOTS") == "1"

ARTIFACTS = [
    "CHANGELOG.md",
    "delivery-report.md",
    "delivery-report.json",
    "CITATIONS.html",
    "index.html",
    "gallery.html",
    "science.html",
    "product.html",
    "mission.html",
    "about.html",
    "preorder.html",
]


def _assert_snapshot(actual: bytes, snap_path: Path) -> None:
    if UPDATE or not snap_path.exists():
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_bytes(actual)
        return
    expected = snap_path.read_bytes()
    if actual != expected:
        # Show a textual diff when both sides decode as text.
        try:
            import difflib

            a = expected.decode("utf-8").splitlines()
            b = actual.decode("utf-8").splitlines()
            diff = "\n".join(
                difflib.unified_diff(a, b, fromfile=str(snap_path), tofile="actual", lineterm="")
            )
            pytest.fail(f"snapshot mismatch for {snap_path.name}:\n{diff}")
        except UnicodeDecodeError:
            pytest.fail(f"snapshot mismatch (binary) for {snap_path.name}")


@pytest.mark.luca_flow
@pytest.mark.parametrize("name", ARTIFACTS)
def test_artifact_matches_snapshot(luca_dist: Path, name: str) -> None:
    actual = (luca_dist / name).read_bytes()
    _assert_snapshot(actual, SNAPSHOT_DIR / name)
