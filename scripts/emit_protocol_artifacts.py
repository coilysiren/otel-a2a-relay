#!/usr/bin/env python3
"""Emit machine artifacts from docs/protocol.md.

The protocol doc carries a fenced ```yaml block tagged `# o2r-attributes`
that lists the canonical span attributes. This script parses that block
and writes:

- docs/generated/o2r-attributes.schema.json - JSON Schema describing
  the attribute set. Useful as a contract for span-validating tooling.
- docs/generated/o2r-semconv.yaml - OTel-semantic-conventions-shaped
  YAML so downstream OTel tooling can consume the same names.

Doc is the source of truth. Run after editing the attribute block.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

DOC = pathlib.Path("docs/protocol.md")
OUT_DIR = pathlib.Path("docs/generated")
SCHEMA_OUT = OUT_DIR / "o2r-attributes.schema.json"
SEMCONV_OUT = OUT_DIR / "o2r-semconv.yaml"

REQUIREMENT_VALUES = {"required", "recommended", "optional"}


def extract_attributes(doc_text: str) -> list[dict[str, object]]:
    """Find the fenced yaml block tagged `# o2r-attributes` and parse it."""
    pattern = re.compile(
        r"```yaml\s*\n#\s*o2r-attributes\s*\n(.*?)\n```",
        re.DOTALL,
    )
    m = pattern.search(doc_text)
    if not m:
        raise SystemExit("docs/protocol.md missing the o2r-attributes yaml block")
    parsed = yaml.safe_load(m.group(1))
    attrs = parsed.get("attributes")
    if not isinstance(attrs, list):
        raise SystemExit("o2r-attributes block must contain a list under `attributes`")
    return attrs


def validate(attrs: list[dict[str, object]]) -> None:
    for a in attrs:
        for key in ("id", "type", "requirement", "brief"):
            if key not in a:
                raise SystemExit(f"attribute {a!r} missing required key {key}")
        if a["requirement"] not in REQUIREMENT_VALUES:
            raise SystemExit(
                f"attribute {a['id']} has invalid requirement {a['requirement']!r}; "
                f"expected one of {sorted(REQUIREMENT_VALUES)}"
            )


def render_schema(attrs: list[dict[str, object]]) -> dict[str, object]:
    properties = {}
    required = []
    for a in attrs:
        prop = {"type": a["type"], "description": a["brief"]}
        if "enum" in a:
            prop["enum"] = a["enum"]
        properties[a["id"]] = prop
        if a["requirement"] == "required":
            required.append(a["id"])
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://coilysiren.me/otel-a2a-relay/o2r-attributes.schema.json",
        "title": "o2r span attribute registry",
        "description": "Generated from docs/protocol.md. Do not hand-edit.",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


def render_semconv(attrs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "groups": [
            {
                "id": "registry.o2r",
                "type": "attribute_group",
                "brief": "o2r span attribute registry. Generated from docs/protocol.md.",
                "attributes": [
                    {
                        "id": a["id"],
                        "type": a["type"],
                        "requirement_level": a["requirement"],
                        "brief": a["brief"],
                        **({"members": a["enum"]} if "enum" in a else {}),
                    }
                    for a in attrs
                ],
            }
        ]
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".", help="repo root (default: cwd)")
    p.add_argument("--check", action="store_true", help="exit 1 if outputs would change")
    args = p.parse_args()

    root = pathlib.Path(args.repo_root).resolve()
    doc_path = root / DOC
    if not doc_path.exists():
        print(f"missing {doc_path}", file=sys.stderr)
        return 2

    attrs = extract_attributes(doc_path.read_text())
    validate(attrs)

    schema = render_schema(attrs)
    semconv = render_semconv(attrs)

    schema_str = json.dumps(schema, indent=2, sort_keys=False) + "\n"
    semconv_str = yaml.safe_dump(semconv, sort_keys=False)

    schema_path = root / SCHEMA_OUT
    semconv_path = root / SEMCONV_OUT

    if args.check:
        existing_schema = schema_path.read_text() if schema_path.exists() else ""
        existing_semconv = semconv_path.read_text() if semconv_path.exists() else ""
        if existing_schema != schema_str or existing_semconv != semconv_str:
            print(
                "generated protocol artifacts are stale - regenerate with"
                " `make protocol-artifacts`",
                file=sys.stderr,
            )
            return 1
        return 0

    (root / OUT_DIR).mkdir(parents=True, exist_ok=True)
    schema_path.write_text(schema_str)
    semconv_path.write_text(semconv_str)
    print(f"wrote {SCHEMA_OUT} and {SEMCONV_OUT} ({len(attrs)} attributes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
