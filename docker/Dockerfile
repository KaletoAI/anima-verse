# syntax=docker/dockerfile:1
# ── Stage 1: Builder ─────────────────────────────────────────────────────────
# Installiert die Python-Dependencies aus pyproject.toml (single source of truth —
# NICHT von Hand nachpflegen). Build-Tools nur hier, nicht im Runtime-Image.
# Python 3.13: der Code nutzt 3.12+-Syntax (z.B. Backslashes in f-String-
# Ausdruecken) — 3.11 bricht beim Import. An die lokale Dev-Version angeglichen.
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# pyproject + README + Paketcode (poetry-core braucht das Paket zum Bauen).
# Dependencies kommen ausschliesslich aus [project].dependencies in pyproject.toml.
COPY pyproject.toml README.md ./
COPY app/ ./app/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim

# libgl1/libglib2.0 fuer onnxruntime/rembg (Hintergrundentfernung),
# curl fuer fetch_models.sh + Healthcheck-Komfort.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installierte Packages + Konsolen-Skripte aus dem Builder uebernehmen.
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# App-Code + Laufzeit-Assets.
#   app/      — Backend
#   static/   — gebaute Frontend-Assets (game_admin/play SPA, committed)
#   shared/   — LLM-Prompt-Templates, Character-Templates, Sprachen, Schemas (PFLICHT)
#   worlds/   — Welten inkl. gebackener Demo-Welt (worlds/demo/world.db)
COPY app/ ./app/
COPY static/ ./static/
COPY shared/ ./shared/
COPY worlds/ ./worlds/
COPY start.sh fetch_models.sh ./
COPY docker/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./start.sh ./fetch_models.sh ./docker-entrypoint.sh

# Lokale Modelle vorab holen (u2net fuer rembg + bge-small fuer Pose-Embeddings).
# Nicht-fataler Schritt: ohne Build-Internet laden sie sonst beim ersten Gebrauch
# nach (und persistieren dann im /app/models-Volume).
RUN ./fetch_models.sh || echo "[build] fetch_models.sh uebersprungen — Lazy-Download zur Laufzeit"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["./docker-entrypoint.sh"]
