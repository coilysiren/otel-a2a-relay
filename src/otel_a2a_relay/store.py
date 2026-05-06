"""In-memory task store.

One per process. Not durable, not shared across processes. Fine for the
single-relay dogfood; the next slice that introduces a real persistence
substrate (or a second relay) replaces this.

Tasks are keyed by `task.id`. Storing again under the same id overwrites.
"""

from __future__ import annotations

import copy
import threading
from typing import Any


class TaskStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def put(self, task: dict[str, Any]) -> None:
        task_id = task.get("id")
        if not task_id:
            return
        with self._lock:
            self._tasks[task_id] = copy.deepcopy(task)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return copy.deepcopy(task) if task else None

    def update_state(self, task_id: str, state: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task["status"] = {**task.get("status", {}), "state": state}
            return copy.deepcopy(task)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(t) for t in self._tasks.values()]
