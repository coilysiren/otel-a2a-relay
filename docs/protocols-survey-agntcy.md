# AGNTCY (Cisco / Linux Foundation)

Companion to [protocols-survey.md](protocols-survey.md). Cisco-originated initiative donated to the Linux Foundation in July 2025, with Cisco, Dell Technologies, Google Cloud, Oracle, and Red Hat as founding members. It is a stack, not a single protocol. Several pieces, several wire formats.

The picture shifted in 2026: the original "Agent Connect Protocol" spec repo (`agntcy/acp-spec`, REST/OpenAPI) was archived on April 11, 2026, suggesting the connect-protocol piece is being subsumed (most plausibly by A2A, though that is speculation).

## Components (per AGNTCY's own docs)

- **OASF (Open Agentic Schema Framework)** - an OCI-based extensible data model for describing agent attributes and identity. Schema-as-OCI-artifact. JSON / YAML for the schema content.
- **Agent Directory** - a discovery service over OASF.
- **SLIM (Secure Low-latency Interactive Messaging)** - a gRPC-based communication layer. Supports request/reply, streaming, fire-and-forget, and pub/sub. MLS and post-quantum cryptography are called out. The most distinctive piece. Pitches a many-to-many comms substrate that a connect protocol (A2A or otherwise) can ride on top of.
- **Identity System** - decentralized identifier (DID) based agent identity.
- **Observability and Evaluation** - telemetry collection and evaluation tooling. Not detailed in the public docs reviewed.
- **Security Services** - policy and authorization tools.

## Wire format

Differs by component. SLIM extends gRPC. OASF emits JSON / YAML schema content stored as OCI artifacts. The connect-protocol piece was REST + OpenAPI before archival.

## Transport

SLIM is gRPC. The directory and OASF tooling are HTTP-shaped. SLIM specifically targets pub/sub and streaming over gRPC bidi-streaming.

## Semantics

AGNTCY models the substrate, not the application protocol. Agents, identities, schemas, transports, topics, sessions. It is more "L4-L5 of an agent stack" than an A2A peer. A real deployment likely runs A2A or MCP on top of SLIM rather than instead of it.

## Observability hooks

AGNTCY ships an "Observability and Evaluation" component as a first-class part of the stack. Public details are thin in the docs reviewed. Speculative: gRPC's standard trace-context propagation (W3C Trace Context via gRPC metadata) almost certainly carries through SLIM, since it is gRPC-derived. Confirm against current SLIM docs before relying on this.

## Maturity and governance

- Governance: Linux Foundation, donated July 2025.
- License: open source (Apache 2.0 across the components reviewed).
- Status: connect-protocol piece archived April 2026. Other components active.
- Adoption signals: founding-member roster is strong (Cisco / Dell / Google Cloud / Oracle / Red Hat). Production-deployment evidence is harder to find in primary sources.

## Primary sources

- Org page: https://agntcy.org
- Docs: https://docs.agntcy.org
- GitHub org: https://github.com/agntcy
- Archived ACP spec repo: https://github.com/agntcy/acp-spec
