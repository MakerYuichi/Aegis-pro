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

HOST_UID="$(id -u)" \
HOST_GID="$(id -g)" \
VERIFIER_HOST_WORKDIR="$(pwd)/verifier-workdir" \
  exec docker-compose --env-file demo.env "$@"
