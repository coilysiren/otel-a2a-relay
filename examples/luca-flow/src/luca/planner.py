"""LUCA planner.

Pure oracle. Holds the task queue, answers `plan.next` requests from the
orchestrator, records `plan.note` entries the orchestrator forwards. Talks
exclusively to the orchestrator (star topology).

The queue is seeded from script.yaml at boot. Each `plan.next` call pops
the head; each `plan.enqueue` call appends a follow-up task.
"""

from __future__ import annotations

import argparse
import threading
from collections import deque
from typing import Any

import uvicorn
import yaml

from luca.messages import (
    KIND_PLAN_ENQUEUE,
    KIND_PLAN_NEXT,
    KIND_PLAN_NOTE,
    LucaEnvelope,
    humanize,
)
from luca.peer import (
    create_peer_app,
    deregister_from_relay,
    register_with_relay,
)


class TaskQueue:
    """Thread-safe FIFO queue of script steps + dynamically-enqueued followups."""

    def __init__(self, steps: list[dict[str, Any]]) -> None:
        self._q: deque[dict[str, Any]] = deque(steps)
        self._notes: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def pop(self) -> dict[str, Any] | None:
        with self._lock:
            return self._q.popleft() if self._q else None

    def push(self, step: dict[str, Any]) -> None:
        with self._lock:
            self._q.append(step)

    def note(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._notes.append(entry)

    def remaining(self) -> int:
        with self._lock:
            return len(self._q)


def make_handler(queue: TaskQueue) -> Any:
    def handle(env: LucaEnvelope, _msg: dict[str, Any]) -> LucaEnvelope:
        if env.kind == KIND_PLAN_NEXT:
            step = queue.pop()
            if step is None:
                return LucaEnvelope(
                    kind="plan.empty",
                    human=humanize("📋", "Project Manager", "queue is empty"),
                    sender="planner",
                    target=env.sender,
                    data={},
                )
            return LucaEnvelope(
                kind="plan.dispatch",
                human=humanize(
                    "📋",
                    "Project Manager",
                    f"next up step {step.get('step')}",
                    f"{step.get('actor')} - {step.get('title')}",
                ),
                sender="planner",
                target=env.sender,
                step=int(step.get("step", 0)),
                task_id=step.get("task_id", ""),
                actor=step.get("actor", ""),
                data=step,
            )
        if env.kind == KIND_PLAN_ENQUEUE:
            new_step = env.data
            queue.push(new_step)
            return LucaEnvelope(
                kind="plan.enqueued",
                human=humanize(
                    "📋",
                    "Project Manager",
                    "enqueued follow-up",
                    f"step {new_step.get('step')} {new_step.get('actor')} "
                    f"{new_step.get('task_id')}",
                ),
                sender="planner",
                target=env.sender,
                step=int(new_step.get("step", 0)),
                task_id=new_step.get("task_id", ""),
                actor=new_step.get("actor", ""),
                data={"remaining": queue.remaining()},
            )
        if env.kind == KIND_PLAN_NOTE:
            queue.note(env.data)
            return LucaEnvelope(
                kind="plan.noted",
                human=humanize("📋", "Project Manager", "noted", env.human),
                sender="planner",
                target=env.sender,
                step=env.step,
                task_id=env.task_id,
            )
        return LucaEnvelope(
            kind="plan.unknown",
            human=humanize("📋", "Project Manager", "did not understand", env.kind),
            sender="planner",
            target=env.sender,
        )

    return handle


def load_script_steps(script_path: str) -> list[dict[str, Any]]:
    with open(script_path) as f:
        doc = yaml.safe_load(f)
    return list(doc.get("steps") or [])


def build_app(script_path: str, base_url: str) -> Any:
    steps = load_script_steps(script_path)
    queue = TaskQueue(steps)
    return create_peer_app(
        agent_id="planner",
        role="planner",
        base_url=base_url,
        handler=make_handler(queue),
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--script", required=True)
    p.add_argument("--port", type=int, default=9101)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--relay", default="http://127.0.0.1:8080")
    args = p.parse_args()

    base_url = f"http://{args.host}:{args.port}/"
    app = build_app(args.script, base_url)
    register_with_relay(args.relay, "planner", "planner", base_url)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    finally:
        deregister_from_relay(args.relay, "planner")


if __name__ == "__main__":
    main()
