"""Shared fixtures for the LUCA-flow snapshot suite.

The session-scoped `luca_dist` fixture runs the demo end-to-end exactly
once with `LUCA_FREEZE_TIME` pinned. Every test in the suite asserts
against the resulting `dist/` directory. This costs ~15s per session.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LUCA_ROOT = REPO_ROOT / "examples" / "luca-flow"
DIST_DIR = LUCA_ROOT / "dist"
STAGE_DIR = LUCA_ROOT / ".luca-stage"
FROZEN_TIME = "2026-01-01T00:00:00Z"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def luca_dist() -> Iterator[Path]:
    """Run the LUCA-flow demo with frozen time and yield the dist path."""
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)

    env = {**os.environ, "LUCA_FREEZE_TIME": FROZEN_TIME}
    result = subprocess.run(
        [sys.executable, "-m", "otel_a2a_relay.luca.runner", "--no-require-phoenix"],
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


@pytest.fixture(scope="session")
def luca_dist_url(luca_dist: Path) -> Iterator[str]:
    """Serve the dist over a localhost http.server. Yields the base URL."""
    port = _free_port()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(luca_dist), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # silence  # noqa: A002
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give it a tick to start accepting connections.
    time.sleep(0.1)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
