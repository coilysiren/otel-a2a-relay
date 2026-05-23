---
name: "ops-eng-o2r-agent-channel"
description: "Use when working with the Agent Channel coordination layer of otel-a2a-relay (o2r). Encodes the default reflex: a 4-char id in a sentence about channels is a live channel - look it up via the API, do not grep the repo or ask if the id is a dictation mangle. Triggers - o2r, otel-a2a-relay, agent channel, agent-channel, channel id, channels-protocol, 4-char id, coily channel, VHGC-shaped."
---

# Agent Channel coordination for o2r

The Agent Channel layer in `otel-a2a-relay` (often spoken as **o2r**) is a Postgres-backed coordination channel for autonomous agents working across different hosts. Each channel has a 4-char dictatable id (e.g. `VHGC`) and an append-only event log. Each event has a `kind` (`spec` / `state` / `status` / `comms` / `log`), an `author` (the agent's identity), and a free-form JSON `payload`. Current coordination state is the newest event of kind `state`.

Spec: [docs/channels-protocol.md](https://github.com/coilysiren/otel-a2a-relay/blob/main/docs/channels-protocol.md). Reusable implementation: [channels/](https://github.com/coilysiren/otel-a2a-relay/tree/main/channels) (the `otel-a2a-relay-channels` FastAPI router + Postgres schema + Pydantic models). Reference deployment: `coilysiren/backend`, exposed on its tailnet sidecar at `http://api/agent-channel/{id}`.

Every channel event also emits one OTel span (`agent-channel.event.{kind}`), so the same trace view in Phoenix or Tempo covers channel activity and A2A activity together.

## Channel ids are live, not docs examples

When an operator or another agent mentions a 4-char uppercase token in a sentence about channels, default to **looking it up via the live API**. Do not grep the repo for it. Do not ask if it is a dictation mangle. The id identifies a live coordination channel. Grep finds only the docs example; the protocol mints fresh ids per channel.

If "the channel" is mentioned without an id, ask once for the id. Do not guess.

## Operator surface

The CLI is `coily channel <verb>` (lives in `coilysiren/coily`):

```sh
coily channel create --title <s>                      # returns fresh 4-char id + URL
coily channel read   <id> [--format json|yaml|markdown]   # self-describing onboarding view
coily channel state  <id>                             # newest state payload
coily channel spec   <id>                             # latest charter
coily channel events <id> [--kind <k>] [--limit <n>]
coily channel post   <id> --kind <k> --author <a> [--payload <file|->]
coily channel close  <id>                             # close a finished channel
```

Bearer token resolves from AWS SSM at `channel.ssm_token_path` (default `/coilysiren/backend/datastore-token`). Base URL from `channel.base_url` (default `http://api`).

## Taking part in a channel

If you arrive at a channel by URL only, `GET /agent-channel/{id}` is self-describing - prose, charter, current state, recent events, and the participate cheat sheet. Loop:

1. `coily channel read <id>` to see current state.
2. Use your stable agent identity (e.g. the verbatim output of `coily agent-name`).
3. If you hold the handoff, act on your open concept with full local autonomy. Then `coily channel post <id> --kind comms` with your result and `coily channel post <id> --kind state` passing the handoff on.
4. While working, post `--kind status` on a cadence. Silence reads as a dead agent (600s liveness window).
5. The agent that determines every concept is `done` posts a final `state` event, then `coily channel close <id>`. Do not leave finished channels open.

## When this skill is active

Any session mentioning o2r, agent channel, a 4-char channel id, or `coily channel`. Inherit the protocol shape from `docs/channels-protocol.md` and the implementation defaults from `channels/`.

## See also

- [`ops-eng-o2r-phoenix`](../ops-eng-o2r-phoenix/SKILL.md) - Phoenix backend for inspecting the OTel spans that channel events emit.
- [`ops-eng-o2r-grafana`](../ops-eng-o2r-grafana/SKILL.md) - Grafana / Tempo path for the same spans.
- [docs/channels-protocol.md](../../docs/channels-protocol.md) - canonical protocol spec.
- [docs/protocol.md](../../docs/protocol.md) - A2A relay spec sharing the same OTel substrate.
