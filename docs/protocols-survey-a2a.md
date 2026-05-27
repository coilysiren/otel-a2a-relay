# A2A (Agent2Agent Protocol)

Companion to [protocols-survey.md](protocols-survey.md). What the relay currently speaks. Originally announced by Google in 2025 and contributed to the Linux Foundation later that year as an open-governance project.

## Wire format

JSON over HTTP. The canonical data model is defined in Protocol Buffers (`spec/a2a.proto` is described as "the single authoritative normative definition" of all protocol objects), with three concrete bindings:

- JSON-RPC 2.0 over HTTP, with Server-Sent Events for streaming.
- gRPC with native streaming.
- HTTP+JSON / REST.

Field naming follows camelCase. Binary content in the JSON binding is base64-encoded.

## Transport

HTTPS for unary calls. SSE for the streaming binding (`message/stream` and task subscription). gRPC streaming for the gRPC binding. The protocol leans on HTTP idioms (status codes, bearer tokens, headers) for the JSON-RPC and REST bindings.

## Semantics

First-class objects, per the v1.0 spec:

- **AgentCard** - JSON metadata document describing identity, capabilities, skills, service endpoint, and authentication. Discovered via well-known URIs.
- **Task** - stateful unit of work with a defined lifecycle and a unique `taskId`.
- **Message** - input or output exchanged within a Task.
- **Context** - a `contextId` that logically groups related Tasks and Messages, providing continuity across a series of interactions.
- **Push notifications** - configurable per task (Create, Get, List, Delete methods).

Methods include `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, push-notification config methods, and `GetExtendedAgentCard`. Versioning is `Major.Minor`. There are also `A2A-Version` and `A2A-Extensions` service parameters carried via HTTP headers (or gRPC metadata in the gRPC binding).

## Observability hooks

The strongest area for A2A relative to its peers, and the reason the relay has anything to map onto.

- The "Enterprise Features" guidance explicitly recommends W3C Trace Context propagation via HTTP headers, and explicitly names OpenTelemetry as the industry-standard approach.
- `taskId`, `sessionId`, and `contextId` are first-class and appear naturally as span attributes or span-link keys.
- `metadata` is an open key-value bag on requests, suitable for carrying additional correlation IDs without spec changes.
- Logging guidance calls out `taskId`, `sessionId`, correlation IDs, and trace context as the recommended fields to capture.
- Operational metrics (request rate, error rate, task latency, resource utilization) are explicitly recommended on the server side.

Because A2A leans on HTTP, off-the-shelf OpenTelemetry HTTP instrumentation already produces server and client spans. The relay's job is to enrich those with A2A-aware attributes (the `taskId` / `contextId` / method-name view).

## Maturity and governance

- Latest spec: v1.0.0, dated March 12, 2026 per the GitHub release page.
- License: Apache 2.0.
- Governance: Linux Foundation open source project, contributed by Google.
- Adoption: secondary-source claims of "150+ organizations" and integrations with major cloud platforms. Unverified by primary sources.

## Primary sources

- Spec repo: https://github.com/a2aproject/A2A
- Spec site: https://a2a-protocol.org/latest/specification/
- Enterprise / observability guidance: https://a2a-protocol.org/latest/topics/enterprise-ready/
- "Life of a Task": https://a2a-protocol.org/latest/topics/life-of-a-task/
