# Agent protocol survey

A reference comparison of agent communication protocols circa May 2026, viewed through the lens of what the `otel-a2a-relay` cares about. The relay translates A2A wire traffic into OpenTelemetry spans for Phoenix, so the survey weighs each protocol on wire format, transport, semantics, and observability hooks. It is a survey, not a recommendation.

## Scope and non-goals

Survey only. It does not propose a protocol change. The relay targets A2A and that stays put. The point of the survey is to:

- Pin down what A2A actually is, in the same vocabulary used for its peers.
- Give future contributors a cheap-to-skim map when someone asks "could we also relay X".
- Make the dimensions we care about (observability hooks especially) explicit, so we can tell when a peer protocol is or is not relevant.

Out of scope: implementation guides, performance benchmarks, security analysis, opinions on which protocol "wins", and anything that requires running code.

The four axes used throughout:

- **Wire format** - the bytes that go on the wire.
- **Transport** - the channel underneath.
- **Semantics** - what the protocol models as first-class.
- **Observability hooks** - tracing, span construction, correlation IDs.

## Protocols covered

One file per protocol. Each follows the same shape: wire format, transport, semantics, observability hooks, maturity / governance, primary sources.

1. [A2A (Agent2Agent Protocol)](protocols-survey-a2a.md)
2. [MCP (Model Context Protocol)](protocols-survey-mcp.md)
3. [ACP (IBM Research / BeeAI)](protocols-survey-acp.md)
4. [AGNTCY (Cisco / Linux Foundation)](protocols-survey-agntcy.md)
5. [Agora Protocol (Oxford research)](protocols-survey-agora.md)
6. [LMOS (Eclipse Foundation)](protocols-survey-lmos.md)
7. [OpenAI Agents SDK and Realtime API](protocols-survey-openai.md)

Cross-cutting summary in [protocols-survey-summary.md](protocols-survey-summary.md).

## Where this leaves the relay

A2A's first-class `taskId` and `contextId` plus its explicit endorsement of W3C Trace Context and OpenTelemetry give the relay a clean target. Among the protocols surveyed, A2A is the one with the most observability-shaped surface area to map onto. MCP is adjacent (agent-to-tool, not agent-to-agent) but well-served by the OTel semconv when needed. AGNTCY SLIM is a substrate, not a competitor at the same layer. ACP merged in. LMOS, Agora, and the OpenAI SDK are not directly relevant to the relay's problem space in May 2026.

The relay does not need to change protocols. This document records why.
