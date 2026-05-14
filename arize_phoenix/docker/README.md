# Always-on Phoenix

`docker-compose.yml` in this directory stands up Arize Phoenix as a
long-lived service. The Mac-local `make phoenix-fg` recipe is fine for
desktop work, but the sequencing gate in `AGENTS.md` calls for a real
Phoenix run before any spec-shape change ships, and "real" means
reachable when Kai is on her phone. This compose file is what serves
that role.

## Bring-up

From the repo root:

```sh
make phoenix-up                # docker compose up -d
make phoenix-status            # ps
make phoenix-logs              # follow logs
make phoenix-down              # stop, preserve volume
make phoenix-clean             # stop + wipe volume
```

The compose pins `arizephoenix/phoenix:version-15.4.0` to match the
harness-validated Phoenix major. Bump the tag in lock-step with
`make phoenix-harness`.

## Endpoints

- HTTP UI + OTLP/HTTP receiver: <http://localhost:6006>
- OTLP/gRPC receiver: `localhost:4317`

The relay's `OTEL_EXPORTER_OTLP_ENDPOINT` default already targets
`http://localhost:6006`, so harness runs against this stack need no
extra config. For remote-host deployments (homelab k3s pod, dedicated
always-on box), set `OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>:6006`
before invoking the harness.

## State

SQLite DB lives in the `phoenix-data` named volume, mounted at
`/phoenix-data` inside the container (via `PHOENIX_WORKING_DIR`).
`make phoenix-clean` wipes it. On a Phoenix major-version bump, expect
to clean the volume if migrations fail; the DB is disposable.

## Auth

There is no auth in front of Phoenix in this compose. Keep it on a
homelab-internal address. Public exposure is out of scope.
