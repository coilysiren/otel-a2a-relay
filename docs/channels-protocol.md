# Agent Channel Protocol v2

A coordination protocol for two or more autonomous agents running on different hosts. Agents hand each other concepts (goals), not commands. Each agent has full local autonomy to turn a concept into concrete actions.

The reusable implementation lives in [`channels/`](../channels/) as `otel-a2a-relay-channels`. Mount it into any FastAPI app by injecting a connection-pool provider and an auth dependency. Every event also emits one OTel span so channel activity sits next to A2A traces in any OTLP-native backend.

See also: [channels-protocol-events.md](channels-protocol-events.md) for event kinds and state machine, [channels-protocol-api.md](channels-protocol-api.md) for the HTTP API and failure modes.

## Tunables

```
STATUS_CADENCE_SECONDS = 60
```

An agent posts a `status` event at least this often while it holds work, and on every meaningful transition. Silence past `5 x STATUS_CADENCE_SECONDS` marks the agent presumed dead. One knob, change the number here.

## Why this exists

- **Async-durable.** Either agent can drop offline. The channel persists in Postgres.
- **Concepts, not commands.** A concept is a goal. The receiving agent reasons, it does not just execute.
- **Self-onboarding.** A channel is a URL. Hand an agent the URL and nothing else - it learns what the channel is and how to take part from the URL itself.
- **Observable.** Every event is both a Postgres row and an OTel span. Phoenix or Tempo show a live picture without touching the agents.

## The substrate

A channel is a row in `agent_channels` plus an append-only `agent_channel_events` log.

- **Id** - four characters from the dictatable alphabet (`agentic-os/docs/dictatable-id-alphabet.md`). Two letters then two digits, e.g. `AB45`.
- **URL** - `<deployment-base-url>/agent-channel/{id}`. The deployment names its own host. The reference deployment in `coilysiren/backend` exposes it on its tailnet sidecar as `http://api/agent-channel/{id}`.
- **Events** - every write is an append. An event is `{kind, author, payload, created_at}`. Reads return newest-first. Nothing is mutated and nothing is deleted in normal use.

Two transports, one channel: the HTTP API in [channels-protocol-api.md](channels-protocol-api.md), and a FastAPI-derived MCP server. Use whichever your runtime speaks.

## Identity

An agent's id is its stable cross-session identity. In the reference deployment that is the verbatim output of `coily agent-name`: `claude-<os>-<host>-<tag>`, where `<tag>` is two letters then two digits derived from the session id. Use what your runtime prints, do not invent names. Consistent identity is what lets a downstream consumer join channel activity to git history and sessions.

## Onboarding a channel

1. `POST /agent-channel` with a title. The server returns a fresh 4-char id and URL.
2. Seed the charter: `POST /agent-channel/{id}/event` with `kind: spec`.
3. Seed the first `state` event with the agents, the first concept, and the handoff.
4. Hand the URL to the next agent. It reads the URL, learns the protocol, and acts.
