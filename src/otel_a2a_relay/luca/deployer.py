"""LUCA deployer.

Subprocess invoked by the runner after the orchestrator finishes. Reads
the staged worker output + the trace log + the SOURCES.yaml, and produces:

  dist/<page>.html       (copies of staged accepted deliverables)
  dist/assets/...        (css, fonts, NASA imagery)
  dist/CITATIONS.html    (rendered from CITATIONS.md + SOURCES.yaml)
  dist/CHANGELOG.md      (one entry per accepted task, chronological)
  dist/delivery-report.md
  dist/delivery-report.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from otel_a2a_relay.luca._clock import now_iso as _utc_now


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def render_changelog(outcomes: list[dict[str, Any]], project: dict[str, Any]) -> str:
    """Customer-facing changelog. One entry per accepted task. Humanized lines only."""
    lines = [
        f"# {project.get('codename', 'AURORA')} changelog",
        "",
        f"_Generated {_utc_now()} by the LUCA-flow deployer._",
        "",
        (
            f"This first release of the **{project.get('codename', 'AURORA')}** site composes "
            "the work of every contributor in order. The following items shipped:"
        ),
        "",
    ]
    for o in outcomes:
        if o.get("outcome") == "accepted":
            lines.append(f"- {o.get('emoji', '✅')} {o.get('title', '')}")
    lines.extend(
        [
            "",
            "---",
            "",
            f"Contact: {project.get('brand', 'Vent Atelier')}, {project.get('city', '')}.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_delivery_report_md(
    *,
    trace: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    project: dict[str, Any],
    started_at: str,
    finished_at: str,
) -> str:
    """System-level humanized report. Every message in chronological order."""
    lines = [
        f"# {project.get('codename', 'AURORA')} - LUCA-flow delivery report",
        "",
        f"- Run started: `{started_at}`",
        f"- Run finished: `{finished_at}`",
        f"- Trace events: **{len(trace)}**",
        f"- Outcomes recorded: **{len(outcomes)}**",
        "",
        "## Outcomes summary",
        "",
    ]
    for o in outcomes:
        marker = {
            "accepted": "✅",
            "needs-followup": "🔁",
            "crashed": "💥",
            "rogue-rejected": "🛑",
        }.get(o.get("outcome", ""), "·")
        lines.append(
            f"- {marker} step {o.get('step')}: {o.get('actor')} - {o.get('title', '')}"
            f"  ({o.get('outcome')})"
        )
        if o.get("notes"):
            for note in o["notes"]:
                lines.append(f"  - {note}")

    lines.extend(["", "## Full system message log", "", "Every routed message, in order:", ""])
    for ev in trace:
        ts = ev.get("ts_human", "")
        human = ev.get("human", "")
        sender = ev.get("sender", "")
        target = ev.get("target", "")
        kind = ev.get("kind", "")
        lines.append(f"- `{ts}` {sender} → {target} *({kind})* - {human}")
    lines.extend(
        [
            "",
            "---",
            "",
            "Machine-readable variant of this report lives at `delivery-report.json` alongside.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_citations_html(citations_md: str, sources: list[dict[str, Any]]) -> str:
    """Minimal HTML wrapper around the citations content + the SOURCES table."""
    rows = []
    for s in sources:
        rows.append(
            f"      <tr>"
            f"<td><code>{s.get('nasa_id', '')}</code></td>"
            f"<td>{s.get('title', '')}</td>"
            f"<td>{s.get('credit', 'NASA')}</td>"
            f"<td><a href='{s.get('source_metadata_url', '')}'>source</a></td>"
            f"</tr>"
        )

    body_html = citations_md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Citations - AURORA</title>
  <link rel="stylesheet" href="assets/css/main.css">
</head>
<body>
  <header class="nav">
    <a class="brand" href="index.html">AURORA</a>
    <a href="science.html">Science</a>
    <a href="product.html">Product</a>
    <a href="gallery.html">Gallery</a>
    <a href="mission.html">Mission</a>
    <a href="about.html">About</a>
    <a href="preorder.html">Pre-order</a>
  </header>
  <section class="page-hero">
    <div class="wrap">
      <p class="kicker">Citations · NASA imagery</p>
      <h1>Image and source citations</h1>
      <p class="muted">
        Every photograph and visualization on this site is a NASA public-domain work.
        Below is the per-image source list, rendered live from
        <code>assets/img/nasa/SOURCES.yaml</code>.
      </p>
    </div>
  </section>
  <article class="prose">
    <table class="spec-table">
      <tr><th>NASA ID</th><th>Title</th><th>Credit</th><th>Source</th></tr>
{chr(10).join(rows)}
    </table>
    <h2>Long-form attribution</h2>
    <pre class="citations-md">
{body_html}
    </pre>
  </article>
  <footer class="footer">
    <p>Imagery courtesy NASA, public domain.</p>
    <p>© 2026 Vent Atelier · Hayward, California</p>
  </footer>
</body>
</html>
"""


def deploy(
    *,
    project_root: Path,
    stage_dir: Path,
    assets_dir: Path,
    citations_md_path: Path,
    sources_yaml_path: Path,
    spec_path: Path,
    dist_dir: Path,
) -> dict[str, Any]:
    """Assemble dist/ from staged worker outputs + shared assets. Pure-ish."""
    spec = yaml.safe_load(spec_path.read_text())
    project = spec.get("project") or {}

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    # Copy shared assets (CSS lives in stage_dir already; img + fonts come from repo).
    (dist_dir / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copytree(assets_dir / "img", dist_dir / "assets" / "img")
    shutil.copytree(assets_dir / "fonts", dist_dir / "assets" / "fonts")

    # CSS from stage if present; else fall back to fixture (for completeness).
    staged_css = stage_dir / "assets" / "css" / "main.css"
    dist_css_dir = dist_dir / "assets" / "css"
    dist_css_dir.mkdir(parents=True, exist_ok=True)
    if staged_css.exists():
        shutil.copy2(staged_css, dist_css_dir / "main.css")

    # Pages from stage. Copy each .html that landed there.
    pages_copied: list[str] = []
    for page in stage_dir.glob("*.html"):
        shutil.copy2(page, dist_dir / page.name)
        pages_copied.append(page.name)

    # CITATIONS.html
    sources = (yaml.safe_load(sources_yaml_path.read_text()) or {}).get("images") or []
    citations_html = render_citations_html(citations_md_path.read_text(), sources)
    (dist_dir / "CITATIONS.html").write_text(citations_html)
    # Also drop the source CITATIONS.md alongside.
    shutil.copy2(citations_md_path, dist_dir / "CITATIONS.md")

    # Trace + outcomes from stage.
    trace_path = stage_dir / "_trace.json"
    outcomes_path = stage_dir / "_outcomes.json"
    trace = _read_json(trace_path) if trace_path.exists() else []
    outcomes = _read_json(outcomes_path) if outcomes_path.exists() else []
    started_at = trace[0]["ts_human"] if trace else _utc_now()
    finished_at = trace[-1]["ts_human"] if trace else _utc_now()

    changelog = render_changelog(outcomes, project)
    (dist_dir / "CHANGELOG.md").write_text(changelog)

    report_md = render_delivery_report_md(
        trace=trace,
        outcomes=outcomes,
        project=project,
        started_at=started_at,
        finished_at=finished_at,
    )
    (dist_dir / "delivery-report.md").write_text(report_md)
    (dist_dir / "delivery-report.json").write_text(
        json.dumps(
            {
                "project": project,
                "started_at": started_at,
                "finished_at": finished_at,
                "trace": trace,
                "outcomes": outcomes,
                "pages_copied": pages_copied,
            },
            indent=2,
        )
    )

    return {
        "dist_dir": str(dist_dir),
        "pages": pages_copied,
        "outcomes_count": len(outcomes),
        "trace_count": len(trace),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, help="examples/luca-flow/ root")
    args = p.parse_args()
    root = Path(args.root)
    result = deploy(
        project_root=root,
        stage_dir=root / ".luca-stage",
        assets_dir=root / "assets",
        citations_md_path=root / "CITATIONS.md",
        sources_yaml_path=root / "assets" / "img" / "nasa" / "SOURCES.yaml",
        spec_path=root / "spec.yaml",
        dist_dir=root / "dist",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
