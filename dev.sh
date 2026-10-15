#!/usr/bin/env bash
set -euo pipefail

# Run the AEGIS PRO stack with correct host UID/GID and an absolute
# verifier workdir path. These values are machine-specific, so they
# are computed at runtime here rather than committed to demo.env.
#
# Usage: ./dev.sh up -d
#        ./dev.sh down
#        ./dev.sh exec orchestrator python -m pytest tests/ -v
#        ./dev.sh logs -f orchestrator
#
# Requires: docker-compose, and a demo.env at the repo root.

# Build the verifier sandbox image on first 'up' if it doesn't
# exist. The image is python:3.11-slim plus pytest; the verifier
# runs the target repo's tests inside it with --network none, so
# pytest has to be pre-installed — no pip at verification time.
#
# Idempotent: subsequent runs skip the build when the image exists.
# To force a rebuild after editing Dockerfile.verifier, run
# `docker rmi aegis-verifier:latest` first.
if [ "${1:-}" = "up" ]; then
  if ! docker image inspect aegis-verifier:latest >/dev/null 2>&1; then
    echo "Building aegis-verifier:latest..."
    docker build \
      -t aegis-verifier:latest \
      -f backend/orchestrator/Dockerfile.verifier \
      backend/orchestrator/
  fi
fi

HOST_UID="$(id -u)" \
HOST_GID="$(id -g)" \
VERIFIER_HOST_WORKDIR="$(pwd)/verifier-workdir" \
  exec docker-compose --env-file demo.env "$@"
