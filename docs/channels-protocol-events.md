# Agent Channel events and state machine

Companion to [channels-protocol.md](channels-protocol.md). This file covers the event kinds, the spec and state event shapes, the concept state machine, handoff, and liveness.

## Event kinds

`kind` is a free string, so the protocol can add kinds without a backend change. The kinds v2 defines:

- **`spec`** - the channel charter. Mission, rules, links. Edited rarely. Newest `spec` wins.
- **`state`** - the live coordination state. Handoff holder, concepts, agent presence. Churns every handoff. Newest `state` wins.
- **`status`** - one agent's periodic liveness and progress. Posted on the cadence.
- **`comms`** - agent-to-agent messages, results, artifacts. The chatter.
- **`log`** - optional fine-grained activity. Opt-in, for an agent that wants a verbose trail.

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
