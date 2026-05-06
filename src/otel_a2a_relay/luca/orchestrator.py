"""LUCA orchestrator.

Long-running peer that drives the script. Spawns each worker as a
subprocess, sends dispatch via the relay, collects the response, asks
the validator, retries when allowed, stages accepted deliverables, and
records every routed message for the deployer.

The orchestrator is the only role the star-topology gate lets initiate
arbitrary peer-to-peer routes, which matches its position as the hub.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from otel_a2a_relay.luca.messages import (
    KIND_DISPATCH,
    KIND_FLOW_COMPLETE,
    KIND_PLAN_ENQUEUE,
    KIND_PLAN_NEXT,
    KIND_PLAN_NOTE,
    KIND_SUBMIT_BYPASS_ATTEMPT,
    KIND_SUBMIT_NEEDS_FOLLOWUP,
    KIND_SUBMIT_PASS,
    KIND_VALIDATE_FAIL,
    KIND_VALIDATE_PASS,
    KIND_VALIDATE_REQUEST,
    LucaEnvelope,
    humanize,
    parse_envelope,
)
from otel_a2a_relay.luca.peer import register_with_relay, send_via_relay


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deterministic_context_id(prefix: str) -> str:
    """16-hex-char digest of `<prefix>:<utc-date>`. Stable per day, fresh per day."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    h = hashlib.sha256(f"{prefix}:{today}".encode()).hexdigest()
    return f"{prefix}-{h[:16]}"


@dataclass
class FlowState:
    spec: dict[str, Any]
    script: dict[str, Any]
    relay_url: str
    project_root: Path
    stage_dir: Path
    context_id: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)


def _record(state: FlowState, env: LucaEnvelope, direction: str) -> None:
    state.trace.append(
        {
            "ts_human": _utc_now_iso(),
            "ts_unix": time.time(),
            "direction": direction,  # "out" or "in"
            "sender": env.sender,
            "target": env.target,
            "kind": env.kind,
            "human": env.human,
            "step": env.step,
            "task_id": env.task_id,
            "actor": env.actor,
            "data": env.data,
        }
    )


def _send(state: FlowState, env: LucaEnvelope) -> dict[str, Any]:
    _record(state, env, "out")
    body = send_via_relay(state.relay_url, env, context_id=state.context_id)
    return body


def _parse_reply(body: dict[str, Any]) -> LucaEnvelope | None:
    if "error" in body:
        return None
    result = body.get("result") or {}
    history = result.get("history") or []
    # Reply is the last message in history (the agent's).
    for msg in reversed(history):
        if (msg.get("metadata") or {}).get("agent.id") != "orchestrator":
            return parse_envelope(msg)
    return None


def _wait_healthy(url: str, timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    return False


def _spawn_worker(
    step: dict[str, Any], relay_url: str, *, retry_attempt: int = 0
) -> subprocess.Popen[bytes]:
    """Spawn the worker subprocess with args derived from its script step.

    For submit-fail-then-pass, retry_attempt selects fixtures_first vs fixtures_retry.
    """
    actor = step["actor"]
    behavior = step["behavior"]
    args = [
        "uv",
        "run",
        "python",
        "-m",
        "otel_a2a_relay.luca.worker",
        "--id",
        actor,
        "--port",
        str(step["port"]),
        "--relay",
        relay_url,
        "--display",
        step.get("display", "Worker"),
        "--emoji",
        (step.get("display") or "🛠️").split(" ", 1)[0]
        if " " in (step.get("display") or "")
        else "🛠️",
        "--title",
        step.get("title", ""),
        "--behavior",
        behavior,
    ]

    if behavior == "submit-fail-then-pass":
        # First attempt uses fixtures_first; retry uses fixtures_retry.
        # Both are single-file deliverables in our flow.
        deliverable = step.get("deliverables", ["product.html"])[0]
        if retry_attempt == 0:
            fpath = step["fixtures_first"]
        else:
            fpath = step["fixtures_retry"]
        args += [
            "--fixtures-json",
            json.dumps({deliverable: str(_resolve_fixture(fpath, step))}),
        ]
    elif behavior == "submit-pass":
        fixtures = step.get("fixtures") or {}
        resolved = {k: str(_resolve_fixture(v, step)) for k, v in fixtures.items()}
        args += ["--fixtures-json", json.dumps(resolved)]
        if step.get("strategy"):
            args += ["--strategy", str(step["strategy"])]
    elif behavior == "submit-needs-followup":
        fu = step.get("followup") or {}
        args += [
            "--followup-task",
            str(fu.get("task_id", "")),
            "--followup-assignee",
            str(fu.get("assignee", "")),
            "--followup-reason",
            str(fu.get("reason", "")),
        ]
    elif behavior == "crash-on-receive":
        args += ["--crash-message", step.get("crash_message", "💥 worker crashed")]
    elif behavior == "route-bypass-attempt":
        args += ["--bypass-target", step.get("bypass_target", "validator")]

    log_dir = Path(__file__).resolve().parents[3] / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"luca-{actor}-step{step.get('step', 0)}.log"
    log_f = open(log_path, "a")
    return subprocess.Popen(args, stdout=log_f, stderr=subprocess.STDOUT)


def _resolve_fixture(rel: str, step: dict[str, Any]) -> Path:
    """Fixtures are paths relative to the examples/luca-flow/ root."""
    root_marker = step.get("_root")
    if root_marker is None:
        # the orchestrator stuffs the root into each step before spawn
        raise RuntimeError("step missing _root injection")
    return Path(root_marker) / rel


def _stage_files(stage_dir: Path, deliverables: dict[str, str]) -> list[str]:
    staged: list[str] = []
    for output_path, content in deliverables.items():
        target = stage_dir / output_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        staged.append(output_path)
    return staged


def _send_to_validator(
    state: FlowState,
    step: dict[str, Any],
    deliverables_paths: list[str],
) -> LucaEnvelope | None:
    """Build a validate.request and send it. Returns the parsed reply envelope."""
    # Build page_specs from spec.yaml
    page_specs: dict[str, dict[str, Any]] = {}
    for page in state.spec.get("pages") or []:
        page_specs[f"{page['id']}.html"] = {
            "min_words": page.get("min_words", 0),
            "images_min": page.get("images_min", 1),
            "role": page.get("role", ""),
        }

    deliverables_abs = {p: str(state.stage_dir / p) for p in deliverables_paths}

    all_pages = {f"{page['id']}.html" for page in (state.spec.get("pages") or [])}

    css_spec = (state.spec.get("assets") or {}).get("css") or {}
    css_abs = state.stage_dir / css_spec.get("path", "assets/css/main.css")

    sources_abs = state.project_root / (
        (state.spec.get("assets") or {}).get("images", {}).get("sources_file")
        or "assets/img/nasa/SOURCES.yaml"
    )

    req = LucaEnvelope(
        kind=KIND_VALIDATE_REQUEST,
        human=humanize(
            "🎯",
            "Director",
            f"asking QA to review {step['task_id']}",
            f"{len(deliverables_paths)} files",
        ),
        sender="orchestrator",
        target="validator",
        step=int(step.get("step", 0)),
        task_id=step.get("task_id", ""),
        actor=step.get("actor", ""),
        data={
            "deliverables": deliverables_abs,
            "page_specs": page_specs,
            "sources_yaml": str(sources_abs),
            "css_path": str(css_abs),
            "css_min_bytes": css_spec.get("min_bytes", 1),
            "all_pages": sorted(all_pages),
        },
    )
    body = _send(state, req)
    reply = _parse_reply(body)
    if reply is not None:
        _record(state, reply, "in")
    return reply


def _ask_planner_next(state: FlowState) -> LucaEnvelope | None:
    env = LucaEnvelope(
        kind=KIND_PLAN_NEXT,
        human=humanize("🎯", "Director", "asking PM what's next", ""),
        sender="orchestrator",
        target="planner",
    )
    body = _send(state, env)
    reply = _parse_reply(body)
    if reply is not None:
        _record(state, reply, "in")
    return reply


def _enqueue_followup(state: FlowState, followup_step: dict[str, Any]) -> None:
    env = LucaEnvelope(
        kind=KIND_PLAN_ENQUEUE,
        human=humanize(
            "🎯",
            "Director",
            "telling PM to enqueue follow-up",
            f"{followup_step.get('actor')} - {followup_step.get('task_id')}",
        ),
        sender="orchestrator",
        target="planner",
        data=followup_step,
    )
    body = _send(state, env)
    reply = _parse_reply(body)
    if reply is not None:
        _record(state, reply, "in")


def _note_to_planner(state: FlowState, step: int, msg: str, data: dict[str, Any]) -> None:
    env = LucaEnvelope(
        kind=KIND_PLAN_NOTE,
        human=msg,
        sender="orchestrator",
        target="planner",
        step=step,
        data=data,
    )
    body = _send(state, env)
    reply = _parse_reply(body)
    if reply is not None:
        _record(state, reply, "in")


def _dispatch_worker(
    state: FlowState, step: dict[str, Any], retry_attempt: int = 0
) -> tuple[LucaEnvelope | None, str]:
    """Spawn a worker subprocess, dispatch via relay, return (reply_env, status).

    status is one of: "ok", "crashed", "rejected".
    """
    proc = _spawn_worker(step, state.relay_url, retry_attempt=retry_attempt)
    worker_url = f"http://127.0.0.1:{step['port']}/healthz"
    if not _wait_healthy(worker_url, timeout=10.0):
        proc.terminate()
        return None, "crashed"

    dispatch = LucaEnvelope(
        kind=KIND_DISPATCH,
        human=humanize(
            "🎯",
            "Director",
            f"dispatching step {step.get('step')} to {step.get('actor')}",
            step.get("title", ""),
        ),
        sender="orchestrator",
        target=step["actor"],
        step=int(step.get("step", 0)),
        task_id=step.get("task_id", ""),
        actor=step.get("actor", ""),
        data={"retry_attempt": retry_attempt, "title": step.get("title", "")},
    )
    try:
        body = _send(state, dispatch)
    except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError):
        proc.wait(timeout=2.0)
        return None, "crashed"

    if "error" in body:
        proc.wait(timeout=3.0)
        # JSON-RPC error means the relay's forward to the worker failed (worker
        # crashed mid-handle, or returned non-JSON, or otherwise misbehaved).
        return None, "crashed"

    reply = _parse_reply(body)
    # Wait for worker to finish exiting cleanly so the next step gets a fresh port.
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=2.0)

    if reply is None:
        return None, "crashed"

    _record(state, reply, "in")
    if reply.kind == KIND_SUBMIT_BYPASS_ATTEMPT:
        return reply, "rejected"
    return reply, "ok"


def run_flow(
    *,
    spec_path: Path,
    script_path: Path,
    project_root: Path,
    relay_url: str,
) -> FlowState:
    """Drive the entire LUCA flow. Returns the final state for the deployer."""
    spec = yaml.safe_load(spec_path.read_text())
    script = yaml.safe_load(script_path.read_text())
    session_prefix = (script.get("session") or {}).get("id_prefix", "luca-aurora")
    context_id = _deterministic_context_id(session_prefix)

    stage_dir = project_root / ".luca-stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    state = FlowState(
        spec=spec,
        script=script,
        relay_url=relay_url,
        project_root=project_root,
        stage_dir=stage_dir,
        context_id=context_id,
    )

    # Inject project root into each step so worker spawn can resolve fixtures.
    for s in script.get("steps") or []:
        s["_root"] = str(project_root)

    # Register orchestrator with the relay (placeholder url - nothing dials in).
    register_with_relay(relay_url, "orchestrator", "orchestrator", "http://127.0.0.1:9100/")

    print(f"🎯 Director: starting AURORA flow, context_id={context_id}")

    for step in script.get("steps") or []:
        actor = step["actor"]
        title = step.get("title", "")
        step_num = step.get("step", 0)
        print(f"🎯 Director: step {step_num}: {actor} - {title}")

        # Ask the planner what's next (the planner pops; we use its response
        # for trace richness even though we already know the step locally).
        _ask_planner_next(state)

        if actor == "deployer":
            # Deployer is invoked outside this loop by the runner.
            break

        # Spawn worker, dispatch, collect reply.
        reply, status = _dispatch_worker(state, step)

        outcome: dict[str, Any] = {
            "step": step_num,
            "actor": actor,
            "title": title,
            "emoji": (step.get("display") or "🛠️").split(" ", 1)[0]
            if " " in (step.get("display") or "")
            else "🛠️",
            "outcome": "unknown",
            "notes": [],
        }

        if status == "crashed":
            outcome["outcome"] = "crashed"
            outcome["notes"].append(step.get("crash_message", "worker exited 1"))
            _note_to_planner(
                state, step_num, f"💥 step {step_num} crashed: {actor}", {"reason": "crashed"}
            )
            state.outcomes.append(outcome)
            continue

        assert reply is not None
        if reply.kind == KIND_SUBMIT_BYPASS_ATTEMPT:
            outcome["outcome"] = "rogue-rejected"
            outcome["notes"].append(
                f"Attempted to target {reply.data.get('bypass_target')}; relay rejected: "
                f"{reply.data.get('rejected', False)}"
            )
            _note_to_planner(
                state,
                step_num,
                f"🛑 rogue worker {actor} blocked by relay",
                {"rejected": reply.data.get("rejected")},
            )
            state.outcomes.append(outcome)
            continue

        if reply.kind == KIND_SUBMIT_NEEDS_FOLLOWUP:
            outcome["outcome"] = "needs-followup"
            outcome["notes"].append(
                f"reason: {reply.data.get('reason')}; "
                f"followup task: {reply.data.get('followup_task')} -> "
                f"{reply.data.get('followup_assignee')}"
            )
            # Find the followup step in the script (by task_id) and tell planner.
            fu_task_id = reply.data.get("followup_task") or ""
            fu_step = next(
                (s for s in (script.get("steps") or []) if s.get("task_id") == fu_task_id),
                None,
            )
            if fu_step is not None:
                _enqueue_followup(state, fu_step)
            state.outcomes.append(outcome)
            continue

        if reply.kind == KIND_SUBMIT_PASS:
            # Stage the worker's output to disk so the validator can read it.
            staged = _stage_files(stage_dir, reply.data.get("deliverables") or {})
            html_pages = [p for p in staged if p.endswith(".html")]
            if not html_pages:
                # CSS-only or other non-HTML deliverable; treat as accepted.
                outcome["outcome"] = "accepted"
                outcome["notes"].append(f"staged non-html: {staged}")
                state.outcomes.append(outcome)
                continue

            # Send to validator.
            verdict = _send_to_validator(state, step, html_pages)
            if verdict is None:
                outcome["outcome"] = "crashed"
                outcome["notes"].append("validator did not respond")
                state.outcomes.append(outcome)
                continue

            if verdict.kind == KIND_VALIDATE_PASS:
                outcome["outcome"] = "accepted"
                outcome["notes"].extend(
                    f"check: {c}" for c in (verdict.data.get("checks") or [])[:5]
                )
                state.outcomes.append(outcome)
                continue

            if verdict.kind == KIND_VALIDATE_FAIL:
                # Retry?
                if step.get("behavior") == "submit-fail-then-pass":
                    retry_max = int(step.get("retry_max", 1))
                    if retry_max >= 1:
                        outcome["notes"].append(
                            f"first attempt rejected: {verdict.data.get('errors', [''])[0]}"
                        )
                        _note_to_planner(
                            state,
                            step_num,
                            f"🔁 step {step_num} re-dispatching to {actor}",
                            {"reason": "validation-fail"},
                        )
                        # Re-dispatch with retry fixture.
                        reply2, status2 = _dispatch_worker(state, step, retry_attempt=1)
                        if status2 != "ok" or reply2 is None or reply2.kind != KIND_SUBMIT_PASS:
                            outcome["outcome"] = "crashed"
                            outcome["notes"].append("retry did not produce a submission")
                            state.outcomes.append(outcome)
                            continue
                        staged2 = _stage_files(stage_dir, reply2.data.get("deliverables") or {})
                        verdict2 = _send_to_validator(
                            state, step, [p for p in staged2 if p.endswith(".html")]
                        )
                        if verdict2 is not None and verdict2.kind == KIND_VALIDATE_PASS:
                            outcome["outcome"] = "accepted"
                            outcome["notes"].append("retry passed")
                            state.outcomes.append(outcome)
                            continue
                        outcome["outcome"] = "crashed"
                        outcome["notes"].append("retry also rejected")
                        state.outcomes.append(outcome)
                        continue
                outcome["outcome"] = "crashed"
                outcome["notes"].append(
                    f"validator rejected: {verdict.data.get('errors', [''])[0]}"
                )
                state.outcomes.append(outcome)
                continue

        outcome["outcome"] = "unknown"
        outcome["notes"].append(f"unhandled reply kind: {reply.kind}")
        state.outcomes.append(outcome)

    # Final flow-complete envelope (informational, sent to planner so it lands in trace).
    _note_to_planner(
        state,
        step=0,
        msg=humanize(
            "🎯",
            "Director",
            "all script steps complete - handing off to release",
            f"accepted={sum(1 for o in state.outcomes if o['outcome'] == 'accepted')}",
        ),
        data={"kind": KIND_FLOW_COMPLETE},
    )

    # Persist trace + outcomes for the deployer.
    (stage_dir / "_trace.json").write_text(json.dumps(state.trace, indent=2))
    (stage_dir / "_outcomes.json").write_text(json.dumps(state.outcomes, indent=2))

    return state


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    p.add_argument("--relay", default="http://127.0.0.1:8080/")
    args = p.parse_args()
    root = Path(args.root)
    state = run_flow(
        spec_path=root / "spec.yaml",
        script_path=root / "script.yaml",
        project_root=root,
        relay_url=args.relay,
    )
    accepted = sum(1 for o in state.outcomes if o["outcome"] == "accepted")
    crashed = sum(1 for o in state.outcomes if o["outcome"] == "crashed")
    needs_followup = sum(1 for o in state.outcomes if o["outcome"] == "needs-followup")
    rogue = sum(1 for o in state.outcomes if o["outcome"] == "rogue-rejected")
    print(
        f"🎯 Director: flow complete - accepted={accepted}, "
        f"needs-followup={needs_followup}, crashed={crashed}, rogue-rejected={rogue}"
    )


if __name__ == "__main__":
    # uuid is imported above; satisfy linters that flag unused imports.
    _ = uuid
    main()
