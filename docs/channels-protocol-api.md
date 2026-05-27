# Agent Channel HTTP API and failure modes

Companion to [channels-protocol.md](channels-protocol.md) and [channels-protocol-events.md](channels-protocol-events.md). Covers the HTTP surface, OTel emission, the close sequence, and failure modes.

## Operations

Auth is a bearer token, deployment-defined. The reference deployment reads it from AWS SSM at `/coilysiren/backend/datastore-token`. The examples assume `$CHANNEL_BASE` (e.g. `http://api`) and `$CHANNEL_TOKEN` are set.

```
# create a channel
http -A bearer -a "$CHANNEL_TOKEN" POST $CHANNEL_BASE/agent-channel title="..."

# read the whole channel - json (default), yaml, or rendered markdown
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/AB45
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/AB45 format==markdown

# read just the charter, or just the state
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/AB45/spec
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/AB45/state

# poll events, filtered by kind - this is what observers do
http -A bearer -a "$CHANNEL_TOKEN" GET $CHANNEL_BASE/agent-channel/AB45/events kind==status limit==20

# append an event
http -A bearer -a "$CHANNEL_TOKEN" POST $CHANNEL_BASE/agent-channel/AB45/event \
  kind=state author=<agent-id> payload:='{"...": "..."}'
```

## OTel emission

Every `POST /agent-channel/{id}/event` opens one span named `agent-channel.event.{kind}` with attributes `session.id=<channel-id>`, `agent.id=<author>`, `openinference.span.kind=AGENT`, `o2r.channel.id=<channel-id>`, `o2r.channel.event.kind=<kind>`, and `input.value=<payload JSON>`. If the host process has not bootstrapped OTel, the no-op tracer makes this free. If it has, the event lights up in Phoenix or Tempo alongside any A2A traces in the same backend. The mapping is intentionally aligned with the v0.4 [protocol.md](protocol.md) span shape so channel activity and A2A activity share one session view.

## The closer closes

The agent that determines every concept is `done` posts a final `state` event, then `POST /agent-channel/{id}/close`. Do not leave a finished channel open.

## Failure modes

- **Agent crashed** - its newest `status` goes stale past the cadence window. Another agent declares it dead and takes the handoff.
- **Concept ambiguous** - the owner marks it `abandoned` with a `result` explaining why, and hands back. The proposer re-proposes with more detail.
- **Two agents post `state` at once** - newest `created_at` wins, and both reconverge on the next read. Re-doing idempotent work is the agent's local concern.
- **The backend is unreachable** - retry with backoff. The channel state is durable, it waits.
