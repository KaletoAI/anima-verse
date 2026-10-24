# syntax=docker/dockerfile:1
# ── Stage 1: Builder ─────────────────────────────────────────────────────────
# Install Python dependencies from pyproject.toml, the single source of truth.
# Build tools stay in this stage, outside the runtime image.
# Python 3.13 matches local development; the code requires Python 3.12+ syntax.
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# poetry-core needs the README and package sources to build the package.
# Dependencies come exclusively from [project].dependencies in pyproject.toml.
COPY pyproject.toml README.md ./
COPY app/ ./app/

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim

# libgl1/libglib2.0 support onnxruntime/rembg background removal.
# curl supports fetch_models.sh and health checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages and console scripts from the builder.
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Application code and runtime assets.
#   app/      — backend
#   static/   — committed frontend builds: game_admin/ and client3d/
#   shared/   — required LLM prompts, character templates, languages and schemas
#   plugins/  — required skill packages: app/plugins/loader.py expects /app/plugins.
#               Without these the server boots, but characters have no skills:
#               no movement, sleep or party (review 2026-09-20, DS-2).
#               Private pack symlinks and plugins/installed/ are excluded by
#               the root .dockerignore.
#   worlds/   — worlds including the bundled demo world (worlds/demo/world.db)
COPY app/ ./app/
COPY static/ ./static/
COPY shared/ ./shared/
COPY plugins/ ./plugins/
COPY worlds/ ./worlds/
COPY start.sh fetch_models.sh ./
COPY docker/docker-entrypoint.sh ./docker-entrypoint.sh
# The entrypoint runs the one-time instance-config migration on every start
# (a no-op once the instance config exists).
COPY scripts/migrate_instance_config.py ./scripts/migrate_instance_config.py
RUN chmod +x ./start.sh ./fetch_models.sh ./docker-entrypoint.sh

# Prefetch local models: u2net for rembg and bge-small for pose embeddings.
# Non-fatal: without build internet access, they download on first use and
# persist in the /app/models volume.
RUN ./fetch_models.sh || echo "[build] fetch_models.sh skipped — models download lazily at runtime"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["./docker-entrypoint.sh"]
