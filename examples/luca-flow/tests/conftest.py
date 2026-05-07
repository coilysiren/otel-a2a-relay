"""Shared fixtures for the LUCA-flow snapshot suite.

The session-scoped `luca_dist` fixture runs the demo end-to-end exactly
once with `LUCA_FREEZE_TIME` pinned. Every test in the suite asserts
against the resulting `dist/` directory. This costs ~15s per session.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LUCA_ROOT = REPO_ROOT / "examples" / "luca-flow"
DIST_DIR = LUCA_ROOT / "dist"
STAGE_DIR = LUCA_ROOT / ".luca-stage"
FROZEN_TIME = "2026-01-01T00:00:00Z"


@pytest.fixture(scope="session")
def luca_dist() -> Iterator[Path]:
    """Run the LUCA-flow demo with frozen time and yield the dist path.

    Backend-agnostic: --no-require-collector skips the OTLP healthz gate so
    the demo can run without Phoenix or Tempo present. Spans still emit
    over OTLP/HTTP; the receiver just may not be there to ingest them, and
    the demo doesn't care.
    """
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)

    env = {**os.environ, "LUCA_FREEZE_TIME": FROZEN_TIME}
    result = subprocess.run(
        [sys.executable, "-m", "luca.runner", "--no-require-collector"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"luca demo failed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not DIST_DIR.exists():
        raise RuntimeError(f"luca demo did not produce dist at {DIST_DIR}")
    yield DIST_DIR
