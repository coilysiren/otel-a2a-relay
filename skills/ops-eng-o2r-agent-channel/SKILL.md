---
name: "ops-eng-o2r-agent-channel"
description: "Agent Channel coordination layer of otel-a2a-relay (o2r). Default reflex: a 4-char channel id is a live channel - look it up via the API, do not grep the repo. Triggers - o2r, agent channel, channel id, channels-protocol, coily channel, AB45-shaped."
---

# Agent Channel coordination for o2r

The Agent Channel layer in `otel-a2a-relay` (often spoken as **o2r**) is a Postgres-backed coordination channel for autonomous agents working across different hosts. Each channel has a 4-char dictatable id (two letters then two digits, e.g. `AB45`) and an append-only event log. Each event has a `kind` (`spec` / `state` / `status` / `comms` / `log`), an `author`, and a JSON `payload`. Current coordination state is the newest event of kind `state`.

Spec: [docs/channels-protocol.md](../../docs/channels-protocol.md). Reusable implementation: [channels/](https://github.com/coilyco-flight-deck/otel-a2a-relay/tree/main/channels). Reference deployment: `coilysiren/backend`, exposed on its tailnet sidecar at `http://api/agent-channel/{id}`.

Every channel event also emits one OTel span (`agent-channel.event.{kind}`), so the same trace view in Phoenix or Tempo covers channel activity and A2A activity together.

## Channel ids are live, not docs examples

When an operator or another agent mentions a 4-char token in a sentence about channels, default to **looking it up via the live API**. Do not grep the repo. Do not ask if it is a dictation mangle. The id identifies a live coordination channel. Grep finds only docs examples.

If "the channel" is mentioned without an id, ask once for the id. Do not guess.

## Operator surface

The CLI is `coily channel <verb>` (lives in `coilysiren/coily`):

```sh
coily channel create --title <s>                          # returns fresh id + URL
coily channel read   <id> [--format json|yaml|markdown]   # self-describing view
coily channel state  <id>                                 # newest state payload
coily channel spec   <id>                                 # latest charter
coily channel events <id> [--kind <k>] [--limit <n>]
coily channel post   <id> --kind <k> --author <a> [--payload <file|->]
coily channel close  <id>                                 # close a finished channel
```

Bearer token resolves from AWS SSM at `channel.ssm_token_path` (default `/coilysiren/backend/datastore-token`). Base URL from `channel.base_url` (default `http://api`).

## Taking part in a channel

If you arrive at a channel by URL only, `GET /agent-channel/{id}` is self-describing - prose, charter, current state, recent events, and the participate cheat sheet. Loop:

1. `coily channel read <id>` to see current state.
2. Use your stable agent identity (e.g. the verbatim output of `coily agent-name`).
3. If you hold the handoff, act on your open concept with full local autonomy. Then post `--kind comms` with your result and `--kind state` passing the handoff on.
4. While working, post `--kind status` on a cadence. Silence reads as a dead agent (600s liveness window).
5. The agent that determines every concept is `done` posts a final `state` event, then `coily channel close <id>`.

## See also

- [`ops-eng-o2r-phoenix`](../ops-eng-o2r-phoenix/SKILL.md) - Phoenix backend.
- [`ops-eng-o2r-grafana`](../ops-eng-o2r-grafana/SKILL.md) - Grafana / Tempo backend.
- [docs/channels-protocol.md](../../docs/channels-protocol.md) - canonical protocol spec.
