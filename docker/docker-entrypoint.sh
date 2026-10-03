#!/usr/bin/env bash
# Docker entrypoint: runs the app in the foreground (keeps the container alive).
#
# World selection via the WORLD environment variable (default: demo).
# paths.init() reads STORAGE_DIR — we map WORLD onto it. There is NO .env file:
# providers/backends are configured per world in config.json or through
# /admin/settings (see docker/DEPLOYMENT.md).
#
# The instance directory (per-installation server config + secrets) is a
# path override like STORAGE_DIR: paths.init_instance() reads INSTANCE_DIR and
# has no default of its own. It lives on its own volume (docker-compose.yml).
set -euo pipefail

WORLD="${WORLD:-demo}"
export STORAGE_DIR="/app/worlds/${WORLD}"
export INSTANCE_DIR=/app/instance

echo "[docker] Starting Anima Verse — world '${WORLD}' (STORAGE_DIR=${STORAGE_DIR}, INSTANCE_DIR=${INSTANCE_DIR})"
exec python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
