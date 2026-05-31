#!/usr/bin/env bash
# Docker entrypoint: main app im Vordergrund (haelt den Container am Leben).
set -euo pipefail

echo "[docker] Starting main app..."
exec python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
