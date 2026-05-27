# Agora Protocol (Oxford research)

Companion to [protocols-survey.md](protocols-survey.md). Research protocol from a University of Oxford team (paper submitted October 2024, arXiv 2410.11905). Interesting conceptually and worth knowing about, but not a shipping enterprise standard.

## Wire format

Meta-protocol. Agora itself does not pin a wire format. It coordinates other protocols. Agents agree on a "Protocol Document" (PD) - a plain-text description of a sub-protocol they will use for a particular conversation type. Routine flows use compact, machine-defined sub-protocols. Rare flows fall back to natural language. Mid-frequency flows use LLM-generated routines.

## Transport

Whatever the negotiated sub-protocol uses. HTTP is the default in the reference work.

## Semantics

The first-class object is the **Protocol Document**. Agents discover, propose, accept, and adapt PDs at runtime. The framing is the "Agent Communication Trilemma" between versatility, efficiency, and portability.

## Observability hooks

None defined at the protocol level. Tracing would have to attach to the negotiated sub-protocol.

## Maturity and governance

- Status: research. Paper-and-demo level. Oxford team plus contributors.
- License: see the paper-demo repo (`agora-protocol/paper-demo`).
- Adoption: not enterprise-deployed as of the public sources reviewed.
- Why it is in this survey: a reasonable steel-man of "do we need a wire protocol at all, or can agents negotiate one per conversation". Useful as a thought experiment when someone proposes a fancier wire for the relay.

## Primary sources

- Paper: https://arxiv.org/abs/2410.11905
- Project page: https://agoraprotocol.org/
- Demo repo: https://github.com/agora-protocol/paper-demo
