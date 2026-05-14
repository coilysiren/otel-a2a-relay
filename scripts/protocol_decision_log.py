#!/usr/bin/env python3
"""Generate docs/protocol-decisions.md from docs/protocol.md git blame.

For each `## Section` in docs/protocol.md, walk git blame on the section's
lines, collect distinct commits, and emit a chronological decision log.

Run from the repo root (or pass --repo-root). Writes
docs/protocol-decisions.md and is safe to commit.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

DOC = pathlib.Path("docs/protocol.md")
OUT = pathlib.Path("docs/protocol-decisions.md")


def section_ranges(doc_lines: list[str]) -> list[tuple[str, int, int]]:
    """Return [(heading, start_line, end_line)] for each top-level `## ` section.

    Line numbers are 1-indexed and inclusive on both ends.
    """
    headings = [
        (i + 1, line[3:].rstrip()) for i, line in enumerate(doc_lines) if line.startswith("## ")
    ]
    out = []
    for idx, (start, heading) in enumerate(headings):
        end = headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(doc_lines)
        out.append((heading, start, end))
    return out


def blame_commits(start: int, end: int) -> list[tuple[str, int, str, str]]:
    """Return [(sha, unix_ts, author_date_iso, subject)] for distinct commits
    touching the inclusive line range, sorted oldest first.
    """
    res = subprocess.run(
        ["git", "blame", "--line-porcelain", "-L", f"{start},{end}", str(DOC)],
        check=True,
        capture_output=True,
        text=True,
    )
    shas = []
    seen: set[str] = set()
    for line in res.stdout.splitlines():
        m = re.match(r"^([0-9a-f]{40}) ", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            shas.append(m.group(1))
    out = []
    for sha in shas:
        meta = subprocess.run(
            ["git", "show", "-s", "--format=%at%x1f%aI%x1f%s", sha],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        ts_str, iso, subject = meta.split("\x1f", 2)
        out.append((sha, int(ts_str), iso, subject))
    out.sort(key=lambda r: r[1])
    return out


def render(sections: list[tuple[str, int, int]]) -> str:
    lines = [
        "# Protocol decision log",
        "",
        "Auto-generated from `git blame` on `docs/protocol.md`."
        " Do not hand-edit. Regenerate with `make protocol-decisions`.",
        "",
        "Each section lists the commits that have shaped its current text, oldest first.",
        "",
    ]
    for heading, start, end in sections:
        lines.append(f"## {heading}")
        lines.append("")
        commits = blame_commits(start, end)
        if not commits:
            lines.append("_No blame data._")
            lines.append("")
            continue
        for sha, _, iso, subject in commits:
            date = iso[:10]
            short = sha[:8]
            lines.append(f"- `{short}` {date} - {subject}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", default=".", help="repo root (default: cwd)")
    p.add_argument("--check", action="store_true", help="exit 1 if output would change")
    args = p.parse_args()

    root = pathlib.Path(args.repo_root).resolve()
    doc_path = root / DOC
    out_path = root / OUT
    if not doc_path.exists():
        print(f"missing {doc_path}", file=sys.stderr)
        return 2

    doc_lines = doc_path.read_text().splitlines()
    sections = section_ranges(doc_lines)
    rendered = render(sections)

    if args.check:
        existing = out_path.read_text() if out_path.exists() else ""
        if existing != rendered:
            print(f"{OUT} is stale - regenerate with make protocol-decisions", file=sys.stderr)
            return 1
        return 0

    out_path.write_text(rendered)
    print(f"wrote {OUT} ({len(sections)} sections)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
