# LUCA-flow demo

[`examples/luca-flow/`](../examples/luca-flow/) is a real multi-agent choreography that dogfoods the relay end-to-end. Eight worker subprocesses + an orchestrator + a planner + a validator + a deployer build the AURORA microsite (a fictional consumer desk lamp marketed as if it physically channels solar-wind charged particles) from real public-domain NASA imagery committed to the repo.

Star topology is enforced by the relay; one worker deliberately crashes, another deliberately tries to bypass the orchestrator and gets a `-32010` from the relay's gate.

The demo only depends on `otel-a2a-relay-core`. Pick whichever backend you want to send the spans to:

```sh
# Phoenix
make phoenix-fg
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 make luca-demo

# Tempo + Grafana
make tempo-up
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make luca-demo
```

The same flow runs in CI on every push (`.github/workflows/luca-demo.yml`), with Phoenix in CI as a background process. The built `dist/` is uploaded as a workflow artifact. See [`examples/luca-flow/README.md`](../examples/luca-flow/README.md) for the choreography and validation rules.

## See also

- [quickstart.md](quickstart.md) - bring-up recipes for both backends.
- [README.md](../README.md) - intro and the canonical pitch.
