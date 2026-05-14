# Protocol decision log

Auto-generated from `git blame` on `docs/protocol.md`. Do not hand-edit. Regenerate with `make protocol-decisions`.

Each section lists the commits that have shaped its current text, oldest first.

## Topology

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README
- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology

## Sessions

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README

## Agent Graph

- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology

## Worked example: A streams a task to B, B completes, A acks

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README
- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology
- `96d37d02` 2026-05-06 - tracing: add bootstrap() helper and rename a2a.* wire attrs to o2r.*

## Conventions

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README
- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology
- `97e95b1d` 2026-05-07 - protocol v0.3: data-legibility surface for Phoenix

## Tracing bootstrap

- `96d37d02` 2026-05-06 - tracing: add bootstrap() helper and rename a2a.* wire attrs to o2r.*
- `b668c4cf` 2026-05-12 - docs: scrub colony / enterprise vocabulary from tracing.bootstrap docstring and protocol example
- `8374019d` 2026-05-12 - protocol(v0.4): retire colony / multi-tenant vocab from tracing.bootstrap(), closes #121

## Phoenix-validated

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README
- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology
- `96d37d02` 2026-05-06 - tracing: add bootstrap() helper and rename a2a.* wire attrs to o2r.*
- `97e95b1d` 2026-05-07 - protocol v0.3: data-legibility surface for Phoenix

## Operator surface

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README

## Sequencing

- `cf8519d0` 2026-05-05 - seed v0 protocol doc and pitch README
- `72ddfe8d` 2026-05-05 - protocol v0.1: agent identity on spans, graph.node.* for topology
- `744b785b` 2026-05-06 - relay: dynamic peer registration + star-topology enforcement

## Relay-management surface (out of protocol)

- `744b785b` 2026-05-06 - relay: dynamic peer registration + star-topology enforcement
