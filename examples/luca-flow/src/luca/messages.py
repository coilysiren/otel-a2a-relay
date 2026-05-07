"""LUCA message envelope helpers.

Every message exchanged in the LUCA flow carries:

  - a humanized one-liner (with emoji) in the A2A text part - readable in
    Phoenix's trace view and in `make view CTX=...` output
  - a structured `luca.*` block in metadata - what the receiving process
    actually programs against

Helpers here build and parse those envelopes. Pure functions, no I/O.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

# Message kinds. Each is a verb the orchestrator or a peer initiates.
KIND_PLAN_ENQUEUE = "plan.enqueue"
KIND_PLAN_NEXT = "plan.next"
KIND_PLAN_NOTE = "plan.note"
KIND_DISPATCH = "dispatch"
KIND_SUBMIT_PASS = "submit.pass"
KIND_SUBMIT_FAIL = "submit.fail"
KIND_SUBMIT_NEEDS_FOLLOWUP = "submit.needs-followup"
KIND_SUBMIT_BYPASS_ATTEMPT = "submit.bypass-attempt"
KIND_VALIDATE_REQUEST = "validate.request"
KIND_VALIDATE_PASS = "validate.pass"
KIND_VALIDATE_FAIL = "validate.fail"
KIND_DEPLOY_REQUEST = "deploy.request"
KIND_DEPLOY_DONE = "deploy.done"
KIND_FLOW_COMPLETE = "flow.complete"


@dataclass
class LucaEnvelope:
    """The structured side of a LUCA message.

    `human` is the emoji-prefixed one-liner. `kind` and `data` are
    machine-readable. Everything else is for tracing / debugging.
    """

    kind: str
    human: str
    sender: str
    target: str
    step: int = 0
    task_id: str = ""
    actor: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_metadata(self) -> dict[str, Any]:
        """Serialize for inclusion in an A2A message's metadata block."""
        return {
            "agent.id": self.sender,
            "agent.target": self.target,
            "luca.kind": self.kind,
            "luca.human": self.human,
            "luca.step": self.step,
            "luca.task_id": self.task_id,
            "luca.actor": self.actor,
            "luca.timestamp": self.timestamp,
            "luca.data": json.dumps(self.data, sort_keys=True),
        }

    def to_message(
        self,
        *,
        context_id: str,
        a2a_task_id: str | None = None,
        message_id: str | None = None,
        role: str = "user",
    ) -> dict[str, Any]:
        """Build a full A2A `message` object suitable for `message/send` params."""
        return {
            "messageId": message_id or f"m-{uuid.uuid4().hex[:8]}",
            "taskId": a2a_task_id or f"t-{uuid.uuid4().hex[:8]}",
            "contextId": context_id,
            "role": role,
            "parts": [{"kind": "text", "text": self.human}],
            "metadata": self.to_metadata(),
        }

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def parse_envelope(message: dict[str, Any]) -> LucaEnvelope:
    """Reconstruct a LucaEnvelope from an inbound A2A message."""
    md = message.get("metadata") or {}
    raw_data = md.get("luca.data") or "{}"
    try:
        data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except json.JSONDecodeError:
        data = {}
    return LucaEnvelope(
        kind=md.get("luca.kind", ""),
        human=md.get("luca.human") or _first_text(message),
        sender=md.get("agent.id", ""),
        target=md.get("agent.target", ""),
        step=int(md.get("luca.step", 0)),
        task_id=md.get("luca.task_id", ""),
        actor=md.get("luca.actor", ""),
        data=data,
        timestamp=float(md.get("luca.timestamp", time.time())),
    )


def _first_text(message: dict[str, Any]) -> str:
    for part in message.get("parts") or []:
        if part.get("kind") == "text":
            return part.get("text", "") or ""
    return ""


def humanize(emoji: str, role_display: str, action: str, detail: str = "") -> str:
    """Build a one-line humanized message in the canonical shape:

        '<emoji> <role-display> <action>: <detail>'

    All LUCA messages should pass through this so the format stays consistent.
    Single-emoji rule from AGENTS.md is honored implicitly.
    """
    base = f"{emoji} {role_display} {action}".rstrip()
    if detail:
        return f"{base}: {detail}"
    return base
