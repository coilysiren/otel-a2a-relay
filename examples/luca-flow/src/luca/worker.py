"""LUCA worker.

Transient. Each worker is spawned by the orchestrator with a `behavior`
flag that tells it what to do when it gets dispatched. Behavior matrix:

  submit-pass          : read fixture(s), respond with submit.pass
  submit-needs-followup: respond with submit.needs-followup, no fixture
                         attached (the followup task carries its own
                         fixture in script.yaml)
  submit-fail-then-pass: respond with submit.pass; the validator's
                         decision is what differs between attempt 1 and 2.
                         Orchestrator passes a different fixture path on
                         the retry, so attempt 1 lands the broken file
                         (no h1) and attempt 2 lands the fixed file.
  crash-on-receive     : exit 1 immediately on receipt of dispatch (the
                         orchestrator sees a connection drop)
  route-bypass-attempt : try to message a non-orchestrator peer directly,
                         expect 403 from the relay, respond with
                         submit.bypass-attempt and exit non-zero

Workers register themselves with the relay before the orchestrator
dispatches, and deregister after responding.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from luca.messages import (
    KIND_DISPATCH,
    KIND_SUBMIT_BYPASS_ATTEMPT,
    KIND_SUBMIT_NEEDS_FOLLOWUP,
    KIND_SUBMIT_PASS,
    LucaEnvelope,
    humanize,
)
from luca.peer import (
    create_peer_app,
    deregister_from_relay,
    register_with_relay,
    send_via_relay,
)


def _read_fixtures(fixture_paths: dict[str, str]) -> dict[str, str]:
    """Read each fixture from disk into a dict keyed by output path."""
    out: dict[str, str] = {}
    for output_path, fixture_path in fixture_paths.items():
        out[output_path] = Path(fixture_path).read_text()
    return out


def _shutdown_after(delay: float = 1.0, code: int = 0) -> None:
    """Schedule process exit so the response can flush before we go away."""

    def _bye() -> None:
        time.sleep(delay)
        os._exit(code)

    threading.Thread(target=_bye, daemon=True).start()


def _crash(message: str) -> None:
    print(f"WORKER CRASH: {message}", file=sys.stderr, flush=True)
    os._exit(1)


def do_boot_actions(args: argparse.Namespace) -> dict[str, Any]:
    """Pre-handler actions. For the rogue worker, this is the bypass attempt.

    Doing the bypass at boot (not inside the dispatch handler) avoids making
    nested HTTP calls inside an active FastAPI request.
    """
    state: dict[str, Any] = {}
    if args.behavior == "route-bypass-attempt":
        print(
            f"WORKER-G: boot-time bypass attempt -> {args.bypass_target}",
            flush=True,
        )
        bypass_env = LucaEnvelope(
            kind="worker.bypass-poke",
            human=humanize(
                "🦹",
                args.display,
                "attempting to bypass the orchestrator",
                f"target={args.bypass_target}",
            ),
            sender=args.id,
            target=args.bypass_target,
            actor=args.id,
        )
        relay_response = send_via_relay(
            args.relay.rstrip("/") + "/",
            bypass_env,
            context_id="luca-rogue-bootstrap",
        )
        rejected = "error" in relay_response and (
            relay_response.get("error", {}).get("code") == -32010
        )
        print(f"WORKER-G: rejected={rejected}", flush=True)
        state["bypass_response"] = relay_response
        state["bypass_rejected"] = rejected
    return state


def make_handler(args: argparse.Namespace, boot_state: dict[str, Any]) -> Any:
    """Build the dispatch handler keyed off the worker's --behavior flag."""
    display = args.display

    def handle(env: LucaEnvelope, _msg: dict[str, Any]) -> LucaEnvelope:
        if env.kind != KIND_DISPATCH:
            return LucaEnvelope(
                kind="worker.unknown",
                human=humanize("⚠️", display, "did not understand", env.kind),
                sender=args.id,
                target=env.sender,
            )

        if args.behavior == "crash-on-receive":
            print(args.crash_message, flush=True)
            _crash(args.crash_message)

        if args.behavior == "route-bypass-attempt":
            rejected = bool(boot_state.get("bypass_rejected"))
            reply = LucaEnvelope(
                kind=KIND_SUBMIT_BYPASS_ATTEMPT,
                human=humanize(
                    "🦹",
                    display,
                    "tried to bypass the orchestrator",
                    "relay rejected (as expected)" if rejected else "relay let it through!",
                ),
                sender=args.id,
                target=env.sender,
                step=env.step,
                task_id=env.task_id,
                actor=args.id,
                data={
                    "bypass_target": args.bypass_target,
                    "rejected": rejected,
                    "relay_response": boot_state.get("bypass_response"),
                },
            )
            # Exit non-zero after responding so the orchestrator's view of the
            # rogue worker is "did the bad thing, then went away." The reply
            # is returned first; the schedule below kills the process after.
            _shutdown_after(code=1 if rejected else 0)
            return reply

        if args.behavior == "submit-needs-followup":
            reply = LucaEnvelope(
                kind=KIND_SUBMIT_NEEDS_FOLLOWUP,
                human=humanize(
                    "🖼️",
                    display,
                    "submitted partial draft - needs follow-up",
                    args.followup_reason or "too large for one shot",
                ),
                sender=args.id,
                target=env.sender,
                step=env.step,
                task_id=env.task_id,
                actor=args.id,
                data={
                    "followup_task": args.followup_task,
                    "followup_assignee": args.followup_assignee,
                    "reason": args.followup_reason,
                },
            )
            _shutdown_after()
            return reply

        # submit-pass and submit-fail-then-pass both submit a fixture set;
        # the difference is which fixture path the orchestrator passed in.
        fixtures: dict[str, str] = json.loads(args.fixtures_json)
        contents = _read_fixtures(fixtures)
        reply = LucaEnvelope(
            kind=KIND_SUBMIT_PASS,
            human=humanize(
                args.emoji,
                display,
                f"submitted {args.title}",
                f"{len(contents)} files",
            ),
            sender=args.id,
            target=env.sender,
            step=env.step,
            task_id=env.task_id,
            actor=args.id,
            data={"deliverables": contents, "strategy": args.strategy or ""},
        )
        _shutdown_after()
        return reply

    return handle


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--relay", default="http://127.0.0.1:8080")
    p.add_argument("--display", default="Worker")
    p.add_argument("--emoji", default="🛠️")
    p.add_argument("--title", default="work unit")
    p.add_argument(
        "--behavior",
        required=True,
        choices=[
            "submit-pass",
            "submit-needs-followup",
            "submit-fail-then-pass",  # behaves like submit-pass; orchestrator picks fixture
            "crash-on-receive",
            "route-bypass-attempt",
        ],
    )
    p.add_argument("--fixtures-json", default="{}")
    p.add_argument("--strategy", default="")
    p.add_argument("--crash-message", default="")
    p.add_argument("--followup-task", default="")
    p.add_argument("--followup-assignee", default="")
    p.add_argument("--followup-reason", default="")
    p.add_argument("--bypass-target", default="validator")
    p.add_argument(
        "--specialization",
        default="",
        help="Granular agent specialty for span emission (designer, curator, "
        "science_writer, ...). Defaults to 'worker' when unset, but the "
        "topology role registered with the relay is always 'worker'.",
    )
    args = p.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    register_with_relay(args.relay, args.id, "worker", base_url)
    boot_state = do_boot_actions(args)
    app = create_peer_app(
        agent_id=args.id,
        role="worker",
        base_url=base_url,
        handler=make_handler(args, boot_state),
        specialization=args.specialization or None,
    )
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    finally:
        deregister_from_relay(args.relay, args.id)


if __name__ == "__main__":
    main()
