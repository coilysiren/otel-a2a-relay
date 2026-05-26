#!/usr/bin/env bash
# Local replay of regen-gif-baseline.yml's regen step (linux/amd64 docker).

set -euo pipefail

PYTHON_IMAGE=${PYTHON_IMAGE:-python:3.13-slim}
REPO_ROOT=$(git rev-parse --show-toplevel)

echo "==> Local replay of regen-gif-baseline in ${PYTHON_IMAGE}"
echo "==> Repo root: ${REPO_ROOT}"

docker run --rm \
  --platform linux/amd64 \
  -v "${REPO_ROOT}:/work" \
  -w /work \
  "${PYTHON_IMAGE}" \
  bash -c '
    set -e
    apt-get update -qq && apt-get install -y -qq git curl ca-certificates >/dev/null
    pip install --quiet uv
    uv sync --frozen --all-packages
    make gif-fixture-update
  '

echo
echo "==> Done. Diff to inspect:"
echo "    git diff -- arize_phoenix/assets/session-topology.gif"
echo
echo "==> The workflow's commit-back step is NOT replayed locally."
echo "    Push the diff and let regen-gif-baseline dispatch re-commit it,"
echo "    or commit it directly if you trust the byte-for-byte match."
