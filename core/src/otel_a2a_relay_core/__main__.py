"""uvicorn launcher for the relay. Bind via env vars or defaults."""

from __future__ import annotations

import os

import uvicorn

from otel_a2a_relay_core.server import create_app


def main() -> None:
    host = os.environ.get("OTEL_A2A_RELAY_HOST", "127.0.0.1")
    port = int(os.environ.get("OTEL_A2A_RELAY_PORT", "8080"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
