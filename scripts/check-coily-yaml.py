#!/usr/bin/env python3
"""Enforce that every `.coily/coily.yaml` command's `run` is `make <verb>`.

Rationale: coily delegates to make so the recipe lives in one place. Bare
`uv run ...` in `coily.yaml` re-encodes the recipe and the two surfaces
drift. Mismatched names mean `coily exec foo` and `make foo` do different
things, which is bad for muscle memory and worse for audit trails.

Tracks coilysiren/coily#116. Remove once that hook ships.
"""

from __future__ import annotations

import pathlib
import sys

import yaml


def main() -> int:
    path = pathlib.Path(".coily/coily.yaml")
    if not path.exists():
        return 0

    data = yaml.safe_load(path.read_text()) or {}
    commands = data.get("commands") or {}

    errors: list[str] = []
    for verb, spec in commands.items():
        run = (spec or {}).get("run", "")
        expected = f"make {verb}"
        if run != expected:
            errors.append(f"  {verb}: run is {run!r}, expected {expected!r}")

    if errors:
        print(f"{path}: command names must match make targets:", file=sys.stderr)
        for line in errors:
            print(line, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
