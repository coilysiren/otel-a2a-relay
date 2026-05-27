# OpenAI Agents SDK and Realtime API

Companion to [protocols-survey.md](protocols-survey.md). Not a protocol. Worth a paragraph because it competes for the same niche in practice. If you are building a multi-agent product on OpenAI's stack, you might never reach for A2A or MCP, because the SDK gives you a vendor-shaped substitute.

## Wire format and transport

OpenAI HTTP API (REST + SSE for streaming) for the Agents SDK. Realtime API uses WebSocket for low-latency bidirectional voice and tool calls.

## Semantics

The SDK exposes Agents, Tools, Handoffs, and Sessions. Handoffs are the agent-to-agent feature: an agent can hand a conversation off to another agent. Internally a handoff is represented to the LLM as a tool call (e.g. `transfer_to_refund_agent`). For Realtime, a handoff triggers a `session.update` event with new instructions and tools.

## Observability hooks

OpenAI provides its own tracing dashboard for the Agents SDK with run-level traces. Bridges to OpenTelemetry exist (OTel-shaped exporters from the SDK), but the protocol on the wire is OpenAI's own. There is no open spec, so cross-vendor tracing requires SDK-level instrumentation rather than protocol-level header propagation.

## Maturity and governance

- Vendor-controlled. No open governance.
- License: SDK is Apache 2.0. The API itself is closed.
- Status: GA. TypeScript and Python SDKs are first-class. Voice agents via Realtime are GA.
- Why it is in this survey: many "agent-to-agent" deployments in 2026 are in fact intra-vendor handoffs inside the OpenAI SDK rather than cross-vendor wire-protocol calls. Worth knowing because it shapes who is and is not in the A2A market.

## Primary sources

- Agents SDK (Python): https://openai.github.io/openai-agents-python/
- Agents SDK (TypeScript): https://openai.github.io/openai-agents-js/
- Handoffs guide: https://openai.github.io/openai-agents-python/handoffs/
- Realtime agents demo: https://github.com/openai/openai-realtime-agents
- "Next evolution of the Agents SDK" post: https://openai.com/index/the-next-evolution-of-the-agents-sdk/
