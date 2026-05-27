# LMOS (Eclipse Foundation)

Companion to [protocols-survey.md](protocols-survey.md). LMOS is an Eclipse Foundation project. The bigger umbrella is "Eclipse LMOS". It contains an Arc framework (Kotlin DSL for LLM apps) and an LMOS Protocol. The protocol is in active development, with the docs themselves noting "work in progress and contains empty sections".

## Wire format

JSON-LD. The protocol explicitly chose JSON-LD for "structured, machine-readable" metadata with linked-data interoperability. Agent and tool descriptions are JSON-LD documents.

## Transport

Multiple. The spec deliberately does not pin a single transport. HTTP, WebSocket, MQTT, and AMQP are mentioned as candidates. Agents pick what fits.

## Semantics

Built on top of the W3C Web of Things (WoT) architecture. First-class concepts include agents, tools, agent / tool descriptions (JSON-LD), digital identities (W3C DIDs), discovery mechanisms, registries, and agent groups. The pitch is "agents and tools are Things, in the WoT sense".

## Observability hooks

The docs reference an "Observability" section but the section was empty or thin in the public docs reviewed in May 2026. Because transport is not pinned, you would propagate W3C Trace Context using whatever mechanism the chosen transport supports. No protocol-level trace primitives.

## Maturity and governance

- Governance: Eclipse Foundation. The team has signaled intent to take the protocol through the W3C standardization process once mature.
- License: Eclipse standard (typically EPL).
- Status: v1 namespace published, but protocol text marked work-in-progress. October 2025 press release announced an "Open Agent Definition Language (ADL)" framing.
- Adoption signals: enterprise pitch (Deutsche Telekom is the most-cited contributor in secondary sources). Production deployment evidence in primary sources is limited.

## Primary sources

- Project: https://eclipse.dev/lmos/
- Protocol intro: https://eclipse.dev/lmos/docs/lmos_protocol/introduction/
- Agent description format: https://eclipse.dev/lmos/docs/multi_agent_system/agent_description/
- Arc framework: https://github.com/eclipse-lmos/arc
