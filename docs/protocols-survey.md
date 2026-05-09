# Agent protocol survey

A reference comparison of agent communication protocols circa May 2026, viewed through the lens of what the `otel-a2a-relay` cares about. The relay translates A2A wire traffic into OpenTelemetry spans for Phoenix, so the survey weighs each protocol on wire format, transport, semantics, and observability hooks. It is a survey, not a recommendation.

## Scope and non-goals

This document is a survey only. It does not propose a protocol change for `otel-a2a-relay`. The relay targets A2A and that stays put. The point of the survey is to:

- Pin down what A2A actually is, in the same vocabulary used for its peers.
- Give future contributors a cheap-to-skim map when someone asks "could we also relay X".
- Make the dimensions we care about (observability hooks especially) explicit, so we can tell when a peer protocol is or is not relevant to our problem space.

Out of scope: implementation guides, performance benchmarks, security analysis, opinions on which protocol "wins", and anything that requires running code. Where a fact comes from a primary source, the URL is inline. Where a fact comes from a secondary source (a blog post, a comparative-analysis article), it is labeled as such.

The four axes used throughout:

- **Wire format** - the bytes that go on the wire (JSON-RPC, REST/JSON, gRPC/protobuf, JSON-LD, etc).
- **Transport** - the channel underneath (HTTP, SSE, WebSocket, stdio, gRPC streaming).
- **Semantics** - what the protocol models as first-class (tasks, messages, tools, sessions, capabilities, agents, resources). Knowing what is first-class versus derived matters because the relay's spans need to map back to first-class concepts.
- **Observability hooks** - anything in the spec that helps with tracing or span construction. Trace-context propagation, request IDs, session or conversation IDs, span-link-friendly fields. Absences are also called out.

## Protocols covered

1. A2A (Agent2Agent Protocol)
2. MCP (Model Context Protocol)
3. ACP (Agent Communication Protocol, IBM Research / BeeAI)
4. AGNTCY (Cisco-led, now Linux Foundation)
5. Agora Protocol (Oxford research)
6. LMOS (Eclipse Foundation)
7. OpenAI Agents SDK and Realtime API (de-facto pattern, not a protocol)

Each section follows the same shape: wire format, transport, semantics, observability hooks, maturity / governance, primary sources.

## A2A (Agent2Agent Protocol)

What the relay currently speaks. Originally announced by Google in 2025 and contributed to the Linux Foundation later that year as an open-governance project.

**Wire format**

JSON over HTTP. The canonical data model is defined in Protocol Buffers (`spec/a2a.proto` is described as "the single authoritative normative definition" of all protocol objects), with three concrete bindings:

- JSON-RPC 2.0 over HTTP, with Server-Sent Events for streaming.
- gRPC with native streaming.
- HTTP+JSON / REST.

Field naming follows camelCase. Binary content in the JSON binding is base64-encoded.

**Transport**

HTTPS for unary calls. SSE for the streaming binding (`message/stream` and task subscription). gRPC streaming for the gRPC binding. The protocol leans on HTTP idioms (status codes, bearer tokens, headers) for the JSON-RPC and REST bindings.

**Semantics**

First-class objects, per the v1.0 spec:

- **AgentCard** - a JSON metadata document describing identity, capabilities, skills, service endpoint, and authentication. Discovered via well-known URIs. There is also a `GetExtendedAgentCard` method for authenticated capability discovery.
- **Task** - a stateful unit of work with a defined lifecycle and a unique `taskId`.
- **Message** - input or output exchanged within a Task.
- **Context** - a `contextId` that logically groups related Tasks and Messages, providing continuity across a series of interactions. Useful for conversational state.
- **Push notifications** - configurable per task (Create, Get, List, Delete methods).

Methods include `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, the push-notification config methods, and `GetExtendedAgentCard`. Versioning is `Major.Minor`, with patch numbers excluded from protocol negotiations. There are also `A2A-Version` and `A2A-Extensions` service parameters carried via HTTP headers (or gRPC metadata in the gRPC binding).

**Observability hooks**

This is the strongest area for A2A relative to its peers, and the reason the relay has anything to map onto.

- The "Enterprise Features" guidance explicitly recommends W3C Trace Context propagation via HTTP headers, and explicitly names OpenTelemetry as the industry-standard approach. Quote: clients and servers "should participate in distributed tracing systems".
- `taskId`, `sessionId`, and `contextId` are first-class and appear naturally as span attributes or span-link keys.
- `metadata` is an open key-value bag on requests, suitable for carrying additional correlation IDs without spec changes.
- Logging guidance calls out `taskId`, `sessionId`, correlation IDs, and trace context as the recommended fields to capture.
- Operational metrics (request rate, error rate, task latency, resource utilization) are explicitly recommended on the server side.

Because A2A leans on HTTP, off-the-shelf OpenTelemetry HTTP instrumentation already produces server and client spans. The relay's job is to enrich those with A2A-aware attributes (the `taskId` / `contextId` / method-name view).

**Maturity and governance**

- Latest spec: v1.0.0, dated March 12, 2026 per the GitHub release page.
- License: Apache 2.0.
- Governance: Linux Foundation open source project, contributed by Google. Maintainers listed in `MAINTAINERS.md` in the spec repo.
- Adoption: secondary-source claims of "150+ organizations" and integrations with major cloud platforms. Unverified by primary sources. Treat as directional only.

**Primary sources**

- Spec repo: https://github.com/a2aproject/A2A
- Spec site: https://a2a-protocol.org/latest/specification/
- Enterprise / observability guidance: https://a2a-protocol.org/latest/topics/enterprise-ready/
- "Life of a Task": https://a2a-protocol.org/latest/topics/life-of-a-task/

## MCP (Model Context Protocol)

Important framing up front: MCP is agent-to-tool, not agent-to-agent. The Anthropic spec describes hosts (LLM applications), clients (connectors inside a host), and servers (services that provide context and tools). The host is the agent. The server is a tool surface. There is no peer-to-peer agent semantics in the base protocol. People do build agent-to-agent patterns by stacking MCP servers behind an agent, but that is a usage pattern, not a protocol-level feature.

This matters for the relay. MCP traffic is not A2A traffic. They could coexist in the same process (an A2A-exposed agent might also speak MCP downstream to its tools), but the relay's pattern-matching is tuned for the agent-to-agent semantics A2A actually models.

**Wire format**

JSON-RPC 2.0. The canonical schema lives in TypeScript at https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-06-18/schema.ts, with the spec text generated from it. Date-based versioning (`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-...`).

**Transport**

Two officially supported transports:

- **stdio** - the original, used for local subprocess servers. Length-prefixed JSON-RPC over a process pipe.
- **Streamable HTTP** - the current HTTP transport, replacing the older HTTP+SSE transport from `2024-11-05`. A single MCP endpoint accepts both POST (request) and GET (server-initiated stream). The server may optionally use SSE to stream multiple messages. The 2026 roadmap signals further evolution (horizontally scalable, stateless servers) but no new official transports.

**Semantics**

Server-side primitives offered to clients:

- **Resources** - context and data (URI-addressable).
- **Prompts** - templated messages and workflows.
- **Tools** - functions for the model to execute.

Client-side primitives offered to servers:

- **Sampling** - server-initiated requests for the host to run an LLM call.
- **Roots** - URI or filesystem boundaries the server can ask about.
- **Elicitation** - server-initiated requests for additional user information.

Utilities: configuration, progress tracking, cancellation, error reporting, logging.

Connection is stateful and capability-negotiated at handshake. There is an experimental "Tasks" primitive in flight for the November 2025 spec, but it is explicitly experimental.

**Observability hooks**

MCP does not define trace-context propagation in the base protocol. The OpenTelemetry semantic-conventions group has filled that gap with a community spec.

- OpenTelemetry semconv for MCP defines span attributes including `mcp.method.name`, `mcp.session.id`, `mcp.protocol.version`, `mcp.resource.uri`, and `jsonrpc.request.id`. Tool calls map to `gen_ai.operation.name = execute_tool`. These are in **Development** stability, not stable.
- The semconv recommends propagating W3C Trace Context inside the MCP request's `params._meta` property bag (`traceparent`, `tracestate`, optional `baggage`). This is a convention layered over MCP, not a spec mandate, and the spec note calls it out as "likely to change".
- `progressToken` is a first-class mechanism for long-running operations. It is correlation-friendly but not a tracing primitive.

Net: instrumenting MCP for OTel works, but only if both ends agree on the semconv. Out of the box, the spec gives you `jsonrpc.request.id` and that is it.

**Maturity and governance**

- Latest spec: November 2025 release per the 2026 roadmap blog post. The widely-deployed snapshot through early 2026 is `2025-06-18`.
- License: open source, see the spec repo.
- Governance: Anthropic-led at the start. As of the 2026 roadmap, governance has shifted to Working Groups and Interest Groups with Core Maintainers providing strategic oversight.
- Adoption: very widespread among LLM-app stacks, IDE integrations, and developer tooling. Effectively the de-facto agent-to-tool standard.

**Primary sources**

- Spec entry point: https://modelcontextprotocol.io/specification/2025-06-18
- Spec repo: https://github.com/modelcontextprotocol
- 2026 roadmap: https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/
- OTel semantic conventions for MCP: https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/
- Trace-context propagation discussion: https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/269

## ACP (Agent Communication Protocol, IBM Research / BeeAI)

Status note: the IBM Research / BeeAI ACP repo (`i-am-bee/acp`) is **archived** as of August 27, 2025, with v1.0.3 as the final release. ACP has been folded into A2A under the Linux Foundation. The `agentcommunicationprotocol.dev` site states explicitly that ACP is "now part of A2A under the Linux Foundation". Treat ACP as historical context. The technical ideas it championed (REST-first, multimodal MIME parts, async-first with sync support) live on, partly absorbed into A2A's REST binding and message-part model.

**Wire format**

REST over HTTP, with JSON bodies. Multimodal content uses standard MIME types so a single message can carry text, images, audio, video, or custom binaries as separate parts. OpenAPI was the source of truth for the schema.

**Transport**

HTTP. Async-first with sync supported. Both stateful and stateless operation patterns were explicitly supported. Long-running tasks were idiomatic.

**Semantics**

- **Agent** - a participant.
- **Run** - a unit of work (analogous to A2A's Task).
- **Message** - input or output.
- **Part** - typed content slice inside a message, MIME-tagged.

The "MIME-typed parts" idea is the most distinctive contribution. It generalizes cleanly to multimodal flows without bolting on per-modality endpoints.

**Observability hooks**

ACP did not define a trace-context propagation mechanism at the spec level beyond standard HTTP headers. Because the wire is plain REST over HTTP, off-the-shelf HTTP-tracing instrumentation works (W3C `traceparent` flows naturally). Run IDs and message IDs play the role A2A's `taskId` and `messageId` play. No first-class `contextId`-like grouping equivalent appeared in the public docs reviewed.

**Maturity and governance**

- Status: archived. Final version v1.0.3 (August 21, 2025).
- License: Apache 2.0.
- Governance: was developed under the Linux Foundation AI & Data program. Now subsumed by A2A.
- Adoption: BeeAI was the reference implementation. The user-facing presence has migrated to A2A.

**Primary sources**

- Archived spec repo: https://github.com/i-am-bee/acp
- Docs site (still up, points at A2A): https://agentcommunicationprotocol.dev/introduction/welcome

## AGNTCY (Cisco / Linux Foundation)

AGNTCY is a Cisco-originated initiative donated to the Linux Foundation in July 2025, with Cisco, Dell Technologies, Google Cloud, Oracle, and Red Hat as founding members. It is a stack, not a single protocol. Several pieces, several wire formats. The picture has shifted in 2026: their original "Agent Connect Protocol" spec repo (`agntcy/acp-spec`, REST/OpenAPI) was archived on April 11, 2026, suggesting the connect-protocol piece is being subsumed (most plausibly by A2A, though that is speculation).

What remains active under AGNTCY:

**Components (per AGNTCY's own docs)**

- **OASF (Open Agentic Schema Framework)** - an OCI-based extensible data model for describing agent attributes and identity. Schema-as-OCI-artifact. JSON / YAML for the schema content.
- **Agent Directory** - a discovery service over OASF.
- **SLIM (Secure Low-latency Interactive Messaging)** - a gRPC-based communication layer. Supports request/reply, streaming, fire-and-forget, and pub/sub. MLS and post-quantum cryptography are called out. This is the most distinctive piece. It pitches a many-to-many comms substrate that a connect protocol (A2A or otherwise) can ride on top of.
- **Identity System** - decentralized identifier (DID) based agent identity.
- **Observability and Evaluation** - telemetry collection and evaluation tooling. Not detailed in the public docs reviewed.
- **Security Services** - policy and authorization tools.

**Wire format**

Differs by component. SLIM extends gRPC. OASF emits JSON / YAML schema content stored as OCI artifacts. The connect-protocol piece was REST + OpenAPI before archival.

**Transport**

SLIM is gRPC. The directory and OASF tooling are HTTP-shaped. SLIM specifically targets pub/sub and streaming over gRPC bidi-streaming.

**Semantics**

AGNTCY models the substrate, not the application protocol. Agents, identities, schemas, transports, topics, sessions. It is more "L4-L5 of an agent stack" than an A2A peer. A real deployment likely runs A2A or MCP on top of SLIM rather than instead of it.

**Observability hooks**

AGNTCY ships an "Observability and Evaluation" component as a first-class part of the stack. Public details are thin in the docs reviewed. Speculative: gRPC's standard trace-context propagation (W3C Trace Context via gRPC metadata) almost certainly carries through SLIM, since it is gRPC-derived. Confirm against current SLIM docs before relying on this.

**Maturity and governance**

- Governance: Linux Foundation, donated July 2025.
- License: open source (Apache 2.0 across the components reviewed).
- Status: connect-protocol piece archived April 2026. Other components active.
- Adoption signals: founding-member roster is strong (Cisco / Dell / Google Cloud / Oracle / Red Hat). Production-deployment evidence is harder to find in primary sources. Treat adoption claims as speculative.

**Primary sources**

- Org page: https://agntcy.org
- Docs: https://docs.agntcy.org
- GitHub org: https://github.com/agntcy
- Archived ACP spec repo: https://github.com/agntcy/acp-spec

## Agora Protocol (Oxford research)

Agora is a research protocol from a University of Oxford team (paper submitted October 2024, arXiv 2410.11905). It is interesting conceptually and worth knowing about, but it is not a shipping enterprise standard.

**Wire format**

Meta-protocol. Agora itself does not pin a wire format. It coordinates other protocols. Agents agree on a "Protocol Document" (PD) - a plain-text description of a sub-protocol they will use for a particular conversation type. Routine flows use compact, machine-defined sub-protocols. Rare flows fall back to natural language. Mid-frequency flows use LLM-generated routines.

**Transport**

Whatever the negotiated sub-protocol uses. HTTP is the default in the reference work.

**Semantics**

The first-class object is the **Protocol Document**. Agents discover, propose, accept, and adapt PDs at runtime. The framing is the "Agent Communication Trilemma" between versatility, efficiency, and portability.

**Observability hooks**

None defined at the protocol level. Tracing would have to attach to the negotiated sub-protocol.

**Maturity and governance**

- Status: research. Paper-and-demo level. Oxford team plus contributors.
- License: see the paper-demo repo (`agora-protocol/paper-demo`).
- Adoption: not enterprise-deployed as of the public sources reviewed.
- Why it is in this survey: it is a reasonable steel-man of "do we need a wire protocol at all, or can agents negotiate one per conversation". Useful as a thought experiment when someone proposes a fancier wire for the relay.

**Primary sources**

- Paper: https://arxiv.org/abs/2410.11905
- Project page: https://agoraprotocol.org/
- Demo repo: https://github.com/agora-protocol/paper-demo

## LMOS (Eclipse Foundation)

LMOS is an Eclipse Foundation project. The bigger umbrella is "Eclipse LMOS". It contains an Arc framework (Kotlin DSL for LLM apps) and an LMOS Protocol. The protocol is in active development, with the docs themselves noting "work in progress and contains empty sections".

**Wire format**

JSON-LD. The protocol explicitly chose JSON-LD for "structured, machine-readable" metadata with linked-data interoperability. Agent and tool descriptions are JSON-LD documents.

**Transport**

Multiple. The spec deliberately does not pin a single transport. HTTP, WebSocket, MQTT, and AMQP are mentioned as candidates. Agents pick what fits.

**Semantics**

Built on top of the W3C Web of Things (WoT) architecture. First-class concepts include agents, tools, agent / tool descriptions (JSON-LD), digital identities (W3C DIDs), discovery mechanisms, registries, and agent groups. The pitch is "agents and tools are Things, in the WoT sense".

**Observability hooks**

The docs reference an "Observability" section but the section was empty or thin in the public docs reviewed in May 2026. Because transport is not pinned, you would propagate W3C Trace Context using whatever mechanism the chosen transport supports. No protocol-level trace primitives.

**Maturity and governance**

- Governance: Eclipse Foundation. The team has signaled intent to take the protocol through the W3C standardization process once mature.
- License: Eclipse standard (typically EPL).
- Status: v1 namespace published, but protocol text marked work-in-progress. October 2025 press release announced an "Open Agent Definition Language (ADL)" framing.
- Adoption signals: enterprise pitch (Deutsche Telekom is the most-cited contributor in secondary sources). Production deployment evidence in primary sources is limited.

**Primary sources**

- Project: https://eclipse.dev/lmos/
- Protocol intro: https://eclipse.dev/lmos/docs/lmos_protocol/introduction/
- Agent description format: https://eclipse.dev/lmos/docs/multi_agent_system/agent_description/
- Arc framework: https://github.com/eclipse-lmos/arc

## OpenAI Agents SDK and Realtime API

Not a protocol. Worth a paragraph because it competes for the same niche in practice. If you are building a multi-agent product on OpenAI's stack, you might never reach for A2A or MCP, because the SDK gives you a vendor-shaped substitute.

**Wire format and transport**

OpenAI HTTP API (REST + SSE for streaming) for the Agents SDK. Realtime API uses WebSocket for low-latency bidirectional voice and tool calls.

**Semantics**

The SDK exposes Agents, Tools, Handoffs, and Sessions. Handoffs are the agent-to-agent feature: an agent can hand a conversation off to another agent. Internally a handoff is represented to the LLM as a tool call (e.g. `transfer_to_refund_agent`). For Realtime, a handoff triggers a `session.update` event with new instructions and tools.

**Observability hooks**

OpenAI provides its own tracing dashboard for the Agents SDK with run-level traces. Bridges to OpenTelemetry exist (OTel-shaped exporters from the SDK), but the protocol on the wire is OpenAI's own. There is no open spec, so cross-vendor tracing requires SDK-level instrumentation rather than protocol-level header propagation.

**Maturity and governance**

- Vendor-controlled. No open governance.
- License: SDK is Apache 2.0. The API itself is closed.
- Status: GA. TypeScript and Python SDKs are first-class. Voice agents via Realtime are GA.
- Why it is in this survey: many "agent-to-agent" deployments in 2026 are in fact intra-vendor handoffs inside the OpenAI SDK rather than cross-vendor wire-protocol calls. Worth knowing because it shapes who is and is not in the A2A market.

**Primary sources**

- Agents SDK (Python): https://openai.github.io/openai-agents-python/
- Agents SDK (TypeScript): https://openai.github.io/openai-agents-js/
- Handoffs guide: https://openai.github.io/openai-agents-python/handoffs/
- Realtime agents demo: https://github.com/openai/openai-realtime-agents
- "Next evolution of the Agents SDK" post: https://openai.com/index/the-next-evolution-of-the-agents-sdk/

## Comparison summary

Flat bullets. Format: `* <protocol> - <wire> / <transport> - <details>`.

Wire format and transport at a glance:

* A2A - JSON-RPC 2.0, REST, gRPC / HTTPS, SSE, gRPC streaming - three official bindings, protobuf is canonical
* MCP - JSON-RPC 2.0 / stdio, Streamable HTTP - agent-to-tool only, dual transport, SSE optional inside HTTP transport
* ACP (i-am-bee) - REST over JSON / HTTPS - archived, folded into A2A, MIME-typed message parts
* AGNTCY SLIM - gRPC / HTTP+2 - substrate layer, pub/sub + streaming + req-rep, post-quantum-friendly
* AGNTCY OASF - JSON / YAML in OCI artifacts - schema framework, not a wire protocol
* Agora - meta-protocol, wire is whatever PDs negotiate / HTTP default - research, not enterprise
* LMOS - JSON-LD / HTTP, WebSocket, MQTT, AMQP - W3C Web-of-Things-shaped, transport-agnostic by design
* OpenAI Agents SDK - OpenAI HTTP API + WebSocket Realtime - vendor stack, handoffs via tool-call mechanism

Semantics, what is first-class:

* A2A - AgentCard, Task, Message, contextId, push notifications - first-class taskId and contextId are span-friendly
* MCP - Resources, Prompts, Tools, Sampling, Roots, Elicitation - tool-surface model, not peer-agent
* ACP - Agent, Run, Message, MIME-typed Part - multimodal-first
* AGNTCY - Agent identity (DID), schema (OASF), transport (SLIM), directory - infrastructure layer
* Agora - Protocol Document - everything else is negotiated
* LMOS - Agent, Tool, Description, DID, Group - WoT-derived
* OpenAI SDK - Agent, Tool, Handoff, Session - vendor-defined, not interop

Observability hooks worth attaching spans to:

* A2A - W3C Trace Context recommended, taskId / contextId / sessionId first-class, OpenTelemetry called out by name in enterprise guidance
* MCP - no spec-level trace propagation, OTel semconv defines params._meta convention with traceparent / tracestate, jsonrpc.request.id and progressToken are useful
* ACP - HTTP-native, traceparent flows naturally, no protocol-level correlation primitives beyond run/message IDs
* AGNTCY SLIM - speculative, gRPC metadata likely carries traceparent, primary docs thin
* AGNTCY OASF - no trace concept, schema not a wire
* Agora - no protocol-level trace, attaches at the negotiated sub-protocol layer
* LMOS - observability section thin in docs, depends on chosen transport
* OpenAI SDK - vendor tracing dashboard, OTel bridges exist, no open wire protocol

Maturity and governance:

* A2A - Apache 2.0, Linux Foundation, v1.0.0 (March 2026), broad enterprise adoption claimed
* MCP - open source, governance via Working Groups + Core Maintainers, latest spec November 2025, very widespread agent-to-tool adoption
* ACP - archived (August 2025), folded into A2A
* AGNTCY - Linux Foundation (donated July 2025), Cisco-led, ACP-spec piece archived April 2026, other components active
* Agora - Oxford research, not enterprise-deployed
* LMOS - Eclipse Foundation, work-in-progress spec, eyes on W3C standardization
* OpenAI SDK - vendor-owned, GA, no open governance

## Where this leaves the relay

Stating it for the file: A2A's first-class `taskId` and `contextId` plus its explicit endorsement of W3C Trace Context and OpenTelemetry give the relay a clean target. Among the protocols surveyed, A2A is the one with the most observability-shaped surface area to map onto. MCP is adjacent (agent-to-tool, not agent-to-agent) but well-served by the OTel semconv when needed. AGNTCY SLIM is a substrate, not a competitor at the same layer. ACP merged in. LMOS, Agora, and the OpenAI SDK are not directly relevant to the relay's problem space in May 2026.

The relay does not need to change protocols. This document records why.
