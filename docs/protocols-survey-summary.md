# Agent protocol survey - comparison summary

Companion to [protocols-survey.md](protocols-survey.md). Cross-cutting comparison of the seven protocols on wire / transport, semantics, observability hooks, and governance.

## Wire format and transport at a glance

- A2A - JSON-RPC 2.0, REST, gRPC / HTTPS, SSE, gRPC streaming - three official bindings, protobuf is canonical.
- MCP - JSON-RPC 2.0 / stdio, Streamable HTTP - agent-to-tool only, dual transport, SSE optional inside HTTP transport.
- ACP (i-am-bee) - REST over JSON / HTTPS - archived, folded into A2A, MIME-typed message parts.
- AGNTCY SLIM - gRPC / HTTP+2 - substrate layer, pub/sub + streaming + req-rep, post-quantum-friendly.
- AGNTCY OASF - JSON / YAML in OCI artifacts - schema framework, not a wire protocol.
- Agora - meta-protocol, wire is whatever PDs negotiate / HTTP default - research, not enterprise.
- LMOS - JSON-LD / HTTP, WebSocket, MQTT, AMQP - W3C Web-of-Things-shaped, transport-agnostic by design.
- OpenAI Agents SDK - OpenAI HTTP API + WebSocket Realtime - vendor stack, handoffs via tool-call mechanism.

## Semantics - what is first-class

- A2A - AgentCard, Task, Message, contextId, push notifications - first-class taskId and contextId are span-friendly.
- MCP - Resources, Prompts, Tools, Sampling, Roots, Elicitation - tool-surface model, not peer-agent.
- ACP - Agent, Run, Message, MIME-typed Part - multimodal-first.
- AGNTCY - Agent identity (DID), schema (OASF), transport (SLIM), directory - infrastructure layer.
- Agora - Protocol Document - everything else is negotiated.
- LMOS - Agent, Tool, Description, DID, Group - WoT-derived.
- OpenAI SDK - Agent, Tool, Handoff, Session - vendor-defined, not interop.

## Observability hooks worth attaching spans to

- A2A - W3C Trace Context recommended, taskId / contextId / sessionId first-class, OpenTelemetry called out by name in enterprise guidance.
- MCP - no spec-level trace propagation, OTel semconv defines params._meta convention with traceparent / tracestate, jsonrpc.request.id and progressToken are useful.
- ACP - HTTP-native, traceparent flows naturally, no protocol-level correlation primitives beyond run/message IDs.
- AGNTCY SLIM - speculative, gRPC metadata likely carries traceparent, primary docs thin.
- AGNTCY OASF - no trace concept, schema not a wire.
- Agora - no protocol-level trace, attaches at the negotiated sub-protocol layer.
- LMOS - observability section thin in docs, depends on chosen transport.
- OpenAI SDK - vendor tracing dashboard, OTel bridges exist, no open wire protocol.

## Maturity and governance

- A2A - Apache 2.0, Linux Foundation, v1.0.0 (March 2026), broad enterprise adoption claimed.
- MCP - open source, governance via Working Groups + Core Maintainers, latest spec November 2025, very widespread agent-to-tool adoption.
- ACP - archived (August 2025), folded into A2A.
- AGNTCY - Linux Foundation (donated July 2025), Cisco-led, ACP-spec piece archived April 2026, other components active.
- Agora - Oxford research, not enterprise-deployed.
- LMOS - Eclipse Foundation, work-in-progress spec, eyes on W3C standardization.
- OpenAI SDK - vendor-owned, GA, no open governance.
