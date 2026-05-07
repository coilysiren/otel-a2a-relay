#!/usr/bin/env python
"""Phoenix-side setup for the o2r relay's data-legibility surface.

Idempotently provisions:

- **Annotation configs.** Two named configs the relay's spans expect Phoenix
  to render against:
    - `relay_failure_class` - categorical (multi-label in spirit; Phoenix's
      categorical type is single-pick per annotation, so the script defines
      one label per failure class). Applied to any erroring relay span.
      Values: `topology_violation`, `peer_disconnect`, `peer_404`, `timeout`,
      `peer_jsonrpc_error`, `unknown`.
    - `task_outcome_correct` - binary categorical (`correct=1.0`,
      `incorrect=0.0`), `optimization_direction=MAXIMIZE`. Applied to a
      session's terminal `orchestrator.flow_complete` span.

- **Datasets.** Two empty named datasets the team can seed via Phoenix's UI
  ("Add to dataset" on a hand-picked span) or the GraphQL `addSpansToDataset`
  mutation:
    - `relay-decisions-golden` - golden examples of relay routing decisions.
      Inputs: trimmed `{from_role, from_id, target_id, target_role, message_text,
      session_id?}`. Outputs: `{decision, reason?}`.
    - `relay-failures-regression` - regression dataset seeded from the
      existing failure spans (topology-reject for worker-g, peer-disconnect
      for worker-d).

Re-running the script is a no-op once everything exists. `--dry-run` prints
the plan without writing.

Usage:

    uv run python -m scripts.phoenix_bootstrap [--phoenix http://localhost:6006] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

DEFAULT_PHOENIX_URL = "http://localhost:6006"


def _list_annotation_configs(client: httpx.Client) -> list[dict[str, Any]]:
    r = client.get("/v1/annotation_configs", params={"limit": 100})
    r.raise_for_status()
    return list(r.json().get("data") or [])


def _annotation_configs_spec() -> list[dict[str, Any]]:
    """The two annotation configs we want Phoenix to expose."""
    return [
        {
            "name": "relay_failure_class",
            "type": "CATEGORICAL",
            "description": (
                "Coarse failure class for relay rejections and forwarding errors. "
                "Applied to any erroring `a2a.relay.*` or `a2a.task` span emitted "
                "by the relay. Mirrors the `o2r.relay.failure_class` span attribute, "
                "which the relay sets at emit time so the annotator can confirm or "
                "override."
            ),
            "optimization_direction": "NONE",
            "values": [
                {"label": "topology_violation", "score": None},
                {"label": "peer_disconnect", "score": None},
                {"label": "peer_404", "score": None},
                {"label": "timeout", "score": None},
                {"label": "peer_jsonrpc_error", "score": None},
                {"label": "unknown", "score": None},
            ],
        },
        {
            "name": "task_outcome_correct",
            "type": "CATEGORICAL",
            "description": (
                "Did the session's terminal orchestrator.flow_complete span "
                "match the expected shape (or, more broadly, did the system "
                "do the right thing for this session)? Maximize."
            ),
            "optimization_direction": "MAXIMIZE",
            "values": [
                {"label": "correct", "score": 1.0},
                {"label": "incorrect", "score": 0.0},
            ],
        },
    ]


def ensure_annotation_configs(client: httpx.Client, *, dry_run: bool) -> tuple[int, int]:
    """Create the two annotation configs if missing. Returns (created, existing)."""
    existing = {c["name"]: c for c in _list_annotation_configs(client)}
    created = 0
    skipped = 0
    for spec in _annotation_configs_spec():
        if spec["name"] in existing:
            print(f"  ✓ annotation config {spec['name']!r} already exists")
            skipped += 1
            continue
        print(f"  + would create annotation config {spec['name']!r}")
        if dry_run:
            created += 1
            continue
        r = client.post("/v1/annotation_configs", json=spec)
        if r.status_code >= 400:
            print(
                f"    ✗ create failed: HTTP {r.status_code} {r.text[:200]}",
                file=sys.stderr,
            )
            continue
        created += 1
    return created, skipped


def _list_datasets(client: httpx.Client) -> list[dict[str, Any]]:
    r = client.get("/v1/datasets", params={"limit": 100})
    r.raise_for_status()
    return list(r.json().get("data") or [])


def _golden_seed() -> dict[str, list[dict[str, Any]]]:
    """One worked-example row so the dataset is non-empty on creation.

    The shape is the io contract the issue specifies:
      input  = {from_role, from_id, target_id, target_role, message_text,
                session_id?}
      output = {decision, reason?}

    Real golden rows get added via Phoenix's UI ("Add to dataset" on a
    hand-picked span). This seed exists so the column schema is locked in.
    """
    return {
        "inputs": [
            {
                "from_role": "worker",
                "from_id": "worker-a",
                "target_id": "orchestrator",
                "target_role": "orchestrator",
                "message_text": (
                    "🎨 Designer submitted Built the AURORA design system and hero page: 2 files"
                ),
                "session_id": "luca-aurora-EXAMPLE",
            }
        ],
        "outputs": [
            {
                "decision": "forward",
                "reason": "sender or target is orchestrator; route allowed",
            }
        ],
        "metadata": [
            {
                "kind": "seed",
                "note": (
                    "Hand-shaped example so the dataset's column schema is "
                    "fixed at creation. Replace via UI."
                ),
            }
        ],
    }


def _regression_seed() -> dict[str, list[dict[str, Any]]]:
    """The two known failure spans, encoded with their correct expected output."""
    return {
        "inputs": [
            {
                "from_role": "worker",
                "from_id": "worker-g",
                "target_id": "validator",
                "target_role": "validator",
                "message_text": "🦹 Rogue attempting to bypass the orchestrator: target=validator",
                "session_id": "luca-aurora-EXAMPLE",
            },
            {
                "from_role": "orchestrator",
                "from_id": "orchestrator",
                "target_id": "worker-d",
                "target_role": "worker",
                "message_text": (
                    "🎯 Director dispatching step 4 to worker-d: Drafted the science explainer"
                ),
                "session_id": "luca-aurora-EXAMPLE",
            },
        ],
        "outputs": [
            {
                "decision": "reject",
                "reason": "topology_violation: neither sender nor target is orchestrator",
            },
            {
                "decision": "forward_failed",
                "reason": "peer_disconnect: worker-d crashed mid-handle",
            },
        ],
        "metadata": [
            {"kind": "regression", "failure_class": "topology_violation"},
            {"kind": "regression", "failure_class": "peer_disconnect"},
        ],
    }


def _datasets_spec() -> list[dict[str, Any]]:
    return [
        {
            "name": "relay-decisions-golden",
            "description": (
                "Golden representative examples of relay routing decisions. "
                "Inputs: {from_role, from_id, target_id, target_role, "
                "message_text, session_id?}. Outputs: {decision, reason?}. "
                "Seeded with one worked example; real rows should be added "
                "from real spans via Phoenix's UI."
            ),
            "seed": _golden_seed(),
        },
        {
            "name": "relay-failures-regression",
            "description": (
                "Regression dataset for known relay failure modes. "
                "Initial seed: worker-g topology bypass attempt and worker-d "
                "peer disconnect. Add new failures here as they're triaged."
            ),
            "seed": _regression_seed(),
        },
    ]


def ensure_datasets(client: httpx.Client, *, dry_run: bool) -> tuple[int, int]:
    """Create the two datasets if missing. Returns (created, existing)."""
    existing = {d["name"]: d for d in _list_datasets(client)}
    created = 0
    skipped = 0
    for spec in _datasets_spec():
        if spec["name"] in existing:
            print(f"  ✓ dataset {spec['name']!r} already exists")
            skipped += 1
            continue
        print(f"  + would create dataset {spec['name']!r}")
        if dry_run:
            created += 1
            continue
        body = {
            "action": "create",
            "name": spec["name"],
            "description": spec["description"],
            "inputs": spec["seed"]["inputs"],
            "outputs": spec["seed"]["outputs"],
            "metadata": spec["seed"]["metadata"],
        }
        r = client.post("/v1/datasets/upload", json=body)
        if r.status_code >= 400:
            print(
                f"    ✗ create failed: HTTP {r.status_code} {r.text[:200]}",
                file=sys.stderr,
            )
            continue
        created += 1
    return created, skipped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phoenix", default=DEFAULT_PHOENIX_URL)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing.",
    )
    args = p.parse_args()

    print(f"📡 Phoenix: {args.phoenix} (dry-run={args.dry_run})")

    with httpx.Client(base_url=args.phoenix.rstrip("/"), timeout=10.0) as client:
        try:
            r = client.get("/healthz")
            r.raise_for_status()
        except httpx.HTTPError as e:
            print(f"❌ Phoenix not reachable: {e}", file=sys.stderr)
            return 2

        print()
        print("Annotation configs:")
        ac_created, ac_skipped = ensure_annotation_configs(client, dry_run=args.dry_run)
        print(f"  → created={ac_created}, already-existed={ac_skipped}")

        print()
        print("Datasets:")
        ds_created, ds_skipped = ensure_datasets(client, dry_run=args.dry_run)
        print(f"  → created={ds_created}, already-existed={ds_skipped}")

    print()
    print(
        json.dumps(
            {
                "annotation_configs": ac_created + ac_skipped,
                "datasets": ds_created + ds_skipped,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
