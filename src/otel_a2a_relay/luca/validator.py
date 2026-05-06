"""LUCA validator.

Real HTML / CSS / citation checks against submitted deliverables. Pure
executor of validation, talks only to the orchestrator.

The orchestrator sends a `validate.request` whose data carries:
  - task_id
  - deliverables: { "<output_path>": "<staged absolute path>" }
  - page_specs: per-deliverable {min_words, images_min, role}
  - sources_yaml: absolute path to NASA SOURCES.yaml
  - citations_md: absolute path to CITATIONS.md
  - css_path / css_min_bytes (for asset checks)
  - all_pages: list of internal page filenames the validator should require
    to resolve from each submitted page's nav

Returns `validate.pass` with checks=[...] or `validate.fail` with
errors=[...].
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import html5lib
import uvicorn
import yaml

from otel_a2a_relay.luca.messages import (
    KIND_VALIDATE_FAIL,
    KIND_VALIDATE_PASS,
    KIND_VALIDATE_REQUEST,
    LucaEnvelope,
    humanize,
)
from otel_a2a_relay.luca.peer import (
    create_peer_app,
    deregister_from_relay,
    register_with_relay,
)


def _walk(node: Any) -> Any:
    yield node
    for child in getattr(node, "childNodes", []) or []:
        yield from _walk(child)


def _tag(node: Any) -> str:
    return (getattr(node, "tagName", "") or "").lower().split("}")[-1]


def _attr(node: Any, name: str) -> str | None:
    a = getattr(node, "attributes", None)
    if a is None:
        return None
    try:
        item = a.get(name)
        if item is None:
            return None
        if hasattr(item, "value"):
            return item.value  # type: ignore[no-any-return]
        return str(item)
    except Exception:
        return None


def _text_content(node: Any) -> str:
    out: list[str] = []
    for n in _walk(node):
        if getattr(n, "nodeType", 0) == 3:  # TEXT_NODE
            out.append(getattr(n, "data", "") or "")
    return " ".join(out)


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def validate_one_page(
    *,
    page_name: str,
    html_text: str,
    spec: dict[str, Any],
    nasa_ids: set[str],
    all_pages: set[str],
) -> list[str]:
    """Return a list of error strings; empty means pass."""
    errors: list[str] = []
    try:
        tree = html5lib.parse(html_text, treebuilder="dom")
    except Exception as e:
        errors.append(f"{page_name}: html5lib parse failure: {e}")
        return errors

    h1s = [n for n in _walk(tree) if _tag(n) == "h1"]
    if len(h1s) != 1:
        errors.append(f"{page_name}: exactly one `<h1>` required, found {len(h1s)}")

    imgs = [n for n in _walk(tree) if _tag(n) == "img"]
    if len(imgs) < int(spec.get("images_min", 1)):
        errors.append(
            f"{page_name}: spec requires images_min={spec.get('images_min')}, found {len(imgs)}"
        )
    for i, img in enumerate(imgs):
        alt = _attr(img, "alt")
        if not alt or not alt.strip():
            errors.append(f"{page_name}: `<img>[{i}]` missing alt text")
        nasa_id = _attr(img, "data-nasa-id")
        if not nasa_id:
            errors.append(f"{page_name}: `<img>[{i}]` missing data-nasa-id citation reference")
        elif nasa_id not in nasa_ids:
            errors.append(f"{page_name}: `<img>[{i}]` data-nasa-id={nasa_id!r} not in SOURCES.yaml")

    scripts = [n for n in _walk(tree) if _tag(n) == "script"]
    for s in scripts:
        src = _attr(s, "src") or ""
        if src:
            errors.append(f"{page_name}: external `<script src={src!r}>` not allowed")

    body_text = _text_content(tree)
    wc = _word_count(body_text)
    if wc < int(spec.get("min_words", 0)):
        errors.append(f"{page_name}: word count {wc} below min_words={spec.get('min_words')}")

    # Internal nav: every <a href> ending in .html must point at a known page.
    for a in [n for n in _walk(tree) if _tag(n) == "a"]:
        href = _attr(a, "href") or ""
        if not href:
            continue
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if href.endswith(".html"):
            base = href.split("/")[-1]
            if base not in all_pages and base != "CITATIONS.html":
                errors.append(f"{page_name}: nav link to unknown page {href!r}")

    # Page-level CDN smell-test: any rel='stylesheet' must be local-relative.
    for link in [n for n in _walk(tree) if _tag(n) == "link"]:
        rel = (_attr(link, "rel") or "").lower()
        href = _attr(link, "href") or ""
        if "stylesheet" in rel and href.startswith(("http://", "https://", "//")):
            errors.append(f"{page_name}: external stylesheet {href!r} not allowed")

    return errors


def validate_submission(req: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """Run all checks for one submission. Returns (passed, errors, checks_run)."""
    deliverables: dict[str, str] = req.get("deliverables") or {}
    page_specs: dict[str, dict[str, Any]] = req.get("page_specs") or {}
    sources_yaml = req.get("sources_yaml")
    css_path = req.get("css_path")
    css_min_bytes = int(req.get("css_min_bytes", 1))
    all_pages = set(req.get("all_pages") or [])

    errors: list[str] = []
    checks: list[str] = []

    nasa_ids: set[str] = set()
    if sources_yaml and Path(sources_yaml).exists():
        with open(sources_yaml) as f:
            doc = yaml.safe_load(f) or {}
        nasa_ids = {img.get("nasa_id") for img in (doc.get("images") or []) if img.get("nasa_id")}
        checks.append(f"loaded {len(nasa_ids)} NASA ids from SOURCES.yaml")
    else:
        errors.append(f"SOURCES.yaml not found at {sources_yaml!r}")

    if css_path:
        p = Path(css_path)
        if not p.exists():
            errors.append(f"css file missing: {css_path}")
        elif p.stat().st_size < css_min_bytes:
            errors.append(f"css {css_path} size {p.stat().st_size} below min_bytes={css_min_bytes}")
        else:
            checks.append(f"css {p.name} present, {p.stat().st_size} bytes")

    for page_name, abs_path in deliverables.items():
        if not page_name.endswith(".html"):
            checks.append(f"non-html deliverable {page_name} skipped at page-validate stage")
            continue
        path = Path(abs_path)
        if not path.exists():
            errors.append(f"deliverable {page_name} missing at {abs_path}")
            continue
        spec = page_specs.get(page_name, {})
        page_errors = validate_one_page(
            page_name=page_name,
            html_text=path.read_text(),
            spec=spec,
            nasa_ids=nasa_ids,
            all_pages=all_pages,
        )
        if page_errors:
            errors.extend(page_errors)
        else:
            checks.append(
                f"{page_name}: ok (h1=1, imgs ok, words≥{spec.get('min_words', 0)}, nav resolves)"
            )

    return (not errors, errors, checks)


def make_handler() -> Any:
    def handle(env: LucaEnvelope, _msg: dict[str, Any]) -> LucaEnvelope:
        if env.kind != KIND_VALIDATE_REQUEST:
            return LucaEnvelope(
                kind="validate.unknown",
                human=humanize("🔍", "QA", "did not understand", env.kind),
                sender="validator",
                target=env.sender,
            )
        passed, errors, checks = validate_submission(env.data)
        if passed:
            return LucaEnvelope(
                kind=KIND_VALIDATE_PASS,
                human=humanize(
                    "🔍", "QA", f"approved {env.task_id}", f"{len(checks)} checks passed"
                ),
                sender="validator",
                target=env.sender,
                step=env.step,
                task_id=env.task_id,
                actor=env.actor,
                data={"checks": checks},
            )
        return LucaEnvelope(
            kind=KIND_VALIDATE_FAIL,
            human=humanize(
                "🔍",
                "QA",
                f"rejected {env.task_id}",
                f"{len(errors)} issues - first: {errors[0]}",
            ),
            sender="validator",
            target=env.sender,
            step=env.step,
            task_id=env.task_id,
            actor=env.actor,
            data={"errors": errors, "checks": checks},
        )

    return handle


def build_app(base_url: str) -> Any:
    return create_peer_app(
        agent_id="validator",
        role="validator",
        base_url=base_url,
        handler=make_handler(),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=9102)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--relay", default="http://127.0.0.1:8080")
    args = p.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    app = build_app(base_url)
    register_with_relay(args.relay, "validator", "validator", base_url)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    finally:
        deregister_from_relay(args.relay, "validator")


if __name__ == "__main__":
    main()
