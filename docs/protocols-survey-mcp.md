# MCP (Model Context Protocol)

Companion to [protocols-survey.md](protocols-survey.md). MCP is agent-to-tool, not agent-to-agent. The Anthropic spec describes hosts (LLM applications), clients (connectors inside a host), and servers (services that provide context and tools). The host is the agent. The server is a tool surface. There is no peer-to-peer agent semantics in the base protocol. People do build agent-to-agent patterns by stacking MCP servers behind an agent, but that is a usage pattern, not a protocol-level feature.

This matters for the relay. MCP traffic is not A2A traffic. They could coexist in the same process (an A2A-exposed agent might also speak MCP downstream to its tools), but the relay's pattern-matching is tuned for the agent-to-agent semantics A2A actually models.

## Wire format

JSON-RPC 2.0. The canonical schema lives in TypeScript at https://github.com/modelcontextprotocol/specification/blob/main/schema/2025-06-18/schema.ts. Date-based versioning (`2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-...`).

## Transport

Two officially supported transports:

- **stdio** - the original, used for local subprocess servers. Length-prefixed JSON-RPC over a process pipe.
- **Streamable HTTP** - the current HTTP transport, replacing the older HTTP+SSE transport from `2024-11-05`. A single MCP endpoint accepts both POST (request) and GET (server-initiated stream). The server may optionally use SSE to stream multiple messages. The 2026 roadmap signals further evolution (horizontally scalable, stateless servers).

## Semantics

Server-side primitives offered to clients: **Resources** (URI-addressable context and data), **Prompts** (templated messages and workflows), **Tools** (functions for the model to execute).

Client-side primitives offered to servers: **Sampling** (server-initiated requests for the host to run an LLM call), **Roots** (URI or filesystem boundaries), **Elicitation** (server-initiated requests for additional user information).

Utilities: configuration, progress tracking, cancellation, error reporting, logging. Connection is stateful and capability-negotiated at handshake. There is an experimental "Tasks" primitive in flight for the November 2025 spec, but it is explicitly experimental.

## Observability hooks

MCP does not define trace-context propagation in the base protocol. The OpenTelemetry semantic-conventions group has filled that gap with a community spec.

- OpenTelemetry semconv for MCP defines span attributes including `mcp.method.name`, `mcp.session.id`, `mcp.protocol.version`, `mcp.resource.uri`, and `jsonrpc.request.id`. Tool calls map to `gen_ai.operation.name = execute_tool`. These are in **Development** stability, not stable.
- The semconv recommends propagating W3C Trace Context inside the MCP request's `params._meta` property bag (`traceparent`, `tracestate`, optional `baggage`). This is a convention layered over MCP, not a spec mandate.
- `progressToken` is a first-class mechanism for long-running operations. Correlation-friendly but not a tracing primitive.

Net: instrumenting MCP for OTel works, but only if both ends agree on the semconv.

## Maturity and governance

- Latest spec: November 2025 release per the 2026 roadmap blog post. The widely-deployed snapshot through early 2026 is `2025-06-18`.
- License: open source.
- Governance: Anthropic-led at the start. As of the 2026 roadmap, governance has shifted to Working Groups and Interest Groups with Core Maintainers providing strategic oversight.
- Adoption: very widespread among LLM-app stacks, IDE integrations, and developer tooling. Effectively the de-facto agent-to-tool standard.

## Primary sources

- Spec entry point: https://modelcontextprotocol.io/specification/2025-06-18
- Spec repo: https://github.com/modelcontextprotocol
- 2026 roadmap: https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/
- OTel semantic conventions for MCP: https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/
