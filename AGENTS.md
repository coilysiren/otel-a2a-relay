# Agent instructions

See `../AGENTS.md` for workspace-level conventions (git workflow, test/lint autonomy, readonly ops, writing voice, deploy knowledge). This file covers only what's specific to this repo.

## Scope

`otel-a2a-relay` (a.k.a. `o2r`) is the canonical implementation of the agent-activity-to-OTel-span mapping. A2A is the wire format today; the spec generalizes to other transport-keyed channels. The relay implements the spec faithfully. The Phoenix harness validates it against reality.

## Project shape

[uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) with a backend-agnostic core and per-backend extensions: `otel-a2a-relay-core`, `-channels`, `-arize-phoenix`, `-tempo-grafana`, plus the `luca-flow` demo. Workspace map in [README.md](README.md); per-package inventory in [docs/FEATURES.md](docs/FEATURES.md).

## Repo boundaries

Ships the relay only (`serve` mode, A2A endpoints, OTLP emitter, Agent Channel router). The operator CLI lives in [`coilysiren/coily`](https://github.com/coilyco-bridge/coily) as `coily channel <verb>`. Cross-repo features: file in both, cross-link.

## Commands

Agents cannot run bare `make`, `uv`, `python`, or `docker compose`. Route every command through coily, which reads [.coily/coily.yaml](.coily/coily.yaml). Current verbs: `test-core`, `test-arize-phoenix`, `test-tempo-grafana`, `test-all`, `lint`, `fmt`, `sync`. Add new verbs to that file before invoking them; do not bypass.

## Validation

`docs/protocol.md` is the canonical specification. If the doc and the implementation disagree, the doc wins by default and the code gets fixed. The exception is when a Phoenix harness run surfaces a real finding the doc got wrong - then the doc gets rewritten and the version bumped (v0 -> v0.1 was the first cycle, see otel-a2a-relay#1).

Do not ship a protocol change without re-running the harness. "Mentally simulated" is how v0 ended up wrong about Resource attributes and span links. Sequencing gate:

1. Protocol doc + harness updated together.
2. Harness re-run against a real Phoenix (`phoenix serve` locally, or `make phoenix-up`). Both the GraphQL spans query and the Sessions query must show the new attributes.
3. Only then: relay code changes that depend on the new shape.

GraphQL introspection (`{ __type(name:"Span") { fields { name } } }`) is authoritative for what Phoenix actually exposes; the REST API at `/v1/projects/<id>/spans` does NOT show Resource attributes or span links. Full validation recipe in [docs/harness.md](docs/harness.md).

## Safety

Public repo. No LAN IPs, public IPs, addresses, real names, secondary email aliases, or private identity tags. Role-based descriptors only for people in issues, PRs, commits, docs.

`phoenix serve` keeps state in `~/.phoenix/phoenix.db`. Across upgrades the migration can fail with `alembic.script.revision.ResolutionError`. Fix: `rm ~/.phoenix/phoenix.db` and restart. The harness is single-shot; the DB is disposable.

## Cross-repo contracts

The Agent Channel protocol is specified in [docs/channels-protocol.md](docs/channels-protocol.md); clients across the org must track that spec. Operator-side changes route through `coilysiren/coily` (see Repo boundaries).

## Release

Protocol versions live in the doc heading (`# Protocol vX.Y`). Bump on any spec-shape change the harness has revalidated. Don't bump for prose-only edits. The relay binary will get its own semver once there is a binary; for now the protocol version is the one that matters.

## Agent rules

Inherited from `../AGENTS.md`. Plus: don't ship a protocol change without rerunning the harness against a real Phoenix instance.

## See also

- [README.md](README.md) - human-facing intro and quickstart.
- [docs/FEATURES.md](docs/FEATURES.md) - inventory of what ships today.
- [.coily/coily.yaml](.coily/coily.yaml) - allowlisted commands.

Cross-reference convention from [coilysiren/agentic-os#59](https://github.com/coilyco-flight-deck/agentic-os/issues/59).
