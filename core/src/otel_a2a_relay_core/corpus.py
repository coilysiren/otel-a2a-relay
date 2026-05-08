"""Trace zoo / fixture corpus loader.

The corpus lives at `core/tests/fixtures/trace_zoo/` as one JSON file per
fixture, each a list of canonical Phoenix-shaped spans. This module loads
fixtures by name, lists what is available, and hydrates a `MemorySpanStore`
for tests that want a queryable surface.

The corpus is the input to the assertion macros (#71) and the substrate
for future shape-clustering / trace-diff work. New fixtures should target
distinct protocol shapes - one fixture per shape, no padding.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from otel_a2a_relay_core.span_store import MemorySpanStore

CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "trace_zoo"


def list_fixtures(corpus_dir: Path | None = None) -> list[str]:
    """All fixture names in the corpus, sorted."""
    base = corpus_dir or CORPUS_DIR
    return sorted(p.stem for p in base.glob("*.json"))


def load_fixture(name: str, corpus_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load one fixture by name. Raises FileNotFoundError if missing."""
    base = corpus_dir or CORPUS_DIR
    path = base / f"{name}.json"
    with path.open() as fh:
        spans = json.load(fh)
    if not isinstance(spans, list):
        raise ValueError(f"corpus fixture {name!r} is not a list of spans")
    return spans


def load_into_store(
    name: str,
    store: MemorySpanStore | None = None,
    corpus_dir: Path | None = None,
) -> MemorySpanStore:
    """Hydrate a `MemorySpanStore` with one fixture's spans.

    Returns the store. Creates a fresh one if none is passed, so callers
    can write `store = load_into_store("worked_example_completed")`.
    """
    target = store if store is not None else MemorySpanStore()
    target.add_all(load_fixture(name, corpus_dir))
    return target


def load_all(corpus_dir: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """All fixtures, keyed by name. For shape clustering / coverage reports."""
    return {name: load_fixture(name, corpus_dir) for name in list_fixtures(corpus_dir)}
