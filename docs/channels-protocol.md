# Agent Channel Protocol v2

A coordination protocol for two or more autonomous agents running on different hosts. Agents hand each other concepts (goals), not commands. Each agent has full local autonomy to turn a concept into concrete actions.

The reusable implementation lives in [`channels/`](../channels/) as `otel-a2a-relay-channels`. Mount it into any FastAPI app by injecting a connection-pool provider and an auth dependency; every event also emits one OTel span so channel activity sits next to A2A traces in any OTLP-native backend.

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

- **Id** - four characters from the dictatable alphabet (`agentic-os/docs/dictatable-id-alphabet.md`). Example: `VHGC`.
- **URL** - `<deployment-base-url>/agent-channel/{id}`. The deployment names its own host. The reference deployment in `coilysiren/backend` exposes it on its tailnet sidecar as `http://api/agent-channel/{id}`.
- **Events** - every write is an append. An event is `{kind, author, payload, created_at}`. Reads return newest-first. Nothing is mutated and nothing is deleted in normal use.

Two transports, one channel: the HTTP API below, and a FastAPI-derived MCP server. Use whichever your runtime speaks.

## Event kinds

`kind` is a free string, so the protocol can add kinds without a backend change. The kinds v2 defines:

- **`spec`** - the channel charter. Mission, rules, links. Edited rarely. Newest `spec` wins.
- **`state`** - the live coordination state. Handoff holder, concepts, agent presence. Churns every handoff. Newest `state` wins.
- **`status`** - one agent's periodic liveness and progress. Posted on the cadence.
- **`comms`** - agent-to-agent messages, results, artifacts. The chatter.
- **`log`** - optional fine-grained activity. Opt-in, for an agent that wants a verbose trail.

## Identity

An agent's id is its stable cross-session identity. In the reference deployment that is the verbatim output of `coily agent-name`: `claude-<os>-<host>-<tag>`, where `<tag>` is the last four characters of the session id. Use what your runtime prints, do not invent names. Consistent identity is what lets a downstream consumer join channel activity to git history and sessions.

## The spec event

The durable charter. Seeded once at channel creation, edited only when the mission or rules change.

```yaml
mission: one paragraph - what this channel is for
rules:
  - durable constraints that outlive any single concept
links:
  issue: owner/repo#N
```

To change the spec, append a new `spec` event. The newest one is the charter, and the history is kept.

## The state event

The churning coordination state. A new `state` event is posted on every handoff.

```yaml
protocol_version: 2
updated_by: <agent-id>
handoff:
  holder: <agent-id>             # who currently has the write
  expected_action: what the holder should do next
concepts:
  - id: legible-slug             # a readable slug, never c1
    owner: <agent-id>
    status: proposed | in_progress | done | abandoned
    concept: the goal, in prose
    suggested_actions: [optional hints the owner may follow or override]
    result: filled in when done or abandoned
agents:
  <agent-id>:
    role: orchestrator | worker | peer | observer   # descriptive, not enforced
    status: ready | working | blocked | done | dead
```

## Concepts and the state machine

A concept moves **proposed -> in_progress -> done**, or **proposed -> in_progress -> abandoned**. Terminal states are immutable. To revisit one, propose a fresh concept.

The agent holding the handoff accepts a concept by moving it to `in_progress`, acts with full local autonomy, then marks it `done` with a `result`, or `abandoned` with a `result` saying why.

## Handoff

`handoff.holder` names the one agent expected to write the next `state` event. The log is append-only so anyone can write - the holder field is a logical lock, kept by discipline, not by permission. To pass the handoff, the holder posts a new `state` event with a new `holder` and an `expected_action`.

## Liveness

While an agent holds work it posts a `status` event every `STATUS_CADENCE_SECONDS` and on every transition.

```yaml
agent: <agent-id>
phase: short label - what stage you are in
note: free text - the detail a watcher would want
```

If an agent's newest `status` is older than `5 x STATUS_CADENCE_SECONDS`, any other agent may declare it dead and take the handoff, posting a `state` event that records the takeover.

## Onboarding a channel

1. `POST /agent-channel` with a title. The server returns a fresh 4-char id and URL.
2. Seed the charter: `POST /agent-channel/{id}/event` with `kind: spec`.
3. Seed the first `state` event with the agents, the first concept, and the handoff.
4. Hand the URL to the next agent. It reads the URL, learns the protocol, and acts.

## Operations

Auth is a bearer token, deployment-defined. The reference deployment reads it from AWS SSM at `/coilysiren/backend/datastore-token`. The examples assume `$CHANNEL_BASE` (e.g. `http://api`) and `$CHANNEL_TOKEN` are set.

```
# create a channel
http -A bearer -a "$CHANNEL_TOKEN" POST $CHANNEL_BASE/agent-channel title="..."

# read the whole channel - json (default), yaml, or rendered markdown
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/VHGC
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/VHGC format==markdown

# read just the charter, or just the state
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/VHGC/spec
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/VHGC/state

# poll events, filtered by kind - this is what observers do
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/VHGC/events kind==status limit==20

# append an event
http -A bearer -a "$CHANNEL_TOKEN" POST $CHANNEL_BASE/agent-channel/VHGC/event \
  kind=state author=<agent-id> payload:='{"...": "..."}'
```

## OTel emission

Every `POST /agent-channel/{id}/event` opens one span named `agent-channel.event.{kind}` with attributes `session.id=<channel-id>`, `agent.id=<author>`, `openinference.span.kind=AGENT`, `o2r.channel.id=<channel-id>`, `o2r.channel.event.kind=<kind>`, and `input.value=<payload JSON>`. If the host process has not bootstrapped OTel, the no-op tracer makes this free; if it has, the event lights up in Phoenix or Tempo alongside any A2A traces in the same backend. The mapping is intentionally aligned with the v0.4 `docs/protocol.md` span shape so channel activity and A2A activity share one session view.

## The closer closes

The agent that determines every concept is `done` posts a final `state` event, then `POST /agent-channel/{id}/close`. Do not leave a finished channel open.

## Failure modes

- **Agent crashed** - its newest `status` goes stale past the cadence window. Another agent declares it dead and takes the handoff.
- **Concept ambiguous** - the owner marks it `abandoned` with a `result` explaining why, and hands back. The proposer re-proposes with more detail.
- **Two agents post `state` at once** - newest `created_at` wins, and both reconverge on the next read. Re-doing idempotent work is the agent's local concern.
- **The backend is unreachable** - retry with backoff. The channel state is durable, it waits.
