# Agent instructions

See `../AGENTS.md` for workspace-level conventions (git workflow, test/lint autonomy, readonly ops, writing voice, deploy knowledge). This file covers only what's specific to this repo.

---

## Public repo

This is a public repo. Same rules as coilyco-ai's "treat as public" surface: no LAN IPs, public IPs, addresses, real names, secondary email aliases, or private identity tags. Role-based descriptors only when referring to people in issues, PR bodies, commit messages, or docs.

## Protocol doc is the source of truth

`docs/protocol.md` is the canonical specification of the A2A-to-OTel-span mapping. The relay's job is to be a faithful implementation of it. The harness's job is to validate it against a real Phoenix.

If the doc and the implementation disagree, the doc wins by default and the code gets fixed. The exception is when a Phoenix harness run surfaces a real finding that the doc got wrong - then the doc gets rewritten and the version bumped (v0 -> v0.1 was the first such cycle, see otel-a2a-relay#1 for the precedent).

Do not ship a protocol change without re-running the harness. "Mentally simulated" is how v0 ended up wrong about Resource attributes and span links.

## Sequencing gate

The order is fixed:

1. Protocol doc + harness updated together.
2. Harness re-run against a real Phoenix instance (`phoenix serve` locally, or the homelab Phoenix once it exists). Both the GraphQL spans query and the Sessions query must show the new attributes where the spec calls for them.
3. Only then: relay code changes that depend on the new shape.

Skipping step 2 is how the spec drifts from reality. Do not skip it even when "the change is small."

## Validating against Phoenix

Local Phoenix:

```sh
uv sync
uv run phoenix serve &
uv run o2r-harness
```

Or via pyinvoke: `invoke phoenix` and `invoke harness`. The full task list is in `tasks.py`.

Two GraphQL queries cover the validation surface:

- Per-span attribute check:
  ```graphql
  { projects(first:1) { edges { node { spans(first:20) { edges { node { name spanKind attributes } } } } } } }
  ```
- Sessions grouping check:
  ```graphql
  { projects(first:1) { edges { node { sessions(first:5) { edges { node { sessionId numTraces } } } } } } }
  ```

Phoenix's REST API at `/v1/projects/<id>/spans` shows span attributes too, but does NOT show OTel Resource attributes or span links. If you need to confirm what Phoenix is actually exposing, GraphQL introspection is authoritative:

```graphql
{ __type(name:"Span") { fields { name } } }
```

If a field you expect is not on this list, Phoenix is dropping it and the spec needs to compensate. v0.1 dropped Resource attributes and span links specifically because of this introspection.

## Phoenix DB resets

`phoenix serve` keeps state in `~/.phoenix/phoenix.db`. Across version upgrades the migration can fail with `alembic.script.revision.ResolutionError: No such revision or branch '...'`. Fix is `rm ~/.phoenix/phoenix.db` and restart - the harness is single-shot, the DB is disposable.

## Operator surface lives in `coily`

The operator-facing CLI for talking to a relay is `coily channel <verb>` in `coilysiren/coily`. This repo ships only the relay (`serve` mode, A2A endpoints, OTLP emitter). When a feature spans both, file the relay-side issue here and the CLI-side issue in `coily`, cross-linked.

## Versioning

Protocol versions live in the doc heading (`# Protocol vX.Y`). Bump on any spec-shape change that the harness has revalidated. Don't bump for prose-only edits.

The relay binary itself will get its own semver once there is a binary. For now the protocol version is the only version that matters.
