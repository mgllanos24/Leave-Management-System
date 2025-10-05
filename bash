#!/usr/bin/env bash
set -euo pipefail

# Load local development overrides if present. Production deployments should
# provide secrets via the environment or a dedicated secret manager.
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -o allexport
  source .env
  set +o allexport
fi

: "${ADMIN_EMAIL:?ADMIN_EMAIL environment variable is required}"
: "${ADMIN_USERNAME:?ADMIN_USERNAME environment variable is required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD environment variable is required}"

exec python server.py "${1:-8080}"

