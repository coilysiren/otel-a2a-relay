# otel-a2a-relay-arize-phoenix

Arize Phoenix backend extension for `otel-a2a-relay-core`. Adds:

- `o2r-harness` - validation harness that posts a worked-example trace and prints validation steps to take in Phoenix.
- `o2r-phoenix-bootstrap` - idempotently provisions the relay's expected annotation configs (`relay_failure_class`, `task_outcome_correct`) and named datasets (`relay-decisions-golden`, `relay-failures-regression`) via Phoenix's REST API.
- `o2r-view` - CLI that reduces a Phoenix session's spans to a readable per-hop log. Also drives `make gif` (animated topology GIF for one session).
- `otel_a2a_relay_arize_phoenix.viz` - GIF rendering of session topologies. Optional `viz` extra (Pillow).
- `otel_a2a_relay_arize_phoenix.phoenix` - REST + GraphQL query helpers.

Pairs with `otel-a2a-relay-core` to form the Phoenix-flavored stack. Sibling: `otel-a2a-relay-tempo-grafana` for Tempo + Grafana.
