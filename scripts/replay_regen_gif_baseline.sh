#!/usr/bin/env bash
# Local replay of .github/workflows/regen-gif-baseline.yml's regen step.
#
# Pillow's freetype build is per-platform, so the byte-exact baseline can
# only be produced on linux/amd64. This script runs the same regen step in
# a docker container that mirrors the workflow's runner, so iteration on
# the regen logic doesn't have to round-trip through GitHub Actions.
#
# The commit-back step is intentionally NOT replayed - that requires a
# GitHub token and signed-commit machinery the workflow handles. After a
# successful local run, diff `arize_phoenix/assets/session-topology.gif`
# and commit by hand, or push and let the dispatch workflow re-commit it.
#
# Usage:
#   scripts/replay_regen_gif_baseline.sh
#
# Environment:
#   PYTHON_IMAGE  override the python image (default: python:3.13-slim)

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
