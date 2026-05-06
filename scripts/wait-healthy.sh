#!/usr/bin/env bash
set -euo pipefail

# Block until each URL passed in returns 2xx on a GET, or until 15s elapses.
# Used by `make wait` after `make up` so smoke tests don't race the boot.

deadline=$(($(date +%s) + 15))

for url in "$@"; do
  while true; do
    if curl -sf -m 1 "$url" >/dev/null; then
      break
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
      echo "timed out waiting for $url" >&2
      exit 1
    fi
    sleep 0.2
  done
done
