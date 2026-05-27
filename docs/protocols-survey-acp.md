# ACP (Agent Communication Protocol, IBM Research / BeeAI)

Companion to [protocols-survey.md](protocols-survey.md). The IBM Research / BeeAI ACP repo (`i-am-bee/acp`) is **archived** as of August 27, 2025, with v1.0.3 as the final release. ACP has been folded into A2A under the Linux Foundation. The `agentcommunicationprotocol.dev` site states explicitly that ACP is "now part of A2A under the Linux Foundation". Treat ACP as historical context. The technical ideas it championed (REST-first, multimodal MIME parts, async-first with sync support) live on, partly absorbed into A2A's REST binding and message-part model.

## Wire format

REST over HTTP, with JSON bodies. Multimodal content uses standard MIME types so a single message can carry text, images, audio, video, or custom binaries as separate parts. OpenAPI was the source of truth for the schema.

## Transport

HTTP. Async-first with sync supported. Both stateful and stateless operation patterns were explicitly supported. Long-running tasks were idiomatic.

## Semantics

- **Agent** - a participant.
- **Run** - a unit of work (analogous to A2A's Task).
- **Message** - input or output.
- **Part** - typed content slice inside a message, MIME-tagged.

The "MIME-typed parts" idea is the most distinctive contribution. It generalizes cleanly to multimodal flows without bolting on per-modality endpoints.

## Observability hooks

ACP did not define a trace-context propagation mechanism at the spec level beyond standard HTTP headers. Because the wire is plain REST over HTTP, off-the-shelf HTTP-tracing instrumentation works (W3C `traceparent` flows naturally). Run IDs and message IDs play the role A2A's `taskId` and `messageId` play. No first-class `contextId`-like grouping equivalent appeared in the public docs reviewed.

## Maturity and governance

- Status: archived. Final version v1.0.3 (August 21, 2025).
- License: Apache 2.0.
- Governance: was developed under the Linux Foundation AI & Data program. Now subsumed by A2A.
- Adoption: BeeAI was the reference implementation. User-facing presence has migrated to A2A.

## Primary sources

- Archived spec repo: https://github.com/i-am-bee/acp
- Docs site (points at A2A): https://agentcommunicationprotocol.dev/introduction/welcome
