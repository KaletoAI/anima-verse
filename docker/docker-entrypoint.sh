#!/usr/bin/env bash
# Docker entrypoint: startet die App im Vordergrund (haelt den Container am Leben).
#
# Welt-Auswahl ueber die Umgebungsvariable WORLD (Default: demo). paths.init()
# liest STORAGE_DIR — wir mappen WORLD darauf. Es gibt KEINE .env-Datei:
# Provider/Backends werden pro Welt in config.json bzw. ueber /admin/settings
# konfiguriert (siehe docker/DEPLOYMENT.md).
set -euo pipefail

WORLD="${WORLD:-demo}"
export STORAGE_DIR="/app/worlds/${WORLD}"

echo "[docker] Starting Anima Verse — world '${WORLD}' (STORAGE_DIR=${STORAGE_DIR})"
exec python -m uvicorn app.server:app --host 0.0.0.0 --port 8000
